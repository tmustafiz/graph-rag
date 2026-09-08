# Enterprise Java with graph-rag

graph-rag models a Java codebase two ways, and you can mix them per file:

| Tier | How | Resolves | Setup |
| --- | --- | --- | --- |
| **static** (default) | tree-sitter, `grag-mcp ingest <dir>` | in-file calls, explicit imports, `this`/`super` members, framework wiring (Spring beans / MVC / Data / Camel / events / AOP / MyBatis / Feign) — best-effort, skips what needs type inference | none — `grag-mcp[java]` extra |
| **SCIP** (optional) | `scip-java` → `grag-mcp ingest --scip` | compiler-grade `CALLS` / `IMPORTS` / `IMPLEMENTS` across files and modules, overload-correct targets, library symbols | a working build + the `scip-java` binary |

Static parsing is always the zero-config path. Reach for SCIP when you need an
accurate cross-file/cross-module call graph, overload-correct call targets, or
dependency navigation — e.g. "what actually calls `OrderService.submit(Order)`
(not the `submit(String)` overload)", "everything that transitively depends on
this module".

## Producing a SCIP index

`scip-java` (https://github.com/sourcegraph/scip-java) runs your build with an
instrumented compiler and emits `index.scip`.

```bash
# auto-detects Gradle / Maven
scip-java index

# explicit build command (the escape hatch)
scip-java index -- clean verify -DskipTests

# include dependency + JDK symbols so library calls resolve
scip-java index --build-tool gradle
```

Output is `index.scip` in the working directory by default.

## Ingesting it

```bash
# from the repo root, so the index's relative paths line up with a prior
# static ingest of the same tree
grag-mcp ingest --scip index.scip

# or point at the repo root explicitly
grag-mcp ingest --scip /path/to/index.scip --root /path/to/repo
```

SCIP-derived entities **replace** the static ones for every file the index
covers (`CodeEntity.resolution` records which pass produced the current set).
Ingest static first for the framework graph (Spring / Camel / …), then
`--scip` on top for the precise call graph.

> The `scip-java` binary is an external tool — graph-rag does not vendor or
> invoke it. A CI recipe and a `grag-mcp scip-java` wrapper are tracked in
> [#80](https://github.com/tmustafiz/graph-rag/issues/80).
