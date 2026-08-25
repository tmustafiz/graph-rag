from pathlib import Path

from graph_rag.ingest.parsers.python_parser import PythonParser


def _write_package(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    return pkg


def test_module_qualified_name_uses_init_py_ancestry(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    sub = pkg / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    module_path = sub / "mod.py"
    module_path.write_text("")
    assert PythonParser._module_qualified_name(module_path) == "pkg.sub.mod"


def test_module_qualified_name_for_init_py_is_package_name(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    assert PythonParser._module_qualified_name(pkg / "__init__.py") == "pkg"


def test_module_qualified_name_stops_at_directory_without_init(tmp_path: Path) -> None:
    module_path = tmp_path / "standalone.py"
    module_path.write_text("")
    assert PythonParser._module_qualified_name(module_path) == "standalone"


def test_parses_function_signature_and_docstring(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    path = pkg / "funcs.py"
    path.write_text(
        'def greet(name: str, times: int = 1) -> str:\n    """Say hello."""\n    return name\n'
    )

    document = PythonParser().parse(path)

    func = next(e for e in document.code_entities if e.qualified_name == "pkg.funcs.greet")
    assert func.kind == "function"
    assert func.signature == "(name: str, times: int=1) -> str"
    assert func.docstring == "Say hello."
    assert func.embed_text == "Say hello."


def test_fallback_embed_text_when_no_docstring(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    path = pkg / "funcs.py"
    path.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

    document = PythonParser().parse(path)

    func = next(e for e in document.code_entities if e.qualified_name == "pkg.funcs.add")
    assert func.docstring is None
    assert func.embed_text == "function add(a: int, b: int) -> int: return a + b"


def test_class_with_methods_produces_contains_hierarchy(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    path = pkg / "widgets.py"
    path.write_text(
        "class Widget:\n"
        '    """A widget."""\n\n'
        "    def render(self) -> str:\n"
        '        """Render it."""\n'
        '        return "ok"\n'
    )

    document = PythonParser().parse(path)

    by_qualified_name = {e.qualified_name: e for e in document.code_entities}
    assert by_qualified_name["pkg.widgets.Widget"].kind == "class"
    assert by_qualified_name["pkg.widgets.Widget"].docstring == "A widget."
    method = by_qualified_name["pkg.widgets.Widget.render"]
    assert method.kind == "method"
    assert method.parent_qualified_name == "pkg.widgets.Widget"


def test_self_call_resolves_to_sibling_method(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    path = pkg / "widgets.py"
    path.write_text(
        "class Widget:\n"
        "    def render(self) -> str:\n"
        "        return self.label()\n\n"
        "    def label(self) -> str:\n"
        '        return "x"\n'
    )

    document = PythonParser().parse(path)

    render = next(
        e for e in document.code_entities if e.qualified_name == "pkg.widgets.Widget.render"
    )
    assert render.calls == ["pkg.widgets.Widget.label"]


def test_local_function_call_resolves_within_module(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    path = pkg / "funcs.py"
    path.write_text("def helper() -> None:\n    pass\n\n\ndef main() -> None:\n    helper()\n")

    document = PythonParser().parse(path)

    main = next(e for e in document.code_entities if e.qualified_name == "pkg.funcs.main")
    assert main.calls == ["pkg.funcs.helper"]


def test_from_import_call_resolves_to_imported_qualified_name(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    path = pkg / "consumer.py"
    path.write_text("from other_pkg.util import do_thing\n\n\ndef run() -> None:\n    do_thing()\n")

    document = PythonParser().parse(path)

    module_entity = next(e for e in document.code_entities if e.qualified_name == "pkg.consumer")
    assert "other_pkg.util.do_thing" in module_entity.imports
    run = next(e for e in document.code_entities if e.qualified_name == "pkg.consumer.run")
    assert run.calls == ["other_pkg.util.do_thing"]


def test_module_alias_call_resolves_via_import_as(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    path = pkg / "consumer.py"
    path.write_text("import json as j\n\n\ndef dump() -> None:\n    j.dumps({})\n")

    document = PythonParser().parse(path)

    dump = next(e for e in document.code_entities if e.qualified_name == "pkg.consumer.dump")
    assert dump.calls == ["json.dumps"]


def test_relative_import_resolves_using_package_ancestry(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    sub = pkg / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    (sub / "helpers.py").write_text("def helper() -> None:\n    pass\n")
    consumer_path = sub / "consumer.py"
    consumer_path.write_text("from .helpers import helper\n\n\ndef run() -> None:\n    helper()\n")

    document = PythonParser().parse(consumer_path)

    module_entity = next(
        e for e in document.code_entities if e.qualified_name == "pkg.sub.consumer"
    )
    assert "pkg.sub.helpers.helper" in module_entity.imports
    run = next(e for e in document.code_entities if e.qualified_name == "pkg.sub.consumer.run")
    assert run.calls == ["pkg.sub.helpers.helper"]


def test_module_with_no_docstring_summarizes_its_exports(tmp_path: Path) -> None:
    pkg = _write_package(tmp_path)
    path = pkg / "funcs.py"
    path.write_text("def helper() -> None:\n    pass\n")

    document = PythonParser().parse(path)

    module_entity = next(e for e in document.code_entities if e.qualified_name == "pkg.funcs")
    assert module_entity.kind == "module"
    assert module_entity.docstring is None
    assert module_entity.embed_text == "Module pkg.funcs. Defines: helper"
