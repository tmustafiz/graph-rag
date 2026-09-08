"""`ScipJavaRunner.build_command` — argv construction only (the external
`scip-java` call is not exercised).
"""

from pathlib import Path

import pytest

from graph_rag.scip_java_runner import ScipJavaRunner


def test_default_command_is_scip_java_index_with_output() -> None:
    assert ScipJavaRunner.build_command(Path("index.scip")) == [
        "scip-java",
        "index",
        "--output",
        "index.scip",
    ]


def test_build_tool_is_passed_through_when_not_auto() -> None:
    assert ScipJavaRunner.build_command(Path("out.scip"), build_tool="gradle") == [
        "scip-java",
        "index",
        "--output",
        "out.scip",
        "--build-tool",
        "gradle",
    ]
    # "auto" is the scip-java default — don't pass the flag
    assert "--build-tool" not in ScipJavaRunner.build_command(Path("x"), build_tool="auto")


def test_build_command_is_split_and_appended_after_double_dash() -> None:
    argv = ScipJavaRunner.build_command(
        Path("index.scip"), build_command="clean verify -DskipTests"
    )
    assert argv[-4:] == ["--", "clean", "verify", "-DskipTests"]


def test_unknown_build_tool_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown --build-tool"):
        ScipJavaRunner.build_command(Path("x"), build_tool="ant")
