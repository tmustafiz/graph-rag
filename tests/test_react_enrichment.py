from pathlib import Path

from graph_rag.ingest.parsers.javascript_parser import JavaScriptParser


def _write(tmp_path: Path, relative: str, body: str) -> Path:
    (tmp_path / "package.json").write_text("{}\n")
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _by_qualified_name(document) -> dict[str, object]:
    return {entity.qualified_name: entity for entity in document.code_entities}


def test_function_component_is_detected_and_retagged(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/ui/panel.tsx",
        "export function Panel() {\n  return <div>hello</div>;\n}\n"
        "export function helper(value) {\n  return value + 1;\n}\n",
    )

    document = JavaScriptParser().parse(path)
    by_qualified_name = _by_qualified_name(document)

    assert by_qualified_name["src.ui.panel.Panel"].kind == "component"
    # A JSX-free function is left alone.
    assert by_qualified_name["src.ui.panel.helper"].kind == "function"


def test_class_component_is_detected_via_react_component_base(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/ui/legacy.tsx",
        "export class Legacy extends React.Component {\n"
        "  render() {\n    return <p>old</p>;\n  }\n"
        "}\n",
    )

    document = JavaScriptParser().parse(path)

    assert _by_qualified_name(document)["src.ui.legacy.Legacy"].kind == "component"


def test_renders_edge_is_added_for_a_resolvable_child(tmp_path: Path) -> None:
    _write(tmp_path, "src/ui/row.tsx", "export function Row() {\n  return <tr/>;\n}\n")
    path = _write(
        tmp_path,
        "src/ui/table.tsx",
        'import { Row } from "./row";\n'
        "export function Table({ items }) {\n"
        "  return (\n"
        "    <div>\n"
        "      {items.map((item) => <Row key={item.id} />)}\n"
        "    </div>\n"
        "  );\n"
        "}\n",
    )

    document = JavaScriptParser().parse(path)

    table = _by_qualified_name(document)["src.ui.table.Table"]
    assert table.kind == "component"
    assert table.renders == ["src.ui.row.Row"]


def test_no_edge_for_unresolved_or_lowercase_or_self_tags(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/ui/mixed.tsx",
        "export function Mixed() {\n"
        "  return (\n"
        "    <section>\n"
        "      <span>plain</span>\n"
        "      <Unknown />\n"
        "      <Mixed />\n"
        "    </section>\n"
        "  );\n"
        "}\n",
    )

    document = JavaScriptParser().parse(path)

    mixed = _by_qualified_name(document)["src.ui.mixed.Mixed"]
    assert mixed.kind == "component"
    # lowercase host tag, unresolved import, and the self-reference all skipped.
    assert mixed.renders == []


def test_hook_and_prop_names_land_in_embed_text(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/ui/form.tsx",
        'import { useAuth } from "../hooks/auth";\n'
        "export function LoginForm({ onSubmit, redirectTo }) {\n"
        "  const [value, setValue] = useState('');\n"
        "  useEffect(() => {}, []);\n"
        "  const session = useAuth();\n"
        "  return <form onSubmit={onSubmit}>{redirectTo}</form>;\n"
        "}\n",
    )

    document = JavaScriptParser().parse(path)

    form = _by_qualified_name(document)["src.ui.form.LoginForm"]
    assert form.kind == "component"
    assert "Props: onSubmit, redirectTo" in form.embed_text
    assert "Hooks: useState, useEffect, useAuth" in form.embed_text
    assert "Props: onSubmit, redirectTo" in form.signature


def test_props_from_props_member_access(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/ui/badge.jsx",
        "import React from 'react';\n"
        "export const Badge = (props) => <span className={props.color}>{props.label}</span>;\n",
    )

    document = JavaScriptParser().parse(path)

    badge = _by_qualified_name(document)["src.ui.badge.Badge"]
    assert badge.kind == "component"
    assert "Props: color, label" in badge.embed_text


def test_plain_typescript_without_react_is_untouched(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "src/service.ts",
        "export function build() {\n  return { ok: true };\n}\n",
    )

    document = JavaScriptParser().parse(path)

    assert _by_qualified_name(document)["src.service.build"].kind == "function"
