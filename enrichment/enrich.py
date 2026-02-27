"""
Phase 5 — Semantic Enrichment
Reads Function nodes from Neo4j, sends batches to GPT-4o,
writes domain_tag + semantic_role + complexity_score back to each node.

Usage:
  python main.py enrich --workspace-id local_dev
  python main.py enrich --workspace-id local_dev --force
  python main.py enrich --workspace-id local_dev --dry-run
"""

import json
import os
import time

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from graph.schema import get_driver

DOMAIN_VOCAB = [
    "auth", "payments", "database", "api", "config",
    "utils", "testing", "infra", "ui", "logging"
]

BATCH_SIZE = 20

SYSTEM_PROMPT = """You are a code analyst. For each function provided, return ONLY a JSON array.
Each element must match this schema exactly:
{"node_id": string, "semantic_role": string, "domain_tag": string, "complexity_score": integer}

Rules:
- domain_tag MUST be one of: auth, payments, database, api, config, utils, testing, infra, ui, logging
- semantic_role: short phrase describing what the function does (e.g. "validates user credentials")
- complexity_score: integer 1-10 (1=trivial, 10=very complex)
- Return ONLY the JSON array. No markdown, no explanation, no backticks."""


def get_neo4j():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    return get_driver(uri, user, password)


def get_openai():
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def fetch_unenriched_functions(driver, workspace_id: str, force: bool = False) -> list:
    if force:
        query = """
        MATCH (fn:Function {workspace_id: $wid})
        RETURN fn.id AS id, fn.name AS name, fn.file_path AS file_path,
               fn.start_line AS start_line, fn.end_line AS end_line
        ORDER BY fn.file_path, fn.start_line
        """
    else:
        query = """
        MATCH (fn:Function {workspace_id: $wid})
        WHERE fn.domain_tag IS NULL OR fn.domain_tag = ''
        RETURN fn.id AS id, fn.name AS name, fn.file_path AS file_path,
               fn.start_line AS start_line, fn.end_line AS end_line
        ORDER BY fn.file_path, fn.start_line
        """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, wid=workspace_id)]


def read_function_code(file_path: str, start_line: int, end_line: int) -> str:
    candidates = [
        file_path,
        os.path.join(os.getcwd(), file_path),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
                if start_line and end_line:
                    snippet = lines[max(0, start_line - 1):min(end_line, len(lines))]
                    return ''.join(snippet[:80])
            except Exception:
                pass
    return ""


def build_batch_prompt(functions: list) -> str:
    items = []
    for fn in functions:
        code = read_function_code(fn['file_path'], fn.get('start_line'), fn.get('end_line'))
        if not code:
            code = f"# function: {fn['name']} in {fn['file_path']}"
        items.append(
            f'node_id: {fn["id"]}\nname: {fn["name"]}\nfile: {fn["file_path"]}\n```\n{code[:500]}\n```'
        )
    return "Analyze these functions:\n\n" + "\n\n---\n\n".join(items)


def parse_batch_response(text: str, debug: bool = False) -> list:
    original = text
    text = text.strip()
    # Strip any markdown fences
    if '```json' in text:
        text = text.split('```json')[1].split('```')[0].strip()
    elif text.startswith('```'):
        lines = text.split('\n')
        text = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])
    # Find JSON array if buried in text
    if not text.startswith('['):
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1:
            text = text[start:end+1]
    if debug:
        print(f"\n[DEBUG] Raw response (first 300 chars):\n{original[:300]}")
        print(f"[DEBUG] Cleaned text (first 300 chars):\n{text[:300]}")
    try:
        results = json.loads(text)
        if not isinstance(results, list):
            return []
        valid = []
        for r in results:
            if not isinstance(r, dict) or 'node_id' not in r:
                continue
            domain = r.get('domain_tag', 'utils')
            if domain not in DOMAIN_VOCAB:
                domain = 'utils'
            valid.append({
                'node_id': r['node_id'],
                'semantic_role': str(r.get('semantic_role', ''))[:200],
                'domain_tag': domain,
                'complexity_score': max(1, min(10, int(r.get('complexity_score', 5)))),
            })
        return valid
    except (json.JSONDecodeError, ValueError):
        return []


def write_enrichments(driver, enrichments: list, workspace_id: str):
    query = """
    MATCH (fn:Function {id: $id, workspace_id: $wid})
    SET fn.semantic_role = $semantic_role,
        fn.domain_tag = $domain_tag,
        fn.complexity_score = $complexity_score,
        fn.enriched_at = datetime()
    """
    with driver.session() as session:
        for e in enrichments:
            session.run(query,
                id=e['node_id'],
                wid=workspace_id,
                semantic_role=e['semantic_role'],
                domain_tag=e['domain_tag'],
                complexity_score=e['complexity_score'],
            )


def enrich_workspace(workspace_id: str, force: bool = False, dry_run: bool = False):
    driver = get_neo4j()
    client = get_openai()

    print(f"\n{'─'*60}")
    print(f"  Phase 5 — Semantic Enrichment")
    print(f"  Workspace: {workspace_id}  |  Force: {force}  |  Dry run: {dry_run}")
    print(f"{'─'*60}\n")

    functions = fetch_unenriched_functions(driver, workspace_id, force)
    total = len(functions)

    if total == 0:
        print("  All functions already enriched. Use --force to re-enrich.")
        driver.close()
        return

    if total > 5000:
        print(f"  Capping at 5000 functions (plan limit)")
        functions = functions[:5000]
        total = 5000

    n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    est_cost = total * (800 * 5 + 200 * 15) / 1_000_000

    print(f"  Functions to enrich: {total}")
    print(f"  Batches: {n_batches} (size {BATCH_SIZE})")
    print(f"  Estimated cost: ${est_cost:.2f}\n")

    if dry_run:
        print("  [DRY RUN] No API calls made.")
        driver.close()
        return

    enriched = 0
    failed = 0
    total_cost = 0.0

    for i in range(0, len(functions), BATCH_SIZE):
        batch = functions[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"  Batch {batch_num}/{n_batches} ({len(batch)} functions)... ", end='', flush=True)

        prompt = build_batch_prompt(batch)

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=4000,
            )

            usage = response.usage
            batch_cost = (usage.prompt_tokens * 5 + usage.completion_tokens * 15) / 1_000_000
            total_cost += batch_cost

            raw = response.choices[0].message.content
            results = parse_batch_response(raw)

            if results:
                write_enrichments(driver, results, workspace_id)
                enriched += len(results)
                print(f"✓ {len(results)} enriched | ${batch_cost:.4f}")
            else:
                failed += len(batch)
                parse_batch_response(raw, debug=True)
                print(f"✗ parse failed")

        except Exception as e:
            failed += len(batch)
            print(f"✗ {e}")

        if batch_num < n_batches:
            time.sleep(0.3)

    driver.close()

    print(f"\n{'─'*60}")
    print(f"  Enriched: {enriched}/{total}")
    print(f"  Failed:   {failed}")
    print(f"  Total cost: ${total_cost:.4f}")
    print(f"{'─'*60}\n")