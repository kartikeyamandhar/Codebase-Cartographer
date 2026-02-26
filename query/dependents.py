"""
Phase 1 - Task 1.4
The one target question: "What would break if I deleted file X?"

Two traversal levels:
1. Direct dependents  — files/functions that directly IMPORT this file
2. Function dependents — functions that CALL functions defined in this file

Results printed to stdout. Evidence shown for manual verification.
"""

from neo4j import GraphDatabase


# ── Cypher queries ────────────────────────────────────────────────────────────

# Direct file-level dependents via IMPORTS edges
DIRECT_IMPORT_DEPENDENTS = """
MATCH (target:File {path: $path, workspace_id: $workspace_id})
MATCH (dependent:File)-[:IMPORTS]->(target)
RETURN DISTINCT
    dependent.path AS dependent_path,
    'IMPORTS' AS relationship,
    null AS via_function
ORDER BY dependent_path
"""

# Function-level dependents: functions that CALL into the target file
FUNCTION_CALL_DEPENDENTS = """
MATCH (target:File {path: $path, workspace_id: $workspace_id})
MATCH (target)-[:CONTAINS]->(target_fn:Function)
MATCH (caller:Function)-[c:CALLS]->(target_fn)
MATCH (caller_file:File)-[:CONTAINS]->(caller)
RETURN DISTINCT
    caller_file.path   AS dependent_path,
    'CALLS'            AS relationship,
    caller.name        AS via_function,
    target_fn.name     AS calls_into,
    c.resolved         AS resolved,
    c.confidence       AS confidence
ORDER BY dependent_path, via_function
"""

# Transitive dependents up to 5 hops (literal — Cypher doesn't accept params here)
TRANSITIVE_DEPENDENTS = """
MATCH (target:File {path: $path, workspace_id: $workspace_id})
MATCH path = (dependent:File)-[:IMPORTS*1..5]->(target)
RETURN DISTINCT
    dependent.path      AS dependent_path,
    length(path)        AS hops,
    'TRANSITIVE_IMPORT' AS relationship
ORDER BY hops, dependent_path
"""


# ── Query runner ──────────────────────────────────────────────────────────────

def what_breaks_if_deleted(
    driver,
    file_path: str,
    workspace_id: str,
    max_hops: int = 5,
    verbose: bool = True,
) -> dict:
    """
    Answer: "What would break if I deleted file X?"

    Returns a dict with:
      - direct_importers: files that directly import this file
      - function_callers: functions that call into this file
      - transitive_importers: files that transitively depend on this file
      - summary: plain text answer
    """
    results = {
        "file_path": file_path,
        "direct_importers": [],
        "function_callers": [],
        "transitive_importers": [],
        "summary": "",
    }

    with driver.session() as session:

        # 1. Direct file importers
        records = session.run(
            DIRECT_IMPORT_DEPENDENTS,
            path=file_path,
            workspace_id=workspace_id,
        )
        results["direct_importers"] = [dict(r) for r in records]

        # 2. Function-level callers
        records = session.run(
            FUNCTION_CALL_DEPENDENTS,
            path=file_path,
            workspace_id=workspace_id,
        )
        results["function_callers"] = [dict(r) for r in records]
        # 3. Transitive importers — deduplicate keeping shortest path per file
        records = session.run(
            TRANSITIVE_DEPENDENTS,
            path=file_path,
            workspace_id=workspace_id,
        )
        transitive_raw = [dict(r) for r in records]

        # Keep only shortest hop count per dependent path
        shortest: dict[str, dict] = {}
        for r in transitive_raw:
            p = r["dependent_path"]
            if p not in shortest or r["hops"] < shortest[p]["hops"]:
                shortest[p] = r

        # Exclude files already in direct_importers
        direct_paths = {r["dependent_path"] for r in results["direct_importers"]}
        results["transitive_importers"] = [
            r for r in shortest.values() if r["dependent_path"] not in direct_paths
        ]

    # ── Build summary ─────────────────────────────────────────────────────────
    results["summary"] = _build_summary(results, file_path)

    if verbose:
        _print_results(results)

    return results


def _build_summary(results: dict, file_path: str) -> str:
    direct = results["direct_importers"]
    callers = results["function_callers"]
    transitive = results["transitive_importers"]

    unique_caller_files = {r["dependent_path"] for r in callers}
    all_affected = {r["dependent_path"] for r in direct} | unique_caller_files | \
                   {r["dependent_path"] for r in transitive}

    if not all_affected:
        return f"Deleting '{file_path}' would not break any other files in this repo."

    parts = []
    if direct:
        parts.append(f"{len(direct)} file(s) directly import it")
    if unique_caller_files:
        parts.append(f"{len(unique_caller_files)} file(s) call functions defined in it")
    if transitive:
        parts.append(f"{len(transitive)} file(s) transitively depend on it")

    return (
        f"Deleting '{file_path}' would affect {len(all_affected)} file(s): "
        + "; ".join(parts) + "."
    )


def _print_results(results: dict):
    file_path = results["file_path"]

    print("\n" + "═" * 70)
    print(f"  IMPACT ANALYSIS: {file_path}")
    print("═" * 70)

    print(f"\n{'─'*70}")
    print("  DIRECT IMPORTERS (files that import this file)")
    print(f"{'─'*70}")
    if results["direct_importers"]:
        for r in results["direct_importers"]:
            print(f"  ● {r['dependent_path']}")
    else:
        print("  (none)")

    print(f"\n{'─'*70}")
    print("  FUNCTION CALLERS (functions that call into this file)")
    print(f"{'─'*70}")
    if results["function_callers"]:
        for r in results["function_callers"]:
            resolved_tag = "[resolved]" if r.get("resolved") else "[unresolved]"
            print(f"  ● {r['dependent_path']} → {r['via_function']}() calls {r['calls_into']}()  {resolved_tag}")
    else:
        print("  (none)")

    print(f"\n{'─'*70}")
    print("  TRANSITIVE DEPENDENTS (indirect imports, up to 5 hops)")
    print(f"{'─'*70}")
    if results["transitive_importers"]:
        for r in results["transitive_importers"]:
            print(f"  ● {r['dependent_path']}  ({r['hops']} hop(s))")
    else:
        print("  (none)")

    print(f"\n{'─'*70}")
    print("  SUMMARY")
    print(f"{'─'*70}")
    print(f"  {results['summary']}")
    print("═" * 70 + "\n")