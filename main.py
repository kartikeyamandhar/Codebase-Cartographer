"""
Codebase Cartographer — Phase 2 CLI
Adds: Class nodes, Git graph, TypeScript parsing, incremental re-ingest

Usage:
  python main.py ingest <github_url> [--repo-dir <path>] [--no-git]
  python main.py query  <file_path>
  python main.py stats
"""

import os
import sys
import time
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()

from graph.schema import get_driver, apply_schema, verify_connection
from graph.writer import write_graph
from ingestion.clone import clone_repo
from ingestion.parse_python import parse_directory
from ingestion.parse_ts import parse_ts_directory
from ingestion.call_resolver import resolve_all_calls
from ingestion.git_parser import parse_git_history
from query.dependents import what_breaks_if_deleted


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_neo4j_driver():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    workspace_id = os.getenv("WORKSPACE_ID", "local_dev")

    if not password:
        click.echo("[ERROR] NEO4J_PASSWORD not set in .env")
        sys.exit(1)

    driver = get_driver(uri, user, password)
    if not verify_connection(driver):
        click.echo("[ERROR] Cannot connect to Neo4j — is Docker running?")
        sys.exit(1)

    return driver, workspace_id


def get_stored_hashes(driver, workspace_id: str) -> dict[str, str]:
    """
    Fetch all stored content_hashes for files in this workspace.
    Used for incremental re-ingest — skip unchanged files.
    Returns: {file_path -> content_hash}
    """
    with driver.session() as session:
        result = session.run(
            "MATCH (f:File {workspace_id: $wid}) "
            "WHERE f.content_hash IS NOT NULL "
            "RETURN f.path AS path, f.content_hash AS hash",
            wid=workspace_id,
        )
        return {r["path"]: r["hash"] for r in result}


