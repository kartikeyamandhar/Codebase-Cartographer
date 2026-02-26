"""
Phase 1 - Task 1.1
Python AST parser using tree-sitter.
Extracts: functions, classes, imports, call expressions from .py files.
Raw output first - no abstraction until we understand what tree-sitter returns.
"""

import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from tree_sitter_languages import get_language, get_parser


# ── Language setup ────────────────────────────────────────────────────────────

PY_LANGUAGE = get_language("python")
PARSER = get_parser("python")


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ParsedFunction:
    name: str
    file_path: str
    start_line: int
    end_line: int
    parameters: list[str]
    body_text: str
    class_name: Optional[str] = None          # set if this is a method
    calls: list[dict] = field(default_factory=list)  # filled by call_resolver


@dataclass
class ParsedClass:
    name: str
    file_path: str
    start_line: int
    end_line: int
    base_classes: list[str]
    methods: list[str] = field(default_factory=list)


@dataclass
class ParsedImport:
    module: str                   # e.g. "os.path", "flask"
    names: list[str]              # e.g. ["join", "exists"] or ["Flask"]
    alias: Optional[str]          # e.g. "np" for "import numpy as np"
    is_from: bool                 # True = "from x import y", False = "import x"
    source_file: str


@dataclass
class ParsedFile:
    path: str
    language: str
    line_count: int
    content_hash: str
    functions: list[ParsedFunction]
    classes: list[ParsedClass]
    imports: list[ParsedImport]
    parse_errors: list[str] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ── Parameter extraction ──────────────────────────────────────────────────────

def _extract_parameters(params_node, source: bytes) -> list[str]:
    """Extract parameter names from a parameters node."""
    params = []
    if params_node is None:
        return params

    for child in params_node.children:
        kind = child.type
        if kind == "identifier":
            params.append(_node_text(child, source))
        elif kind in ("typed_parameter", "default_parameter", "typed_default_parameter"):
            # first named child is the parameter name
            for subchild in child.children:
                if subchild.type == "identifier":
                    params.append(_node_text(subchild, source))
                    break
        elif kind in ("list_splat_pattern", "dictionary_splat_pattern"):
            for subchild in child.children:
                if subchild.type == "identifier":
                    params.append(_node_text(subchild, source))
                    break
    return params


# ── Base class extraction ─────────────────────────────────────────────────────

def _extract_base_classes(class_node, source: bytes) -> list[str]:
    bases = []
    for child in class_node.children:
        if child.type == "argument_list":
            for arg in child.children:
                if arg.type in ("identifier", "attribute"):
                    bases.append(_node_text(arg, source))
    return bases


# ── Import extraction ─────────────────────────────────────────────────────────

def _extract_import(node, source: bytes, file_path: str) -> Optional[ParsedImport]:
    """Handle both 'import x' and 'from x import y' statements."""
    text = _node_text(node, source)

    if node.type == "import_statement":
        # import os / import os as operating_system / import os, sys
        names = []
        alias = None
        module = None
        for child in node.children:
            if child.type == "dotted_name":
                module = _node_text(child, source)
            elif child.type == "aliased_import":
                parts = [c for c in child.children if c.type in ("dotted_name", "identifier")]
                if parts:
                    module = _node_text(parts[0], source)
                if len(parts) > 1:
                    alias = _node_text(parts[-1], source)
        return ParsedImport(
            module=module or text,
            names=names,
            alias=alias,
            is_from=False,
            source_file=file_path,
        )

    elif node.type == "import_from_statement":
        # from os.path import join, exists
        # from . import something  (relative)
        module = None
        names = []
        children = list(node.children)

        # find module name — first dotted_name or relative_import after 'from'
        for i, child in enumerate(children):
            if child.type in ("dotted_name", "relative_import"):
                module = _node_text(child, source)
                break

        # find imported names — dotted_name or identifier after 'import'
        after_import = False
        for child in children:
            if child.type == "import" and _node_text(child, source) == "import":
                after_import = True
                continue
            if after_import:
                if child.type in ("dotted_name", "identifier"):
                    names.append(_node_text(child, source))
                elif child.type == "aliased_import":
                    parts = [c for c in child.children if c.type in ("dotted_name", "identifier")]
                    if parts:
                        names.append(_node_text(parts[0], source))
                elif child.type == "wildcard_import":
                    names.append("*")

        return ParsedImport(
            module=module or "",
            names=names,
            alias=None,
            is_from=True,
            source_file=file_path,
        )

    return None


# ── Function extraction ───────────────────────────────────────────────────────

