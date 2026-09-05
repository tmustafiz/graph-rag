---
name: agent-memory
description: Save and retrieve this project's persistent working memory (decisions, corrections, findings, preferences, facts) using the graph-rag memory MCP server's remember/recall/forget tools. Use at the start of a task to recall relevant prior context, and proactively whenever you learn or decide something worth keeping across sessions — don't wait to be asked.
---

Copy this directory into a downstream project's `.claude/skills/` to give
Claude the same memory habits this repo's own auto-memory system prompt
describes, backed by graph-rag's `remember`/`recall`/`forget` MCP tools
instead of local files. Requires an MCP client already connected to a
graph-rag memory server — see `../../../README.md` for setup.

## When to recall

At the start of a task, call `recall(query=<description of the task>)`. Phrase
`query` as what you're about to do, not a keyword — it's a semantic search.
Use the optional `about_qualified_name` filter when the task centers on one
specific function/class/module.

## When to remember

Save memories as you learn things, not as an end-of-session summary. Call
`remember(content, kind, ...)` for:

- **`decision`** — a choice you made and why (architecture, library, approach
  chosen over alternatives).
- **`correction`** — the user corrected your approach. Record what was wrong
  and why, so you don't repeat it. This is the single most valuable kind —
  watch for it even when the user doesn't frame it as a correction explicitly
  ("no, don't do X", "actually use Y instead").
- **`finding`** — something learned about the codebase that isn't obvious
  from reading it: a gotcha, a non-obvious invariant, a root cause you had to
  dig for.
- **`preference`** — a standing preference about how to work in this project,
  confirmed by the user (explicitly, or by accepting an unusual choice
  without pushback).
- **`fact`** — project state that will go stale on its own (a deadline, an
  owner, a decision pending elsewhere) — convert relative dates ("Thursday")
  to absolute ones before saving.

Set `importance=True` only for something that must never be pruned by decay
even if never recalled again (a standing constraint) — not for routine
findings, which should decay naturally if they stop being relevant.

Tag with `about_qualified_name=<dotted.path.to.Entity>` when the memory is
about one specific code entity.

## When to forget

Call `forget(memory_id)` immediately if a memory turns out to be wrong or
superseded — don't leave it for decay-based pruning to eventually clean up.

## What not to save

Anything derivable from reading the code, git history, or this project's own
`AGENTS.md`/`CLAUDE.md`; ephemeral in-progress task state; anything that
belongs in a commit message or PR description instead. If a memory only
restates what a `recall` result already said, don't re-save it.
