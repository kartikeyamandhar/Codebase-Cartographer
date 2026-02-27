"""
Phase 3 - Task 3.2
Orchestrator: FastAPI + GPT-4o tool calling.
Fix: inject workspace_id into every tool call automatically.
"""

import json
import os
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

from graph.schema import get_driver, verify_connection
from chat.tools import TOOL_DEFINITIONS, dispatch_tool, get_node_detail, read_file
from chat.schema_prompt import SYSTEM_PROMPT

app = FastAPI(title="Codebase Cartographer", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_neo4j():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    return get_driver(uri, user, password)


def get_openai():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in .env")
    return OpenAI(api_key=api_key)


class ChatRequest(BaseModel):
    message: str
    workspace_id: str = "local_dev"
    context_node_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    evidence: list
    cypher_used: str
    tools_called: list[str]
    latency_ms: int


def inject_workspace_id(tool_args: dict, workspace_id: str) -> dict:
    """
    Force workspace_id into every tool call and into Cypher params.
    GPT-4o frequently forgets to pass it — we never rely on GPT-4o for this.
    """
    tool_args["workspace_id"] = workspace_id

    # Also inject into nested params dict for query_graph calls
    if "params" in tool_args:
        if not isinstance(tool_args["params"], dict):
            tool_args["params"] = {}
        tool_args["params"]["workspace_id"] = workspace_id
    
    return tool_args


def run_orchestrator(message: str, workspace_id: str, context_node_id: Optional[str] = None) -> dict:
    openai_client = get_openai()
    neo4j_driver = get_neo4j()
    start = time.time()

    user_message = message
    if context_node_id:
        user_message = f"[Context node: {context_node_id}]\n{message}"

    # Inject workspace_id directly into system prompt so GPT-4o always knows it
    system = SYSTEM_PROMPT + f"\n\n## Current Session\nworkspace_id: {workspace_id}\nAlways use this exact workspace_id value in every query and tool call. Never use a placeholder."

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message}
    ]

    tools_called = []
    evidence = []
    cypher_used = ""
    answer = "No answer generated."

    MAX_TOOL_ROUNDS = 5
    for _ in range(MAX_TOOL_ROUNDS):
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=0,
        )

        message_obj = response.choices[0].message

        if not message_obj.tool_calls:
            answer = message_obj.content or "No answer generated."
            break

        messages.append(message_obj)

        for tool_call in message_obj.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            # Always inject workspace_id — never trust GPT-4o to pass it
            tool_args = inject_workspace_id(tool_args, workspace_id)

            tools_called.append(tool_name)
            tool_result = dispatch_tool(tool_name, tool_args, neo4j_driver)

            if "cypher_used" in tool_result and tool_result["cypher_used"]:
                cypher_used = tool_result["cypher_used"]

            if tool_name == "query_graph":
                rows = tool_result.get("rows", [])
                evidence.append({
                    "tool": "query_graph",
                    "cypher": tool_result.get("cypher_used", ""),
                    "row_count": len(rows),
                    "sample": rows[:5]
                })
            elif tool_name in ("find_dependents", "find_owners"):
                evidence.append({
                    "tool": tool_name,
                    "args": {k: v for k, v in tool_args.items() if k != "workspace_id"},
                    "result": tool_result
                })

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result, default=str)
            })
    else:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0,
        )
        answer = response.choices[0].message.content or "Could not generate answer."

    neo4j_driver.close()

    return {
        "answer": answer,
        "evidence": evidence,
        "cypher_used": cypher_used,
        "tools_called": tools_called,
        "latency_ms": int((time.time() - start) * 1000),
    }


@app.get("/health")
def health():
    try:
        driver = get_neo4j()
        ok = verify_connection(driver)
        driver.close()
        return {"status": "ok", "neo4j": ok}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        result = run_orchestrator(
            message=request.message,
            workspace_id=request.workspace_id,
            context_node_id=request.context_node_id,
        )
        return ChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/schema")
def schema():
    return {"schema": SYSTEM_PROMPT}


# ── Graph data endpoint for frontend ─────────────────────────────────────────

@app.get("/graph/{workspace_id}")
def get_graph(workspace_id: str, limit: int = 150):
    """
    Return Cytoscape.js-compatible graph JSON.
    Default: top-150 nodes by degree to avoid browser freeze.
    """
    driver = get_neo4j()
    try:
        with driver.session() as session:
            # Get top nodes by degree
            node_result = session.run("""
                MATCH (n {workspace_id: $wid})
                WHERE n:File OR n:Function OR n:Class OR n:Author
                WITH n,
                     size([(n)-[]-() | 1]) AS degree
                ORDER BY degree DESC
                LIMIT $limit
                RETURN
                    COALESCE(n.path, n.id, n.email, n.name) AS node_id,
                    labels(n)[0] AS type,
                    COALESCE(
                        n.path, n.name, n.email, n.id
                    ) AS label,
                    n.domain_tag AS domain_tag,
                    degree
            """, wid=workspace_id, limit=limit)

            nodes = []
            node_ids = set()
            for r in node_result:
                nid = r["node_id"]
                if nid and nid not in node_ids:
                    node_ids.add(nid)
                    lbl = r["label"] or nid
                    # Shorten label to last path component
                    short_label = lbl.split('/')[-1] if '/' in lbl else lbl
                    nodes.append({
                        "data": {
                            "id": nid,
                            "label": short_label,
                            "type": r["type"],
                            "domain_tag": r["domain_tag"] or "",
                            "degree": r["degree"] or 1,
                        }
                    })

            # Get edges between visible nodes only
            edge_result = session.run("""
                MATCH (n {workspace_id: $wid})-[r]->(m {workspace_id: $wid})
                WHERE COALESCE(n.path, n.id, n.email, n.name) IN $node_ids
                  AND COALESCE(m.path, m.id, m.email, m.name) IN $node_ids
                  AND type(r) IN ['IMPORTS', 'CALLS', 'OWNS']
                RETURN
                    COALESCE(n.path, n.id, n.email, n.name) AS source,
                    COALESCE(m.path, m.id, m.email, m.name) AS target,
                    type(r) AS rel_type,
                    r.resolved AS resolved
                LIMIT 800
            """, wid=workspace_id, node_ids=list(node_ids))

            edges = []
            seen_edges = set()
            for i, r in enumerate(edge_result):
                src, tgt = r["source"], r["target"]
                if not src or not tgt:
                    continue
                key = f"{src}→{tgt}→{r['rel_type']}"
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append({
                    "data": {
                        "id": f"e{i}",
                        "source": src,
                        "target": tgt,
                        "type": r["rel_type"],
                        "resolved": r["resolved"],
                    }
                })

        return {"nodes": nodes, "edges": edges, "workspace_id": workspace_id}
    finally:
        driver.close()


@app.get("/node/{node_id:path}")
def get_node(node_id: str, workspace_id: str = "local_dev", node_type: str = "File"):
    """Get full details for a single node."""
    driver = get_neo4j()
    try:
        result = get_node_detail(node_id, node_type, workspace_id, driver)
        return result
    finally:
        driver.close()


@app.get("/workspaces")
def list_workspaces():
    """Return all workspace_ids that have data in the graph."""
    driver = get_neo4j()
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (n) WHERE n.workspace_id IS NOT NULL "
                "RETURN DISTINCT n.workspace_id AS wid, "
                "count(n) AS node_count ORDER BY node_count DESC"
            )
            workspaces = [
                {"workspace_id": r["wid"], "node_count": r["node_count"]}
                for r in result
            ]
        return {"workspaces": workspaces}
    finally:
        driver.close()