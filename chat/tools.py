"""
Phase 3 - Task 3.1
MCP Tools: structured tool definitions for GPT-4o function calling.
Each tool maps to a graph operation.
"""

import os
from neo4j import GraphDatabase
from graph.schema import get_driver


def get_driver_from_env():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    return get_driver(uri, user, password)


# ── Tool definitions for GPT-4o ───────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_graph",
            "description": (
                "Execute a Cypher query against the Neo4j codebase graph. "
                "Use this for any structural question about files, functions, imports, calls, authors, commits. "
                "Always scope queries with workspace_id parameter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cypher": {
                        "type": "string",
                        "description": "The Cypher query to execute. Use $workspace_id as parameter."
                    },
                    "params": {
                        "type": "object",
                        "description": "Query parameters. Always include workspace_id.",
                        "additionalProperties": True
                    }
                },
                "required": ["cypher", "params"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_dependents",
            "description": (
                "Find all files and functions that depend on a given file. "
                "Use this for 'what breaks if I delete X' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The file path to find dependents for."
                    },
                    "workspace_id": {"type": "string"}
                },
                "required": ["file_path", "workspace_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_owners",
            "description": (
                "Find the authors who own a file, ranked by commit count. "
                "Use for 'who owns X' or 'who wrote X' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The file path to find owners for."
                    },
                    "workspace_id": {"type": "string"}
                },
                "required": ["file_path", "workspace_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_detail",
            "description": (
                "Get full details of a specific File or Function node by path or id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "File path or Function id (file_path::function_name)"
                    },
                    "node_type": {
                        "type": "string",
                        "enum": ["File", "Function", "Author", "Class"],
                        "description": "Type of node to look up"
                    },
                    "workspace_id": {"type": "string"}
                },
                "required": ["node_id", "node_type", "workspace_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_subgraph",
            "description": (
                "Summarize a list of nodes and edges in plain English. "
                "Use this to explain what a subgraph means after querying it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of node dicts"
                    },
                    "edges": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of edge dicts"
                    },
                    "question": {
                        "type": "string",
                        "description": "The original question being answered"
                    }
                },
                "required": ["nodes", "question"]
            }
        }
    }
]


# ── Tool implementations ──────────────────────────────────────────────────────

def query_graph(cypher: str, params: dict, driver) -> dict:
    """Execute a Cypher query. Returns rows as list of dicts."""
    try:
        with driver.session() as session:
            result = session.run(cypher, **params)
            rows = [dict(r) for r in result]
            return {
                "success": True,
                "rows": rows,
                "count": len(rows),
                "cypher_used": cypher
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "cypher_used": cypher,
            "rows": []
        }


def find_dependents(file_path: str, workspace_id: str, driver) -> dict:
    """Find all dependents of a file."""
    direct_query = """
    MATCH (target:File {path: $path, workspace_id: $wid})
    MATCH (dependent:File)-[:IMPORTS]->(target)
    RETURN dependent.path AS path, 'IMPORTS' AS relationship
    ORDER BY path
    """

    caller_query = """
    MATCH (target:File {path: $path, workspace_id: $wid})
    MATCH (target)-[:CONTAINS]->(fn:Function)
    MATCH (caller:Function)-[c:CALLS]->(fn)
    WHERE c.resolved = true
    MATCH (caller_file:File)-[:CONTAINS]->(caller)
    RETURN DISTINCT caller_file.path AS path, 
           caller.name AS caller_function,
           fn.name AS calls_into,
           'CALLS' AS relationship
    ORDER BY path
    """

    with driver.session() as session:
        direct = [dict(r) for r in session.run(direct_query, path=file_path, wid=workspace_id)]
        callers = [dict(r) for r in session.run(caller_query, path=file_path, wid=workspace_id)]

    return {
        "file_path": file_path,
        "direct_importers": direct,
        "function_callers": callers,
        "total_affected": len({r["path"] for r in direct + callers}),
        "cypher_used": direct_query
    }


