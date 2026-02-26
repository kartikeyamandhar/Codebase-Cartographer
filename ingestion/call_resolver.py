"""
Phase 1 - Task 1.2
Call graph construction via best-effort static analysis.

Resolution priority (per plan):
1. Direct name match in the same file         → resolved: true,  confidence: high
2. Name match in an imported module            → resolved: true,  confidence: medium
3. Attribute call (obj.method())               → resolved: false, reason: attribute_call
4. Dynamic call (*args, **kwargs patterns)     → resolved: false, reason: dynamic_call
5. Built-in or unknown                         → resolved: false, reason: unresolved_name

Critical rule: NEVER silently drop unresolved calls.
Every call gets an edge. Unresolved edges are tagged, not removed.
"""

from dataclasses import dataclass
from typing import Optional

from tree_sitter_languages import get_language, get_parser

from ingestion.parse_python import ParsedFile, ParsedFunction


PY_LANGUAGE = get_language("python")
PARSER = get_parser("python")


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class CallEdge:
    caller_id: str          # "file_path::function_name"
    callee_name: str        # raw name extracted from AST
    callee_id: Optional[str]  # resolved node id, None if unresolved
    resolved: bool
    confidence: str         # "high", "medium", "low"
    reason: str             # explanation string — always populated
    call_site_line: int


# ── Python builtins (skip these — not user-defined) ──────────────────────────

PYTHON_BUILTINS = {
    "print", "len", "range", "enumerate", "zip", "map", "filter",
    "isinstance", "issubclass", "type", "id", "hash", "repr", "str",
    "int", "float", "bool", "list", "dict", "set", "tuple", "frozenset",
    "sorted", "reversed", "min", "max", "sum", "abs", "round",
    "open", "hasattr", "getattr", "setattr", "delattr", "callable",
    "iter", "next", "super", "object", "property", "staticmethod",
    "classmethod", "any", "all", "vars", "dir", "help",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "StopIteration", "NotImplementedError",
    "raise", "assert", "pass",
}


# ── AST call extractor ────────────────────────────────────────────────────────

def _extract_raw_calls(body_text: str, start_line_offset: int) -> list[dict]:
    """
    Parse a function body and extract all call expressions.
    Returns raw call dicts before resolution.
    """
    # Wrap body in a function so tree-sitter can parse it as valid Python
    wrapped = f"def __wrapper__():\n"
    # Indent each line of body
    indented = "\n".join("    " + line for line in body_text.splitlines())
    source = (wrapped + indented).encode("utf-8")

    tree = PARSER.parse(source)
    root = tree.root_node

    raw_calls = []

    def walk(node):
        if node.type == "call":
            call_info = _classify_call(node, source, start_line_offset)
            if call_info:
                raw_calls.append(call_info)
            # Still recurse — nested calls inside arguments
            for child in node.children:
                walk(child)
            return

        for child in node.children:
            walk(child)

    walk(root)
    return raw_calls


def _classify_call(call_node, source: bytes, line_offset: int) -> Optional[dict]:
    """
    Classify a call node into one of four categories.
    Returns a dict with type and name info.
    """
    # Line number: subtract 1 for wrapper line, add back original offset
    line = call_node.start_point[0] - 1 + line_offset

    func_node = None
    for child in call_node.children:
        if child.type not in ("argument_list",):
            func_node = child
            break

    if func_node is None:
        return None

    text = source[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="replace")

    # Dynamic call patterns — *args or **kwargs in the call itself
    arg_list = None
    for child in call_node.children:
        if child.type == "argument_list":
            arg_list = child
            break

    if arg_list:
        for arg in arg_list.children:
            if arg.type in ("list_splat", "dictionary_splat"):
                return {
                    "type": "dynamic",
                    "name": text,
                    "line": line,
                }

    # Attribute call: obj.method() or module.Class.method()
    if func_node.type == "attribute":
        obj_node = func_node.children[0] if func_node.children else None
        method_node = func_node.children[-1] if func_node.children else None
        obj = source[obj_node.start_byte:obj_node.end_byte].decode("utf-8", errors="replace") if obj_node else ""
        method = source[method_node.start_byte:method_node.end_byte].decode("utf-8", errors="replace") if method_node else ""
        return {
            "type": "attribute",
            "name": text,
            "object": obj,
            "method": method,
            "line": line,
        }

    # Direct identifier call: function_name()
    if func_node.type == "identifier":
        return {
            "type": "direct",
            "name": text,
            "line": line,
        }

    # Subscript call: something[x]() — treat as unresolved
    return {
        "type": "unknown",
        "name": text,
        "line": line,
    }


