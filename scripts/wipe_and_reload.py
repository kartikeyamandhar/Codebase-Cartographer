"""
Phase 1 - Wipe and reload script.
Drops all data for a workspace and re-applies schema.
Required from day one per the plan — schema will change across phases.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.schema import get_driver, apply_schema, drop_all_data, verify_connection


def main():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    workspace_id = os.getenv("WORKSPACE_ID", "local_dev")

    if not password:
        print("[ERROR] NEO4J_PASSWORD not set in .env")
        sys.exit(1)

    driver = get_driver(uri, user, password)

    if not verify_connection(driver):
        print("[ERROR] Cannot connect to Neo4j")
        sys.exit(1)

    print(f"[WIPE] Dropping all data for workspace '{workspace_id}'")
    drop_all_data(driver, workspace_id)

    print("[SCHEMA] Re-applying schema")
    apply_schema(driver)

    print("[DONE] Clean slate ready")
    driver.close()


if __name__ == "__main__":
    main()