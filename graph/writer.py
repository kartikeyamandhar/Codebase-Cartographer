"""
Graph writer: writes all nodes and edges to Neo4j.
Phase 1: File, Function, CONTAINS, CALLS, IMPORTS
Phase 2: Class, Author, Commit, MODIFIED_BY, AUTHORED_BY, OWNS
Uses MERGE for idempotency. Batch writes for performance.
"""

from neo4j import GraphDatabase

from ingestion.parse_python import ParsedFile
from ingestion.call_resolver import CallEdge
from ingestion.git_parser import GitGraph, build_ownership_map


BATCH_SIZE = 500


# ── Phase 1 writers ───────────────────────────────────────────────────────────

def write_files(session, parsed_files: list[ParsedFile], workspace_id: str):
    batch = [
        {
            "path": pf.path,
            "language": pf.language,
            "line_count": pf.line_count,
            "content_hash": pf.content_hash,
            "workspace_id": workspace_id,
        }
        for pf in parsed_files
    ]

    for i in range(0, len(batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MERGE (f:File {path: row.path})
            SET f.language      = row.language,
                f.line_count    = row.line_count,
                f.content_hash  = row.content_hash,
                f.workspace_id  = row.workspace_id
            """,
            rows=batch[i:i + BATCH_SIZE],
        )
    print(f"[WRITER] {len(batch)} File nodes written")


def write_functions(session, parsed_files: list[ParsedFile], workspace_id: str):
    fn_batch = []
    contains_batch = []

    for pf in parsed_files:
        for fn in pf.functions:
            node_id = f"{pf.path}::{fn.name}"
            fn_batch.append({
                "id": node_id,
                "name": fn.name,
                "file_path": pf.path,
                "start_line": fn.start_line,
                "end_line": fn.end_line,
                "class_name": fn.class_name,
                "workspace_id": workspace_id,
            })
            contains_batch.append({
                "file_path": pf.path,
                "function_id": node_id,
                "order": fn.start_line,
            })

    for i in range(0, len(fn_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MERGE (fn:Function {id: row.id})
            SET fn.name         = row.name,
                fn.file_path    = row.file_path,
                fn.start_line   = row.start_line,
                fn.end_line     = row.end_line,
                fn.class_name   = row.class_name,
                fn.workspace_id = row.workspace_id
            """,
            rows=fn_batch[i:i + BATCH_SIZE],
        )

    for i in range(0, len(contains_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (f:File {path: row.file_path})
            MATCH (fn:Function {id: row.function_id})
            MERGE (f)-[r:CONTAINS]->(fn)
            SET r.order = row.order
            """,
            rows=contains_batch[i:i + BATCH_SIZE],
        )

    print(f"[WRITER] {len(fn_batch)} Function nodes + CONTAINS edges written")


def write_classes(session, parsed_files: list[ParsedFile], workspace_id: str):
    """Phase 2 — write Class nodes and CONTAINS edges from File."""
    class_batch = []
    contains_batch = []

    for pf in parsed_files:
        for cls in pf.classes:
            node_id = f"{pf.path}::{cls.name}"
            class_batch.append({
                "id": node_id,
                "name": cls.name,
                "file_path": pf.path,
                "base_classes": cls.base_classes,
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                "workspace_id": workspace_id,
            })
            contains_batch.append({
                "file_path": pf.path,
                "class_id": node_id,
            })

    for i in range(0, len(class_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MERGE (c:Class {id: row.id})
            SET c.name         = row.name,
                c.file_path    = row.file_path,
                c.base_classes = row.base_classes,
                c.start_line   = row.start_line,
                c.end_line     = row.end_line,
                c.workspace_id = row.workspace_id
            """,
            rows=class_batch[i:i + BATCH_SIZE],
        )

    for i in range(0, len(contains_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (f:File {path: row.file_path})
            MATCH (c:Class {id: row.class_id})
            MERGE (f)-[:CONTAINS]->(c)
            """,
            rows=contains_batch[i:i + BATCH_SIZE],
        )

    print(f"[WRITER] {len(class_batch)} Class nodes written")


def write_imports(session, parsed_files: list[ParsedFile], workspace_id: str):
    edges = []

    for pf in parsed_files:
        for imp in pf.imports:
            if not imp.module:
                continue
            target_candidates = _module_to_paths(imp.module)
            edges.append({
                "source_path": pf.path,
                "module": imp.module,
                "candidates": target_candidates,
                "alias": imp.alias or "",
            })

    for i in range(0, len(edges), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (src:File {path: row.source_path})
            MATCH (tgt:File)
            WHERE any(c IN row.candidates WHERE tgt.path ENDS WITH c)
            MERGE (src)-[r:IMPORTS]->(tgt)
            SET r.module = row.module,
                r.alias  = row.alias
            RETURN count(r) AS written
            """,
            rows=edges[i:i + BATCH_SIZE],
        )

    print(f"[WRITER] IMPORTS edges written (intra-repo only)")


def write_calls(session, call_edges: list[CallEdge], workspace_id: str):
    resolved_batch = []
    unresolved_batch = []

    for edge in call_edges:
        if edge.resolved and edge.callee_id:
            resolved_batch.append({
                "caller_id": edge.caller_id,
                "callee_id": edge.callee_id,
                "resolved": True,
                "confidence": edge.confidence,
                "reason": edge.reason,
                "call_site_line": edge.call_site_line,
            })
        else:
            unresolved_batch.append({
                "caller_id": edge.caller_id,
                "callee_name": edge.callee_name,
                "resolved": False,
                "confidence": edge.confidence,
                "reason": edge.reason,
                "call_site_line": edge.call_site_line,
            })

    for i in range(0, len(resolved_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (caller:Function {id: row.caller_id})
            MATCH (callee:Function {id: row.callee_id})
            MERGE (caller)-[r:CALLS]->(callee)
            SET r.resolved       = row.resolved,
                r.confidence     = row.confidence,
                r.reason         = row.reason,
                r.call_site_line = row.call_site_line
            """,
            rows=resolved_batch[i:i + BATCH_SIZE],
        )

    for i in range(0, len(unresolved_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (caller:Function {id: row.caller_id})
            MERGE (phantom:UnresolvedCall {name: row.callee_name, workspace_id: $wid})
            MERGE (caller)-[r:CALLS]->(phantom)
            SET r.resolved       = row.resolved,
                r.confidence     = row.confidence,
                r.reason         = row.reason,
                r.call_site_line = row.call_site_line
            """,
            rows=unresolved_batch[i:i + BATCH_SIZE],
            wid=workspace_id,
        )

    total = len(resolved_batch) + len(unresolved_batch)
    print(f"[WRITER] {total} CALLS edges written "
          f"({len(resolved_batch)} resolved, {len(unresolved_batch)} unresolved)")


# ── Phase 2 writers ───────────────────────────────────────────────────────────

def write_git_graph(session, git_graph: GitGraph, workspace_id: str):
    """Write Author and Commit nodes + AUTHORED_BY edges."""

    # Authors
    author_batch = [
        {
            "email": a.email,
            "name": a.name,
            "workspace_id": workspace_id,
        }
        for a in git_graph.authors
    ]

    for i in range(0, len(author_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MERGE (a:Author {email: row.email})
            SET a.name         = row.name,
                a.workspace_id = row.workspace_id
            """,
            rows=author_batch[i:i + BATCH_SIZE],
        )

    print(f"[WRITER] {len(author_batch)} Author nodes written")

    # Commits + AUTHORED_BY edges
    commit_batch = [
        {
            "hash": c.hash,
            "message": c.message,
            "timestamp": c.timestamp,
            "branch": c.branch,
            "author_email": c.author_email,
            "workspace_id": workspace_id,
        }
        for c in git_graph.commits
    ]

    for i in range(0, len(commit_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MERGE (c:Commit {hash: row.hash})
            SET c.message      = row.message,
                c.timestamp    = row.timestamp,
                c.branch       = row.branch,
                c.workspace_id = row.workspace_id
            WITH c, row
            MATCH (a:Author {email: row.author_email})
            MERGE (c)-[:AUTHORED_BY]->(a)
            """,
            rows=commit_batch[i:i + BATCH_SIZE],
        )

    print(f"[WRITER] {len(commit_batch)} Commit nodes + AUTHORED_BY edges written")

    # MODIFIED_BY edges: File -> Commit
    modified_batch = []
    for commit in git_graph.commits:
        for file_change in commit.files_changed:
            modified_batch.append({
                "file_path": file_change["path"],
                "commit_hash": commit.hash,
                "lines_added": file_change["lines_added"],
                "lines_removed": file_change["lines_removed"],
            })

    written = 0
    for i in range(0, len(modified_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (f:File {path: row.file_path})
            MATCH (c:Commit {hash: row.commit_hash})
            MERGE (f)-[r:MODIFIED_BY]->(c)
            SET r.lines_added   = row.lines_added,
                r.lines_removed = row.lines_removed
            """,
            rows=modified_batch[i:i + BATCH_SIZE],
        )
        written += len(modified_batch[i:i + BATCH_SIZE])

    print(f"[WRITER] {len(modified_batch)} MODIFIED_BY edges attempted")


def write_ownership(session, git_graph: GitGraph, workspace_id: str):
    """Write OWNS edges: Author -> File with commit_count and last_touch."""
    ownership_map = build_ownership_map(git_graph)

    owns_batch = []
    for file_path, authors in ownership_map.items():
        for email, stats in authors.items():
            owns_batch.append({
                "author_email": email,
                "file_path": file_path,
                "commit_count": stats["commit_count"],
                "last_touch": stats["last_touch"],
            })

    for i in range(0, len(owns_batch), BATCH_SIZE):
        session.run(
            """
            UNWIND $rows AS row
            MATCH (a:Author {email: row.author_email})
            MATCH (f:File {path: row.file_path})
            MERGE (a)-[r:OWNS]->(f)
            SET r.commit_count = row.commit_count,
                r.last_touch   = row.last_touch
            """,
            rows=owns_batch[i:i + BATCH_SIZE],
        )

    print(f"[WRITER] {len(owns_batch)} OWNS edges written")


# ── Helper ────────────────────────────────────────────────────────────────────

def _module_to_paths(module: str) -> list[str]:
    base = module.replace(".", "/")
    return [
        f"{base}.py",
        f"{base}/__init__.py",
        f"{base}.ts",
        f"{base}.tsx",
        f"{base}.js",
        f"{base}/index.ts",
        f"{base}/index.js",
    ]


# ── Main entry point ──────────────────────────────────────────────────────────

def write_graph(
    driver,
    parsed_files: list[ParsedFile],
    call_edges: list[CallEdge],
    workspace_id: str,
    git_graph: GitGraph = None,
):
    """
    Write the full graph to Neo4j.
    Order: Files → Classes → Functions → CONTAINS → IMPORTS → CALLS → Git
    """
    with driver.session() as session:
        write_files(session, parsed_files, workspace_id)
        write_classes(session, parsed_files, workspace_id)
        write_functions(session, parsed_files, workspace_id)
        write_imports(session, parsed_files, workspace_id)
        write_calls(session, call_edges, workspace_id)

        if git_graph and (git_graph.authors or git_graph.commits):
            write_git_graph(session, git_graph, workspace_id)
            write_ownership(session, git_graph, workspace_id)

    print(f"[WRITER] Graph write complete for workspace '{workspace_id}'")