def find_owners(file_path: str, workspace_id: str, driver) -> dict:
    """Find owners of a file by commit count."""
    query = """
    MATCH (a:Author)-[r:OWNS]->(f:File {path: $path, workspace_id: $wid})
    RETURN a.name AS name, a.email AS email,
           r.commit_count AS commits, r.last_touch AS last_touch
    ORDER BY r.commit_count DESC
    """
    with driver.session() as session:
        rows = [dict(r) for r in session.run(query, path=file_path, wid=workspace_id)]

    return {
        "file_path": file_path,
        "owners": rows,
        "primary_owner": rows[0] if rows else None,
        "cypher_used": query
    }


def get_node_detail(node_id: str, node_type: str, workspace_id: str, driver) -> dict:
    """Get full details of a node."""
    if node_type == "File":
        query = """
        MATCH (f:File {path: $id, workspace_id: $wid})
        OPTIONAL MATCH (f)-[:CONTAINS]->(fn:Function)
        OPTIONAL MATCH (f)-[:CONTAINS]->(c:Class)
        RETURN f.path AS path, f.language AS language,
               f.line_count AS line_count, f.content_hash AS content_hash,
               count(DISTINCT fn) AS function_count,
               count(DISTINCT c) AS class_count
        """
    elif node_type == "Function":
        query = """
        MATCH (fn:Function {id: $id, workspace_id: $wid})
        OPTIONAL MATCH (fn)-[:CALLS]->(callee:Function)
        OPTIONAL MATCH (caller:Function)-[:CALLS]->(fn)
        RETURN fn.name AS name, fn.file_path AS file_path,
               fn.start_line AS start_line, fn.end_line AS end_line,
               count(DISTINCT callee) AS calls_count,
               count(DISTINCT caller) AS called_by_count
        """
    else:
        query = """
        MATCH (n {workspace_id: $wid})
        WHERE n.path = $id OR n.id = $id OR n.email = $id
        RETURN properties(n) AS props
        """

    with driver.session() as session:
        rows = [dict(r) for r in session.run(query, id=node_id, wid=workspace_id)]

    return {
        "node_id": node_id,
        "node_type": node_type,
        "data": rows[0] if rows else None,
        "found": len(rows) > 0
    }


def summarize_subgraph(nodes: list, edges: list, question: str) -> dict:
    """
    Lightweight summarizer — returns structured data for the orchestrator to use.
    Does not call GPT-4o directly; the orchestrator handles LLM calls.
    """
    node_types = {}
    for n in nodes:
        t = n.get("type", "unknown")
        node_types[t] = node_types.get(t, 0) + 1

    edge_types = {}
    for e in (edges or []):
        t = e.get("relationship", "unknown")
        edge_types[t] = edge_types.get(t, 0) + 1

    return {
        "node_count": len(nodes),
        "edge_count": len(edges or []),
        "node_types": node_types,
        "edge_types": edge_types,
        "question": question,
        "nodes": nodes[:50],   # cap to avoid context overflow
    }


# ── Dispatch ──────────────────────────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_args: dict, driver) -> dict:
    """Route a tool call to its implementation."""
    if tool_name == "query_graph":
        return query_graph(tool_args["cypher"], tool_args.get("params", {}), driver)
    elif tool_name == "find_dependents":
        return find_dependents(tool_args["file_path"], tool_args["workspace_id"], driver)
    elif tool_name == "find_owners":
        return find_owners(tool_args["file_path"], tool_args["workspace_id"], driver)
    elif tool_name == "get_node_detail":
        return get_node_detail(
            tool_args["node_id"], tool_args["node_type"],
            tool_args["workspace_id"], driver
        )
    elif tool_name == "summarize_subgraph":
        return summarize_subgraph(
            tool_args.get("nodes", []),
            tool_args.get("edges", []),
            tool_args.get("question", "")
        )
    else:
        return {"error": f"Unknown tool: {tool_name}"}