"""
Phase 2 - Task 2.3
TypeScript / JavaScript AST parser using tree-sitter.

Handles TS-specific constructs:
- ES module imports/exports
- Arrow functions
- Interface declarations
- Type annotations
- Decorators
- Class declarations

Does NOT force TS constructs into the Python schema — extends it.
Language detection by file extension.
Skips .json, .md, .yaml, .env and files over 500KB.
"""

import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from tree_sitter_languages import get_language, get_parser

from ingestion.parse_python import (
    ParsedFile, ParsedFunction, ParsedClass, ParsedImport, _content_hash
)


TS_LANGUAGE = get_language("typescript")
TSX_LANGUAGE = get_language("tsx")
JS_LANGUAGE = get_language("javascript")

TS_PARSER = get_parser("typescript")
TSX_PARSER = get_parser("tsx")
JS_PARSER = get_parser("javascript")

SUPPORTED_EXTENSIONS = {
    ".ts": (TS_LANGUAGE, TS_PARSER, "typescript"),
    ".tsx": (TSX_LANGUAGE, TSX_PARSER, "tsx"),
    ".js": (JS_LANGUAGE, JS_PARSER, "javascript"),
    ".jsx": (JS_LANGUAGE, JS_PARSER, "jsx"),
}

SKIP_EXTENSIONS = {".json", ".md", ".yaml", ".yml", ".env", ".lock", ".toml"}
MAX_FILE_SIZE = 500 * 1024  # 500KB


# ── Helpers ───────────────────────────────────────────────────────────────────

def _node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


# ── Function extraction ───────────────────────────────────────────────────────

def _extract_ts_function(node, source: bytes, file_path: str,
                          class_name: Optional[str] = None) -> Optional[ParsedFunction]:
    """
    Extract function from:
    - function_declaration
    - method_definition
    - arrow_function (when assigned to variable)
    """
    name = None
    params_node = None

    for child in node.children:
        if child.type == "identifier" and name is None:
            name = _node_text(child, source)
        elif child.type == "property_identifier" and name is None:
            name = _node_text(child, source)
        elif child.type == "formal_parameters":
            params_node = child

    if name is None:
        return None

    params = []
    if params_node:
        for child in params_node.children:
            if child.type == "identifier":
                params.append(_node_text(child, source))
            elif child.type in ("required_parameter", "optional_parameter"):
                for subchild in child.children:
                    if subchild.type == "identifier":
                        params.append(_node_text(subchild, source))
                        break

    # Get body text
    body_text = ""
    for child in node.children:
        if child.type in ("statement_block", "expression"):
            body_text = _node_text(child, source)
            break

    return ParsedFunction(
        name=name,
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parameters=params,
        body_text=body_text,
        class_name=class_name,
    )


# ── Class extraction ──────────────────────────────────────────────────────────

def _extract_ts_class(node, source: bytes, file_path: str) -> tuple[Optional[ParsedClass], list[ParsedFunction]]:
    name = None
    base_classes = []
    methods = []

    for child in node.children:
        if child.type == "type_identifier" and name is None:
            name = _node_text(child, source)
        elif child.type == "identifier" and name is None:
            name = _node_text(child, source)
        elif child.type == "class_heritage":
            for subchild in child.children:
                if subchild.type in ("identifier", "type_identifier"):
                    base_classes.append(_node_text(subchild, source))
        elif child.type == "class_body":
            for item in child.children:
                if item.type == "method_definition":
                    method = _extract_ts_function(item, source, file_path, class_name=name)
                    if method:
                        methods.append(method)
                elif item.type == "public_field_definition":
                    # Arrow function as class field
                    for subitem in item.children:
                        if subitem.type == "arrow_function":
                            method = _extract_ts_function(subitem, source, file_path, class_name=name)
                            if method:
                                # Use field name as method name
                                field_name = None
                                for fc in item.children:
                                    if fc.type in ("property_identifier", "identifier"):
                                        field_name = _node_text(fc, source)
                                        break
                                if field_name and method:
                                    method.name = field_name
                                    methods.append(method)

    if name is None:
        return None, []

    parsed_class = ParsedClass(
        name=name,
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        base_classes=base_classes,
        methods=[m.name for m in methods],
    )

    return parsed_class, methods


# ── Import extraction ─────────────────────────────────────────────────────────

def _extract_ts_import(node, source: bytes, file_path: str) -> Optional[ParsedImport]:
    """
    Handle ES module imports:
    - import { X } from 'module'
    - import X from 'module'
    - import * as X from 'module'
    - import type { X } from 'module'
    """
    module = None
    names = []
    alias = None

    # Find string (module path)
    for child in node.children:
        if child.type == "string":
            raw = _node_text(child, source)
            module = raw.strip("'\"")

    # Find imported names
    for child in node.children:
        if child.type == "import_clause":
            for subchild in child.children:
                if subchild.type == "identifier":
                    # default import: import X from ...
                    names.append(_node_text(subchild, source))
                elif subchild.type == "named_imports":
                    for item in subchild.children:
                        if item.type == "import_specifier":
                            for ic in item.children:
                                if ic.type == "identifier":
                                    names.append(_node_text(ic, source))
                                    break
                elif subchild.type == "namespace_import":
                    # import * as X
                    for ic in subchild.children:
                        if ic.type == "identifier":
                            alias = _node_text(ic, source)
                            names.append("*")
                            break

    if module is None:
        return None

    return ParsedImport(
        module=module,
        names=names,
        alias=alias,
        is_from=True,
        source_file=file_path,
    )


