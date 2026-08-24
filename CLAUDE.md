# CLAUDE.md — Project Octopus

> **Priority:** This file is auto-loaded by Claude / Anthropic agents.
> For the full cross-agent policy, see [AGENTS.md](./AGENTS.md).
> All rules there apply here in full. This file adds Claude-specific context.


## Core Rules — Summary for Claude

### Think before coding
- State assumptions explicitly. Ask when unclear. Surface tradeoffs.
- Multiple interpretations? Present them — don’t pick silently.

### Simplicity first
- Minimum code that solves the problem. Nothing speculative.
- No abstractions for single-use code. No unrequested features.
- If you write 200 lines and it could be 50, rewrite it.

### Surgical changes
- Touch only what you must. Match existing style.
- Don’t refactor adjacent code that isn’t broken.
- Remove only the dead code your change created.

### Complete code, no false completion
- Produce **complete, runnable code** — never stubs, TODOs, or `# omitted for brevity`.
- **Never claim completion without verification.**
- If blocked or unverified, say so explicitly and give the exact command to verify.

### Python standards
- Python 3.11+, type hints, Pydantic v2 models for cross-service data.
- Avoid single letter variable name as much as possible 
- `ruff` formatting, `pathlib.Path`, dependency injection, specific exceptions.
- Tests in `tests/` via pytest. Run with `uv run pytest tests/ -v`.

### python code organization

You must strictly follow a "One Class Per File" architecture for this Python project, mirroring Java's package conventions while maintaining Pythonic naming standards. 

Adhere to the following architectural and implementation rules:

1. FILE STRUCTURE:
- Every single class must reside in its own dedicated .py file (module).
- Do not combine multiple primary classes into a single file.

2. NAMING CONVENTIONS:
- Files/Modules: Use lowercase snake_case (e.g., data_processor.py).
- Classes: Use PascalCase (e.g., class DataProcessor:). The filename must match the class name, converted to snake_case.

3. PACKAGE EXPOSURE VIA __INIT__.PY (The Facade Pattern):
- Every package/directory must contain an __init__.py file.
- Inside __init__.py, explicitly import (hoist) the classes from their submodules so they are exposed at the package root level.
- Format: "from .filename import ClassName"
- Define the "__all__" list in __init__.py to explicitly declare the public API of the package.

4. END-USER IMPORT EXPECTATION:
- A user should always be able to import classes directly from the package without referencing the underlying file name.
- Example target syntax: "from my_package import ClassA, ClassB"

5. INTERNAL DEPENDENCIES:
- When classes within the same package depend on each other, use explicit relative imports (e.g., "from .other_file import OtherClass") to avoid circular dependencies.

Apply this design intent to all code generation, refactoring, and directory creation tasks.

---

## Response Format

```
**What changed**
- <file>: <what and why>

**Verification run**
- <command> → <result>

**Remaining issues / risks**
- <list or "None">
```

## Context & Compaction Strategy

Claude Code compacts automatically as the context window fills (near its limit) —
this is a CLI-level mechanism, not something you can invoke yourself. Do not attempt
to run `/compact` as an action; instead, work proactively so compaction never causes
context loss.

### Proactive checkpointing (your responsibility)
Before starting a new major task, and any time you sense a natural breakpoint
(feature complete, switching from design to implementation, etc.), write a
checkpoint to `docs/progress.md` — don't wait for compaction to force it.

Checkpoint format:

[CHECKPOINT]
1. Core Objective: <1-sentence reminder of the overarching goal>
2. Completed Milestones: <bullets of what's implemented and verified>
3. Critical Context: <decisions, configs, variable/module names, architecture
   patterns that must survive>
4. Discarded Paths: <approaches tried and rejected, so they aren't repeated>
5. Next Step: <exactly what comes next>

### Compact Instructions
When compaction runs (automatic or manual), always preserve:
- The contents of docs/progress.md verbatim
- The full list of files modified in this session
- Any test/verification commands run and their results
- Open questions or blockers not yet resolved

### If you suspect context is degrading
Signs: repeating questions, contradicting earlier decisions, losing track of file
state. When this happens, write a checkpoint to docs/progress.md immediately and
tell the user: "Context may be degrading — consider running `/compact` or `/clear`
and reloading docs/progress.md."
