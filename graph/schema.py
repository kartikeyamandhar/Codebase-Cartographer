"""
Schema definition: constraints and indexes.
Always run schema BEFORE writing any nodes.
Schema is versioned — wipe_and_reload.py resets and re-applies.

Phase 1: File, Function nodes + CONTAINS, CALLS, IMPORTS edges
Phase 2: Class, Author, Commit nodes + MODIFIED_BY, AUTHORED_BY, OWNS edges
"""

from neo4j import GraphDatabase


SCHEMA_VERSION = "2.0.0"

CONSTRAINTS = [
    # Phase 1
    "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
    "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE",
    # Phase 2
    "CREATE CONSTRAINT class_id IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT commit_hash IF NOT EXISTS FOR (c:Commit) REQUIRE c.hash IS UNIQUE",
    "CREATE CONSTRAINT author_email IF NOT EXISTS FOR (a:Author) REQUIRE a.email IS UNIQUE",
]

INDEXES = [
    # Phase 1 — workspace scoping and call resolution
    "CREATE INDEX file_workspace IF NOT EXISTS FOR (f:File) ON (f.workspace_id)",
    "CREATE INDEX function_workspace IF NOT EXISTS FOR (fn:Function) ON (fn.workspace_id)",
    "CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)",
    "CREATE INDEX function_file IF NOT EXISTS FOR (fn:Function) ON (fn.file_path)",
    # Phase 2
    "CREATE INDEX class_workspace IF NOT EXISTS FOR (c:Class) ON (c.workspace_id)",
    "CREATE INDEX commit_workspace IF NOT EXISTS FOR (c:Commit) ON (c.workspace_id)",
    "CREATE INDEX commit_timestamp IF NOT EXISTS FOR (c:Commit) ON (c.timestamp)",
    "CREATE INDEX author_workspace IF NOT EXISTS FOR (a:Author) ON (a.workspace_id)",
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