def filter_changed_files(parsed_files, stored_hashes: dict) -> tuple[list, int]:
    """
    Filter parsed files to only those whose content_hash changed.
    Returns (changed_files, skipped_count).
    """
    changed = []
    skipped = 0

    for pf in parsed_files:
        stored = stored_hashes.get(pf.path)
        if stored and stored == pf.content_hash:
            skipped += 1
        else:
            changed.append(pf)

    return changed, skipped


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Codebase Cartographer — Phase 2 CLI"""
    pass


@cli.command()
@click.argument("github_url")
@click.option("--repo-dir", default=None, help="Local path to clone into")
@click.option("--no-git", is_flag=True, default=False, help="Skip git history parsing")
@click.option("--incremental", is_flag=True, default=False,
              help="Only re-process files whose content hash changed")
def ingest(github_url, repo_dir, no_git, incremental):
    """Clone a repo, parse it, and write the graph to Neo4j."""
    driver, workspace_id = get_neo4j_driver()
    apply_schema(driver)

    start = time.time()

    # Clone
    local_path = clone_repo(github_url, repo_dir)

    # ── Parse Python ──────────────────────────────────────────────────────────
    click.echo(f"\n[PARSE] Walking {local_path} for Python files")
    py_files = parse_directory(local_path, workspace_id)

    # ── Parse TypeScript / JavaScript ─────────────────────────────────────────
    click.echo(f"[PARSE] Walking {local_path} for TypeScript/JavaScript files")
    ts_files = parse_ts_directory(local_path, workspace_id)

    all_parsed = py_files + ts_files

    # ── Incremental re-ingest ─────────────────────────────────────────────────
    if incremental:
        stored_hashes = get_stored_hashes(driver, workspace_id)
        all_parsed, skipped = filter_changed_files(all_parsed, stored_hashes)
        click.echo(f"[INCREMENTAL] {skipped} files unchanged — skipping. "
                   f"{len(all_parsed)} files to process.")
    else:
        stored_hashes = {}

    if not all_parsed:
        click.echo("[INFO] No files to process.")
        driver.close()
        return

    total_functions = sum(len(pf.functions) for pf in all_parsed)
    total_classes = sum(len(pf.classes) for pf in all_parsed)
    total_imports = sum(len(pf.imports) for pf in all_parsed)

    lang_counts = {}
    for pf in all_parsed:
        lang_counts[pf.language] = lang_counts.get(pf.language, 0) + 1

    click.echo(f"[PARSE] {len(all_parsed)} files | {total_functions} functions | "
               f"{total_classes} classes | {total_imports} imports")
    click.echo(f"[PARSE] Languages: {lang_counts}")

    # ── Resolve calls (Python only for now) ───────────────────────────────────
    click.echo(f"\n[RESOLVE] Building call graph")
    call_edges = resolve_all_calls(py_files if incremental else py_files)

    # ── Git graph ─────────────────────────────────────────────────────────────
    git_graph = None
    if not no_git:
        click.echo(f"\n[GIT] Parsing commit history")
        git_graph = parse_git_history(local_path, workspace_id)

    # ── Write graph ───────────────────────────────────────────────────────────
    click.echo(f"\n[WRITE] Writing to Neo4j (workspace: {workspace_id})")
    write_graph(driver, all_parsed, call_edges, workspace_id, git_graph)

    elapsed = time.time() - start
    click.echo(f"\n[DONE] Ingestion complete in {elapsed:.1f}s")
    driver.close()


@cli.command()
@click.argument("file_path")
@click.option("--max-hops", default=5)
def query(file_path, max_hops):
    """Answer: what would break if I deleted this file?"""
    driver, workspace_id = get_neo4j_driver()
    what_breaks_if_deleted(driver, file_path, workspace_id, max_hops, verbose=True)
    driver.close()


@cli.command()
def stats():
    """Print graph stats for the current workspace."""
    driver, workspace_id = get_neo4j_driver()

    with driver.session() as session:
        result = session.run("""
            MATCH (n {workspace_id: $wid})
            RETURN labels(n)[0] AS label, count(n) AS count
            ORDER BY count DESC
        """, wid=workspace_id)

        click.echo(f"\n[STATS] Workspace: {workspace_id}")
        click.echo(f"{'─'*40}")
        for record in result:
            click.echo(f"  {record['label']:<20} {record['count']}")

        result2 = session.run("""
            MATCH ()-[r]->()
            RETURN type(r) AS rel_type, count(r) AS count
            ORDER BY count DESC
        """)
        click.echo(f"\n  Relationships:")
        for record in result2:
            click.echo(f"  {record['rel_type']:<20} {record['count']}")

    driver.close()


@cli.command()
@click.argument("file_path")
def owners(file_path):
    """Show who owns a file based on git history."""
    driver, workspace_id = get_neo4j_driver()

    with driver.session() as session:
        result = session.run("""
            MATCH (a:Author)-[r:OWNS]->(f:File {path: $path, workspace_id: $wid})
            RETURN a.name AS name, a.email AS email,
                   r.commit_count AS commits, r.last_touch AS last_touch
            ORDER BY r.commit_count DESC
        """, path=file_path, wid=workspace_id)

        records = list(result)
        if not records:
            click.echo(f"No ownership data found for: {file_path}")
        else:
            click.echo(f"\n[OWNERS] {file_path}")
            click.echo(f"{'─'*60}")
            for r in records:
                click.echo(f"  {r['name']} <{r['email']}> — "
                           f"{r['commits']} commits, last: {r['last_touch'][:10]}")

    driver.close()


@cli.command()
@click.argument("file_path")
def history(file_path):
    """Show recent commits that touched a file."""
    driver, workspace_id = get_neo4j_driver()

    with driver.session() as session:
        result = session.run("""
            MATCH (f:File {path: $path, workspace_id: $wid})-[:MODIFIED_BY]->(c:Commit)
            MATCH (c)-[:AUTHORED_BY]->(a:Author)
            RETURN c.hash AS hash, c.message AS message,
                   c.timestamp AS timestamp, a.name AS author
            ORDER BY c.timestamp DESC
            LIMIT 20
        """, path=file_path, wid=workspace_id)

        records = list(result)
        if not records:
            click.echo(f"No commit history found for: {file_path}")
        else:
            click.echo(f"\n[HISTORY] {file_path}")
            click.echo(f"{'─'*60}")
            for r in records:
                click.echo(f"  {r['timestamp'][:10]}  {r['hash'][:8]}  "
                           f"{r['author']}  {r['message'][:60]}")

    driver.close()


if __name__ == "__main__":
    cli()