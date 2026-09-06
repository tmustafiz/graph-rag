import builtins
from pathlib import Path

import pytest

from graph_rag.ingest.parsers.javascript_parser import JavaScriptParser


def _write(tmp_path: Path, relative: str, body: str, *, project_marker: bool = True) -> Path:
    if project_marker:
        (tmp_path / "package.json").write_text("{}\n")
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _by_qualified_name(document) -> dict[str, object]:
    return {entity.qualified_name: entity for entity in document.code_entities}


def test_module_qualified_name_is_project_relative_dotted(tmp_path: Path) -> None:
    path = _write(tmp_path, "src/orders/order_service.ts", "export function submit() {}\n")

    document = JavaScriptParser().parse(path)

    module = document.code_entities[0]
    assert module.kind == "module"
    assert module.qualified_name == "src.orders.order_service"
    assert module.language == "typescript"
    assert _by_qualified_name(document)["src.orders.order_service.submit"].kind == "function"


def test_index_file_collapses_to_its_directory(tmp_path: Path) -> None:
    path = _write(tmp_path, "src/orders/index.ts", "export function submit() {}\n")

    document = JavaScriptParser().parse(path)

    assert document.code_entities[0].qualified_name == "src.orders"


def test_no_project_marker_falls_back_to_bare_stem(tmp_path: Path) -> None:
    path = _write(tmp_path, "loose.js", "export function go() {}\n", project_marker=False)

    document = JavaScriptParser().parse(path)

    names = {entity.qualified_name for entity in document.code_entities}
    assert names == {"loose", "loose.go"}
    assert document.code_entities[0].language == "javascript"


def test_esm_import_forms_are_all_collected_and_resolved(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/app/consumer.ts",
        'import Default from "./sibling";\n'
        'import { named } from "../lib/util";\n'
        'import * as ns from "./ns";\n'
        'import "./side-effect";\n'
        'export { re } from "./reexport";\n'
        'export * from "./star";\n'
        'const dynamic = import("./dynamic");\n'
        "export class Consumer {}\n",
    )

    document = JavaScriptParser().parse(path)

    # Named imports/re-exports resolve to `module.symbol` (like Python's
    # `from x import y`); default / namespace / side-effect / `*` to the module.
    assert document.code_entities[0].imports == [
        "src.app.sibling",
        "src.lib.util.named",
        "src.app.ns",
        "src.app.side-effect",
        "src.app.reexport.re",
        "src.app.star",
        "src.app.dynamic",
    ]


def test_commonjs_require_forms_are_collected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/util/log.js",
        'const { format } = require("../shared/fmt");\n'
        'const os = require("os");\n'
        "function info(message) { return format(message); }\n",
    )

    document = JavaScriptParser().parse(path)

    module = document.code_entities[0]
    assert module.imports == ["src.shared.fmt", "os"]
    info = _by_qualified_name(document)["src.util.log.info"]
    assert info.calls == ["src.shared.fmt.format"]


def test_bare_specifiers_are_kept_verbatim(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/ui/widget.tsx",
        'import React from "react";\nimport _ from "lodash";\n'
        'import { join } from "node:path";\n'
        "export function Widget() { return null; }\n",
    )

    document = JavaScriptParser().parse(path)

    # Bare specifiers are never resolved against the file tree.
    assert document.code_entities[0].imports == ["react", "lodash", "node:path.join"]


def test_exported_arrow_const_becomes_a_function_entity(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/math.ts",
        "/** Adds two numbers. */\nexport const add = (a: number, b: number): number => a + b;\n",
    )

    document = JavaScriptParser().parse(path)

    add = _by_qualified_name(document)["src.math.add"]
    assert add.kind == "function"
    assert add.signature == "(a: number, b: number): number"
    assert add.docstring == "Adds two numbers."
    assert add.embed_text == "Adds two numbers."


