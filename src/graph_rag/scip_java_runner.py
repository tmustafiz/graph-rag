import logging
import shlex
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_BUILD_TOOLS = ("auto", "gradle", "maven", "sbt", "mill", "bazel")


class ScipJavaRunner:
    """Thin wrapper around the external `scip-java` binary
    (https://github.com/sourcegraph/scip-java) — graph-rag does **not** vendor
    or bundle it.

    `scip-java index` runs the project's build with an instrumented compiler and
    writes a `.scip` index; this class builds the argv and shells out to it in
    the repo directory. The produced index is then fed to `grag-mcp ingest
    --scip` by the CLI command.
    """

    BINARY = "scip-java"

    @classmethod
    def build_command(
        cls,
        output: Path,
        *,
        build_tool: str | None = None,
        build_command: str | None = None,
    ) -> list[str]:
        """The `scip-java` argv (no repo path — it runs in the repo `cwd`).

        `build_command` is the project build invocation passed after `--`
        (`"clean verify -DskipTests"`); `build_tool` pins detection
        (`gradle` / `maven` / …), otherwise `scip-java` auto-detects.
        """
        argv = [cls.BINARY, "index", "--output", str(output)]
        if build_tool and build_tool != "auto":
            if build_tool not in _BUILD_TOOLS:
                raise ValueError(f"unknown --build-tool {build_tool!r}; pick one of {_BUILD_TOOLS}")
            argv += ["--build-tool", build_tool]
        if build_command:
            argv += ["--", *shlex.split(build_command)]
        return argv

    @classmethod
    def run(
        cls,
        repo: Path,
        output: Path,
        *,
        build_tool: str | None = None,
        build_command: str | None = None,
    ) -> Path:
        if shutil.which(cls.BINARY) is None:
            raise RuntimeError(
                f"`{cls.BINARY}` not found on PATH. Install it — see "
                "https://sourcegraph.github.io/scip-java/docs/getting-started.html — "
                "or run `scip-java index` yourself and pass the result to "
                "`grag-mcp ingest --scip`."
            )
        argv = cls.build_command(output, build_tool=build_tool, build_command=build_command)
        logger.info("running %s in %s", " ".join(argv), repo)
        completed = subprocess.run(argv, cwd=repo, check=False)  # noqa: S603
        if completed.returncode != 0:
            raise RuntimeError(f"`{cls.BINARY} index` failed (exit {completed.returncode})")
        index_path = output if output.is_absolute() else repo / output
        if not index_path.exists():
            raise RuntimeError(f"{cls.BINARY} reported success but {index_path} is missing")
        return index_path
