"""
Phase 1 - Main CLI entry point.
Single script: clone → parse → resolve calls → write graph → answer question.

Usage:
  python main.py ingest <github_url> [--repo-dir <path>]
  python main.py query  <file_path>
  python main.py run    <github_url> <file_to_query>   # ingest + query in one step
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
from ingestion.call_resolver import resolve_all_calls
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


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Codebase Cartographer — Phase 1 CLI"""
    pass


@cli.command()
@click.argument("github_url")
@click.option("--repo-dir", default=None, help="Local path to clone into (optional)")
def ingest(github_url, repo_dir):
    """Clone a repo, parse it, and write the graph to Neo4j."""
    driver, workspace_id = get_neo4j_driver()

    # Schema first — always
    apply_schema(driver)

    start = time.time()

    # Clone
    local_path = clone_repo(github_url, repo_dir)

    # Parse
    click.echo(f"\n[PARSE] Walking {local_path}")
    parsed_files = parse_directory(local_path, workspace_id)
    click.echo(f"[PARSE] {len(parsed_files)} Python files parsed")

    total_functions = sum(len(pf.functions) for pf in parsed_files)
    total_classes = sum(len(pf.classes) for pf in parsed_files)
    total_imports = sum(len(pf.imports) for pf in parsed_files)
    click.echo(f"[PARSE] {total_functions} functions | {total_classes} classes | {total_imports} imports")

    # Resolve calls
    click.echo(f"\n[RESOLVE] Building call graph")
    call_edges = resolve_all_calls(parsed_files)

    # Write graph
    click.echo(f"\n[WRITE] Writing to Neo4j (workspace: {workspace_id})")
    write_graph(driver, parsed_files, call_edges, workspace_id)

    elapsed = time.time() - start
    click.echo(f"\n[DONE] Ingestion complete in {elapsed:.1f}s")
    click.echo(f"[INFO] Run query with: python main.py query <file_path>")

    driver.close()


@cli.command()
@click.argument("file_path")
@click.option("--max-hops", default=5, help="Max traversal depth for transitive deps")
def query(file_path, max_hops):
    """Answer: what would break if I deleted this file?"""
    driver, workspace_id = get_neo4j_driver()

    what_breaks_if_deleted(
        driver=driver,
        file_path=file_path,
        workspace_id=workspace_id,
        max_hops=max_hops,
        verbose=True,
    )

    driver.close()


@cli.command()
@click.argument("github_url")
@click.argument("file_to_query")
@click.option("--repo-dir", default=None, help="Local path to clone into (optional)")
def run(github_url, file_to_query, repo_dir):
    """Ingest a repo and immediately query a file. One command, full flow."""
    driver, workspace_id = get_neo4j_driver()

    apply_schema(driver)

    start = time.time()

    local_path = clone_repo(github_url, repo_dir)

    click.echo(f"\n[PARSE] Walking {local_path}")
    parsed_files = parse_directory(local_path, workspace_id)
    click.echo(f"[PARSE] {len(parsed_files)} files | "
               f"{sum(len(pf.functions) for pf in parsed_files)} functions")

    click.echo(f"\n[RESOLVE] Building call graph")
    call_edges = resolve_all_calls(parsed_files)

    click.echo(f"\n[WRITE] Writing to Neo4j")
    write_graph(driver, parsed_files, call_edges, workspace_id)

    elapsed = time.time() - start
    click.echo(f"\n[INGEST] Complete in {elapsed:.1f}s")

    # Query
    what_breaks_if_deleted(
        driver=driver,
        file_path=file_to_query,
        workspace_id=workspace_id,
        verbose=True,
    )

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


if __name__ == "__main__":
    cli()