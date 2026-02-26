"""
Phase 1 - Task 1.3 (part 1)
Schema definition: constraints and indexes.
Always run schema BEFORE writing any nodes.
Schema is versioned — wipe_and_reload.py resets and re-applies.
"""

from neo4j import GraphDatabase


SCHEMA_VERSION = "1.0.0"

# Phase 1 schema — File, Function nodes + CONTAINS, CALLS, IMPORTS edges
CONSTRAINTS = [
    # Uniqueness constraints (also create implicit indexes)
    "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
    "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE",
]

INDEXES = [
    # Workspace scoping — every query filters by workspace_id
    "CREATE INDEX file_workspace IF NOT EXISTS FOR (f:File) ON (f.workspace_id)",
    "CREATE INDEX function_workspace IF NOT EXISTS FOR (fn:Function) ON (fn.workspace_id)",
    # Call resolution lookups
    "CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)",
    "CREATE INDEX function_file IF NOT EXISTS FOR (fn:Function) ON (fn.file_path)",
]


def apply_schema(driver):
    """
    Apply all constraints and indexes.
    Safe to run multiple times — IF NOT EXISTS prevents errors on re-run.
    """
    with driver.session() as session:
        for statement in CONSTRAINTS:
            session.run(statement)

        for statement in INDEXES:
            session.run(statement)

    print(f"[SCHEMA] v{SCHEMA_VERSION} applied — {len(CONSTRAINTS)} constraints, {len(INDEXES)} indexes")


def drop_all_data(driver, workspace_id: str):
    """
    Wipe all nodes scoped to a workspace_id.
    Used by wipe_and_reload.py — does NOT drop schema/indexes.
    """
    with driver.session() as session:
        result = session.run(
            "MATCH (n {workspace_id: $wid}) DETACH DELETE n RETURN count(n) as deleted",
            wid=workspace_id,
        )
        record = result.single()
        deleted = record["deleted"] if record else 0
    print(f"[SCHEMA] Wiped {deleted} nodes for workspace '{workspace_id}'")


def verify_connection(driver):
    """Smoke test — verify Neo4j is reachable."""
    with driver.session() as session:
        result = session.run("RETURN 1 AS ok")
        record = result.single()
        if record and record["ok"] == 1:
            print("[NEO4J] Connection verified")
            return True
    return False


def get_driver(uri: str, user: str, password: str):
    driver = GraphDatabase.driver(uri, auth=(user, password))
    return driver