# ── Resolution logic ──────────────────────────────────────────────────────────

def _build_name_index(parsed_files: list[ParsedFile]) -> dict[str, dict]:
    """
    Build a lookup index:
      function_name -> {file_path -> node_id}
    Used for cross-file resolution.
    """
    index: dict[str, list[dict]] = {}
    for pf in parsed_files:
        for fn in pf.functions:
            node_id = f"{pf.path}::{fn.name}"
            if fn.name not in index:
                index[fn.name] = []
            index[fn.name].append({
                "node_id": node_id,
                "file_path": pf.path,
            })
    return index


def _build_import_map(parsed_file: ParsedFile) -> dict[str, str]:
    """
    Build a map of: local_name -> module
    e.g. "from flask import Flask" -> {"Flask": "flask"}
         "import os" -> {"os": "os"}
         "import numpy as np" -> {"np": "numpy"}
    """
    imp_map = {}
    for imp in parsed_file.imports:
        if imp.is_from:
            for name in imp.names:
                imp_map[name] = imp.module
        else:
            key = imp.alias if imp.alias else imp.module.split(".")[0]
            imp_map[key] = imp.module
    return imp_map


def resolve_calls(
    parsed_file: ParsedFile,
    all_files: list[ParsedFile],
    name_index: dict[str, dict],
) -> list[CallEdge]:
    """
    For every function in parsed_file, extract and resolve all calls.
    Returns a flat list of CallEdge objects.
    """
    import_map = _build_import_map(parsed_file)

    # Local function names in this file for priority-1 resolution
    local_names: dict[str, str] = {}
    for fn in parsed_file.functions:
        node_id = f"{parsed_file.path}::{fn.name}"
        local_names[fn.name] = node_id

    edges: list[CallEdge] = []

    for fn in parsed_file.functions:
        caller_id = f"{parsed_file.path}::{fn.name}"

        if not fn.body_text.strip():
            continue

        raw_calls = _extract_raw_calls(fn.body_text, fn.start_line)

        for call in raw_calls:
            name = call.get("name", "")
            line = call.get("line", fn.start_line)
            call_type = call.get("type", "unknown")

            # ── Dynamic calls — tag and skip ──────────────────────────────
            if call_type == "dynamic":
                edges.append(CallEdge(
                    caller_id=caller_id,
                    callee_name=name,
                    callee_id=None,
                    resolved=False,
                    confidence="none",
                    reason="dynamic_call_skipped",
                    call_site_line=line,
                ))
                continue

            # ── Attribute calls ───────────────────────────────────────────
            if call_type == "attribute":
                method = call.get("method", "")
                obj = call.get("object", "")

                # Try to resolve: if obj is in import_map, it's a module call
                if obj in import_map:
                    # e.g. os.path.join — medium confidence
                    edges.append(CallEdge(
                        caller_id=caller_id,
                        callee_name=name,
                        callee_id=None,
                        resolved=False,
                        confidence="low",
                        reason=f"attribute_call_on_import:{import_map[obj]}",
                        call_site_line=line,
                    ))
                else:
                    # obj could be self, a local var, etc.
                    edges.append(CallEdge(
                        caller_id=caller_id,
                        callee_name=name,
                        callee_id=None,
                        resolved=False,
                        confidence="none",
                        reason=f"attribute_call_unresolvable_object:{obj}",
                        call_site_line=line,
                    ))
                continue

            # ── Unknown call type ─────────────────────────────────────────
            if call_type == "unknown":
                edges.append(CallEdge(
                    caller_id=caller_id,
                    callee_name=name,
                    callee_id=None,
                    resolved=False,
                    confidence="none",
                    reason="unknown_call_expression",
                    call_site_line=line,
                ))
                continue

            # ── Direct calls — attempt resolution ─────────────────────────
            # Skip builtins
            if name in PYTHON_BUILTINS:
                continue

            # Priority 1: same-file match
            if name in local_names:
                edges.append(CallEdge(
                    caller_id=caller_id,
                    callee_name=name,
                    callee_id=local_names[name],
                    resolved=True,
                    confidence="high",
                    reason="same_file_direct_match",
                    call_site_line=line,
                ))
                continue

            # Priority 2: imported name match
            if name in import_map:
                # The name was imported — find it in name_index
                candidates = name_index.get(name, [])
                module = import_map[name]
                # Try to match by module path
                matched = None
                for c in candidates:
                    if module.replace(".", "/") in c["file_path"] or \
                       c["file_path"].endswith(module.replace(".", "/") + ".py"):
                        matched = c
                        break
                if matched:
                    edges.append(CallEdge(
                        caller_id=caller_id,
                        callee_name=name,
                        callee_id=matched["node_id"],
                        resolved=True,
                        confidence="medium",
                        reason=f"imported_from:{module}",
                        call_site_line=line,
                    ))
                else:
                    edges.append(CallEdge(
                        caller_id=caller_id,
                        callee_name=name,
                        callee_id=None,
                        resolved=False,
                        confidence="low",
                        reason=f"imported_but_not_in_graph:{module}",
                        call_site_line=line,
                    ))
                continue

            # Priority 3: cross-file name match (no import)
            candidates = name_index.get(name, [])
            if candidates:
                # Multiple candidates — take first but flag ambiguity
                best = candidates[0]
                reason = "cross_file_name_match"
                if len(candidates) > 1:
                    reason = f"cross_file_ambiguous_match:{len(candidates)}_candidates"
                edges.append(CallEdge(
                    caller_id=caller_id,
                    callee_name=name,
                    callee_id=best["node_id"],
                    resolved=True,
                    confidence="low",
                    reason=reason,
                    call_site_line=line,
                ))
                continue

            # Unresolved — name not found anywhere
            edges.append(CallEdge(
                caller_id=caller_id,
                callee_name=name,
                callee_id=None,
                resolved=False,
                confidence="none",
                reason="unresolved_name_not_in_graph",
                call_site_line=line,
            ))

    return edges


def resolve_all_calls(parsed_files: list[ParsedFile]) -> list[CallEdge]:
    """
    Entry point. Resolves calls across all parsed files.
    Prints resolution stats.
    """
    name_index = _build_name_index(parsed_files)
    all_edges: list[CallEdge] = []

    for pf in parsed_files:
        edges = resolve_calls(pf, parsed_files, name_index)
        all_edges.extend(edges)

    total = len(all_edges)
    resolved = sum(1 for e in all_edges if e.resolved)
    dynamic = sum(1 for e in all_edges if "dynamic" in e.reason)
    unresolved = total - resolved

    if total > 0:
        ratio = resolved / total
        print(f"[CALL RESOLUTION] {resolved}/{total} resolved ({ratio:.1%}) | "
              f"{dynamic} dynamic skipped | {unresolved} unresolved tagged")
        if ratio < 0.70:
            print(f"[WARNING] Resolution ratio {ratio:.1%} below 70% threshold — "
                  f"review unresolved edges before continuing")

    return all_edges