def test_class_methods_getters_and_this_calls(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/orders/service.ts",
        "export class Service {\n"
        "  constructor() {}\n"
        "  submit(order) { this.accepts(order); }\n"
        "  accepts(order) { return true; }\n"
        "  get size() { return 1; }\n"
        "  set size(value) {}\n"
        "}\n",
    )

    document = JavaScriptParser().parse(path)
    by_qualified_name = _by_qualified_name(document)

    assert by_qualified_name["src.orders.service.Service"].kind == "class"
    assert by_qualified_name["src.orders.service.Service.constructor"].kind == "constructor"
    submit = by_qualified_name["src.orders.service.Service.submit"]
    assert submit.parent_qualified_name == "src.orders.service.Service"
    assert submit.calls == ["src.orders.service.Service.accepts"]
    # getter + setter for `size` collapse to one entity.
    assert sum(1 for name in by_qualified_name if name.endswith(".size")) == 1


def test_typescript_type_flavors_map_to_kind_with_signatures(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/model.ts",
        "export interface Shape { area(): number; }\n"
        "export type ID = string | number;\n"
        "export enum Lane { FAST, SLOW }\n",
    )

    document = JavaScriptParser().parse(path)
    by_qualified_name = _by_qualified_name(document)

    assert by_qualified_name["src.model.Shape"].kind == "interface"
    assert "Members: area" in by_qualified_name["src.model.Shape"].embed_text
    assert by_qualified_name["src.model.ID"].kind == "type"
    assert by_qualified_name["src.model.ID"].signature == "string | number"
    assert by_qualified_name["src.model.Lane"].kind == "enum"
    assert "Members: FAST, SLOW" in by_qualified_name["src.model.Lane"].embed_text


def test_async_and_generator_markers_in_signature(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/io.ts",
        "export async function load(url: string): Promise<string> { return url; }\n"
        "export function* range(n) { yield n; }\n",
    )

    document = JavaScriptParser().parse(path)
    by_qualified_name = _by_qualified_name(document)

    assert by_qualified_name["src.io.load"].signature == "async (url: string): Promise<string>"
    assert by_qualified_name["src.io.range"].signature == "*(n)"


def test_calls_resolve_for_local_and_imported_names(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/orders/flow.ts",
        'import { publish } from "../events/bus";\n'
        'import * as metrics from "./metrics";\n'
        "export function run() {\n"
        "  helper();\n"
        "  publish();\n"
        "  metrics.count();\n"
        "  window.setTimeout();\n"
        "}\n"
        "export function helper() {}\n",
    )

    document = JavaScriptParser().parse(path)

    run = _by_qualified_name(document)["src.orders.flow.run"]
    assert set(run.calls) == {
        "src.orders.flow.helper",
        "src.events.bus.publish",
        "src.orders.metrics.count",
    }


def test_module_jsdoc_becomes_docstring(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/entry.ts",
        "/**\n * The entry point.\n * @module\n */\nexport function main() {}\n",
    )

    document = JavaScriptParser().parse(path)

    assert document.code_entities[0].docstring == "The entry point."


def test_syntax_error_yields_partial_result_without_raising(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/broken.jsx",
        "export function ok() {}\nexport function busted( {\n",
    )

    document = JavaScriptParser().parse(path)

    names = {entity.name for entity in document.code_entities}
    assert "ok" in names


def test_can_handle_matches_every_js_ts_extension() -> None:
    for name in ("a.js", "a.mjs", "a.cjs", "a.jsx", "a.ts", "a.tsx", "A.TS"):
        assert JavaScriptParser.can_handle(Path(name)) is True
    assert JavaScriptParser.can_handle(Path("a.java")) is False
    assert JavaScriptParser.can_handle(Path("a.py")) is False


def test_parse_without_tree_sitter_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):  # noqa: ANN202
        if name == "tree_sitter_language_pack":
            raise ModuleNotFoundError("No module named 'tree_sitter_language_pack'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"'js' extra"):
        JavaScriptParser().parse(Path("Whatever.ts"))