# ── Main parse function ───────────────────────────────────────────────────────

def parse_ts_file(file_path: str) -> ParsedFile:
    """
    Parse a single TypeScript/JavaScript file.
    Returns a ParsedFile using the same structure as parse_python.py.
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    errors = []

    if ext not in SUPPORTED_EXTENSIONS:
        return ParsedFile(
            path=file_path, language="unknown", line_count=0,
            content_hash="", functions=[], classes=[], imports=[],
            parse_errors=[f"unsupported_extension:{ext}"],
        )

    _, parser, language = SUPPORTED_EXTENSIONS[ext]

    try:
        content = path.read_bytes()
    except Exception as e:
        return ParsedFile(
            path=file_path, language=language, line_count=0,
            content_hash="", functions=[], classes=[], imports=[],
            parse_errors=[f"read_error:{e}"],
        )

    tree = parser.parse(content)
    root = tree.root_node

    if root.has_error:
        errors.append("tree_sitter_syntax_error:partial_parse")

    functions: list[ParsedFunction] = []
    classes: list[ParsedClass] = []
    imports: list[ParsedImport] = []
    method_lines: set[int] = set()

    def walk(node):
        if node.type == "class_declaration":
            parsed_class, methods = _extract_ts_class(node, content, file_path)
            if parsed_class:
                classes.append(parsed_class)
                for m in methods:
                    functions.append(m)
                    method_lines.add(m.start_line)
            return

        if node.type in ("function_declaration", "function"):
            if node.start_point[0] + 1 not in method_lines:
                fn = _extract_ts_function(node, content, file_path)
                if fn:
                    functions.append(fn)
            return

        if node.type == "lexical_declaration":
            # const fn = () => {} or const fn = function() {}
            for child in node.children:
                if child.type == "variable_declarator":
                    var_name = None
                    arrow_fn = None
                    for subchild in child.children:
                        if subchild.type == "identifier" and var_name is None:
                            var_name = _node_text(subchild, content)
                        elif subchild.type == "arrow_function":
                            arrow_fn = subchild
                        elif subchild.type == "function":
                            arrow_fn = subchild
                    if var_name and arrow_fn:
                        fn = _extract_ts_function(arrow_fn, content, file_path)
                        if fn:
                            fn.name = var_name
                            functions.append(fn)
            return

        if node.type == "import_statement":
            imp = _extract_ts_import(node, content, file_path)
            if imp:
                imports.append(imp)
            return

        if node.type == "export_statement":
            # export function / export class / export const
            for child in node.children:
                if child.type in ("function_declaration", "function"):
                    fn = _extract_ts_function(child, content, file_path)
                    if fn:
                        functions.append(fn)
                elif child.type == "class_declaration":
                    parsed_class, methods = _extract_ts_class(child, content, file_path)
                    if parsed_class:
                        classes.append(parsed_class)
                        functions.extend(methods)
                elif child.type == "lexical_declaration":
                    for subchild in child.children:
                        if subchild.type == "variable_declarator":
                            var_name = None
                            arrow_fn = None
                            for item in subchild.children:
                                if item.type == "identifier" and var_name is None:
                                    var_name = _node_text(item, content)
                                elif item.type == "arrow_function":
                                    arrow_fn = item
                            if var_name and arrow_fn:
                                fn = _extract_ts_function(arrow_fn, content, file_path)
                                if fn:
                                    fn.name = var_name
                                    functions.append(fn)
            return

        for child in node.children:
            walk(child)

    walk(root)

    line_count = content.decode("utf-8", errors="replace").count("\n") + 1

    return ParsedFile(
        path=file_path,
        language=language,
        line_count=line_count,
        content_hash=_content_hash(content),
        functions=functions,
        classes=classes,
        imports=imports,
        parse_errors=errors,
    )


def parse_ts_directory(repo_path: str, workspace_id: str) -> list[ParsedFile]:
    """
    Walk a repo directory and parse all TS/JS files.
    Skips files over 500KB and unsupported extensions.
    """
    root = Path(repo_path)
    ts_files = []

    for ext in SUPPORTED_EXTENSIONS:
        ts_files.extend(root.rglob(f"*{ext}"))

    # Deduplicate
    ts_files = list(set(ts_files))

    total = len(ts_files)
    skipped = 0
    results = []

    for fp in ts_files:
        if fp.stat().st_size > MAX_FILE_SIZE:
            skipped += 1
            continue
        parsed = parse_ts_file(str(fp))
        results.append(parsed)

    error_count = sum(1 for r in results if r.parse_errors)
    error_ratio = error_count / max(len(results), 1)

    if error_ratio > 0.10:
        print(f"[WARNING] TS parse error ratio {error_ratio:.1%} exceeds 10% — "
              f"investigate grammar version before continuing")

    if skipped:
        print(f"[INFO] Skipped {skipped}/{total} TS/JS files over 500KB")

    return results