def _extract_function(node, source: bytes, file_path: str,
                       class_name: Optional[str] = None) -> Optional[ParsedFunction]:
    name = None
    params_node = None
    body_node = None

    for child in node.children:
        if child.type == "identifier":
            name = _node_text(child, source)
        elif child.type == "parameters":
            params_node = child
        elif child.type == "block":
            body_node = child

    if name is None:
        return None

    body_text = _node_text(body_node, source) if body_node else ""
    parameters = _extract_parameters(params_node, source)

    return ParsedFunction(
        name=name,
        file_path=file_path,
        start_line=node.start_point[0] + 1,   # tree-sitter is 0-indexed
        end_line=node.end_point[0] + 1,
        parameters=parameters,
        body_text=body_text,
        class_name=class_name,
    )


# ── Class extraction ──────────────────────────────────────────────────────────

def _extract_class(node, source: bytes, file_path: str) -> tuple[Optional[ParsedClass], list[ParsedFunction]]:
    """Returns the class and all its methods."""
    name = None
    for child in node.children:
        if child.type == "identifier":
            name = _node_text(child, source)
            break

    if name is None:
        return None, []

    base_classes = _extract_base_classes(node, source)
    methods = []

    # Walk the class body for method definitions
    for child in node.children:
        if child.type == "block":
            for item in child.children:
                if item.type == "function_definition":
                    method = _extract_function(item, source, file_path, class_name=name)
                    if method:
                        methods.append(method)
                elif item.type == "decorated_definition":
                    for subitem in item.children:
                        if subitem.type == "function_definition":
                            method = _extract_function(subitem, source, file_path, class_name=name)
                            if method:
                                methods.append(method)

    parsed_class = ParsedClass(
        name=name,
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        base_classes=base_classes,
        methods=[m.name for m in methods],
    )

    return parsed_class, methods


# ── Main parse function ───────────────────────────────────────────────────────

def parse_python_file(file_path: str) -> ParsedFile:
    """
    Parse a single .py file. Returns a ParsedFile with all extracted nodes.
    Logs parse errors as a ratio — does not raise.
    """
    path = Path(file_path)
    errors = []

    try:
        content = path.read_bytes()
    except Exception as e:
        return ParsedFile(
            path=file_path,
            language="python",
            line_count=0,
            content_hash="",
            functions=[],
            classes=[],
            imports=[],
            parse_errors=[f"read_error: {e}"],
        )

    tree = PARSER.parse(content)
    root = tree.root_node

    # Log if tree-sitter found syntax errors
    if root.has_error:
        errors.append("tree_sitter_syntax_error: partial parse may be incomplete")

    functions: list[ParsedFunction] = []
    classes: list[ParsedClass] = []
    imports: list[ParsedImport] = []

    # Track which functions are methods (to avoid double-adding)
    method_ids: set[tuple] = set()

    def walk(node, current_class: Optional[str] = None):
        if node.type == "class_definition":
            parsed_class, methods = _extract_class(node, content, file_path)
            if parsed_class:
                classes.append(parsed_class)
                for m in methods:
                    functions.append(m)
                    method_ids.add((m.name, m.start_line))
            # Don't recurse further — _extract_class handles its own body
            return

        if node.type == "function_definition":
            key = (None, node.start_point[0] + 1)
            if key not in method_ids:
                fn = _extract_function(node, content, file_path, class_name=current_class)
                if fn:
                    functions.append(fn)
            # Recurse into nested functions
            for child in node.children:
                if child.type == "block":
                    for item in child.children:
                        walk(item, current_class)
            return

        if node.type in ("import_statement", "import_from_statement"):
            imp = _extract_import(node, content, file_path)
            if imp:
                imports.append(imp)
            return

        if node.type == "decorated_definition":
            for child in node.children:
                if child.type == "function_definition":
                    fn = _extract_function(child, content, file_path)
                    if fn:
                        functions.append(fn)
            return

        for child in node.children:
            walk(child, current_class)

    walk(root)

    line_count = content.decode("utf-8", errors="replace").count("\n") + 1

    return ParsedFile(
        path=file_path,
        language="python",
        line_count=line_count,
        content_hash=_content_hash(content),
        functions=functions,
        classes=classes,
        imports=imports,
        parse_errors=errors,
    )


def parse_directory(repo_path: str, workspace_id: str) -> list[ParsedFile]:
    """
    Walk a repo directory and parse all .py files.
    Skips files over 500KB. Logs skip ratio.
    """
    root = Path(repo_path)
    py_files = list(root.rglob("*.py"))

    total = len(py_files)
    skipped = 0
    results = []

    for fp in py_files:
        if fp.stat().st_size > 500 * 1024:   # 500KB limit per plan
            skipped += 1
            continue
        parsed = parse_python_file(str(fp))
        results.append(parsed)

    error_count = sum(1 for r in results if r.parse_errors)
    error_ratio = error_count / max(len(results), 1)

    if error_ratio > 0.05:
        print(f"[WARNING] Parse error ratio {error_ratio:.1%} exceeds 5% threshold — investigate before continuing")

    if skipped:
        print(f"[INFO] Skipped {skipped}/{total} files over 500KB")

    return results