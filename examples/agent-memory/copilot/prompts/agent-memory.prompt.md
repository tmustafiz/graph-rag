---
mode: agent
description: Recall relevant graph-rag memories for the current task, then work with an eye toward saving what's worth keeping.
---
Use the graph-rag memory MCP server's `recall`/`remember`/`forget` tools
(registered in this workspace's MCP config) as persistent working memory
across sessions.

1. Call `recall(query=${input:task:describe the task you're about to do})` —
   `query` is a semantic search, so phrase it as a description, not a
   keyword. Read the results before starting.
2. Do the task.
3. Before finishing, call `remember(content, kind)` for anything worth
   keeping that you learned or decided along the way. `kind` is one of:
   - `decision` — a choice made and why.
   - `correction` — you were corrected on your approach; record what and why.
   - `finding` — something non-obvious learned about the codebase.
   - `preference` — a standing preference confirmed by the user.
   - `fact` — project state that will go stale (convert relative dates to
     absolute ones first).
   Set `importance=True` only for a standing constraint that must never be
   pruned by decay. Don't save anything already derivable from the code or
   git history.
4. If a recalled memory turns out to be wrong or superseded, call
   `forget(memory_id)` immediately rather than leaving it for decay-based
   pruning.

This is a manual complement to a `SessionStart` hook and/or
`.github/copilot-instructions.md`/`AGENTS.md` guidance (see
`../../README.md`) — those cover recall happening automatically or Copilot
deciding on its own to use these tools; running `/agent-memory` explicitly
covers the case where you want a recall/remember pass on demand.
