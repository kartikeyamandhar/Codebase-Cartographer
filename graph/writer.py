"""
Phase 1 - Task 1.3 (part 2)
Graph writer: writes parsed files, functions, imports and call edges to Neo4j.
Uses MERGE to be idempotent — safe to re-run on same data.
Batch writes for performance.
"""

from neo4j import GraphDatabase

from ingestion.parse_python import ParsedFile
from ingestion.call_resolver import CallEdge


BATCH_SIZE = 500


# ── Node writers ──────────────────────────────────────────────────────────────

def write_files(session, parsed_files: list[ParsedFile], workspace_id: str):
    """Write File nodes."""
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
        chunk = batch[i:i + BATCH_SIZE]
        session.run(
            """
            UNWIND $rows AS row
            MERGE (f:File {path: row.path})
            SET f.language      = row.language,
                f.line_count    = row.line_count,
                f.content_hash  = row.content_hash,
                f.workspace_id  = row.workspace_id
            """,
            rows=chunk,
        )

    print(f"[WRITER] {len(batch)} File nodes written")


def write_functions(session, parsed_files: list[ParsedFile], workspace_id: str):
    """Write Function nodes and CONTAINS edges from File."""
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
        chunk = fn_batch[i:i + BATCH_SIZE]
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
            rows=chunk,
        )

    for i in range(0, len(contains_batch), BATCH_SIZE):
        chunk = contains_batch[i:i + BATCH_SIZE]
        session.run(
            """
            UNWIND $rows AS row
            MATCH (f:File {path: row.file_path})
            MATCH (fn:Function {id: row.function_id})
            MERGE (f)-[r:CONTAINS]->(fn)
            SET r.order = row.order
            """,
            rows=chunk,
        )

    print(f"[WRITER] {len(fn_batch)} Function nodes + CONTAINS edges written")


def write_imports(session, parsed_files: list[ParsedFile], workspace_id: str):
    """
    Write IMPORTS edges between File nodes.
    Only writes edges where the target file exists in the graph
    (i.e. is part of this repo). External library imports are skipped
    since they have no File node — but logged.
    """
    edges = []
    skipped = 0

    for pf in parsed_files:
        for imp in pf.imports:
            if not imp.module:
                continue
            # Convert module path to file path (best-effort)
            # e.g. "flask.app" -> look for flask/app.py in repo
            target_candidates = _module_to_paths(imp.module)
            edges.append({
                "source_path": pf.path,
                "module": imp.module,
                "candidates": target_candidates,
                "alias": imp.alias or "",
            })

    # Write edges only where target File node exists
    for i in range(0, len(edges), BATCH_SIZE):
        chunk = edges[i:i + BATCH_SIZE]
        result = session.run(
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
            rows=chunk,
        )
        record = result.single()
        written = record["written"] if record else 0

    print(f"[WRITER] IMPORTS edges written (intra-repo only)")


def write_calls(session, call_edges: list[CallEdge], workspace_id: str):
    """
    Write CALLS edges between Function nodes.
    Both resolved and unresolved edges are written.
    Unresolved edges have resolved=false and a reason string.
    """
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
            # Unresolved — still write the edge, tagged
            unresolved_batch.append({
                "caller_id": edge.caller_id,
                "callee_name": edge.callee_name,
                "resolved": False,
                "confidence": edge.confidence,
                "reason": edge.reason,
                "call_site_line": edge.call_site_line,
            })

    # Write resolved edges (both nodes exist)
    for i in range(0, len(resolved_batch), BATCH_SIZE):
        chunk = resolved_batch[i:i + BATCH_SIZE]
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
            rows=chunk,
        )

    # Write unresolved edges — attach to caller only, store callee_name as property
    # These edges point to a sentinel :UnresolvedCall node per name
    for i in range(0, len(unresolved_batch), BATCH_SIZE):
        chunk = unresolved_batch[i:i + BATCH_SIZE]
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
            rows=chunk,
            wid=workspace_id,
        )

    total = len(resolved_batch) + len(unresolved_batch)
    print(f"[WRITER] {total} CALLS edges written "
          f"({len(resolved_batch)} resolved, {len(unresolved_batch)} unresolved)")


# ── Helper ────────────────────────────────────────────────────────────────────

def _module_to_paths(module: str) -> list[str]:
    """
    Convert a Python module string to candidate file path suffixes.
    e.g. "flask.app" -> ["flask/app.py", "flask/app/__init__.py"]
    """
    base = module.replace(".", "/")
    return [
        f"{base}.py",
        f"{base}/__init__.py",
    ]


# ── Main entry point ──────────────────────────────────────────────────────────

def write_graph(
    driver,
    parsed_files: list[ParsedFile],
    call_edges: list[CallEdge],
    workspace_id: str,
):
    """
    Write the full Phase 1 graph to Neo4j.
    Order: Files → Functions → CONTAINS → IMPORTS → CALLS
    """
    with driver.session() as session:
        write_files(session, parsed_files, workspace_id)
        write_functions(session, parsed_files, workspace_id)
        write_imports(session, parsed_files, workspace_id)
        write_calls(session, call_edges, workspace_id)

    print(f"[WRITER] Graph write complete for workspace '{workspace_id}'")