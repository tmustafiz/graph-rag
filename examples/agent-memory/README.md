# agent-memory

Templates for wiring a coding agent up to graph-rag's `remember` / `recall` /
`forget` tools as its own persistent working memory — in a **downstream**
project, not this repo. Copy whichever pieces you need.

## Prerequisites

A running graph-rag memory MCP server, reachable from wherever your agent
runs:

- **Standalone** (recommended if the agent doesn't need the knowledge-base
  tools too): `docker compose -f docker-compose.memory.yml up -d` from this
  repo, exposing `http://127.0.0.1:8766/mcp`. See
  [docs/operations.md](../../docs/operations.md#split-deployment-optional).
- **Combined**: the default `docker compose up -d` (`--role all`), exposing
  the same tools on `http://127.0.0.1:8765/mcp` alongside search/ingest.

Run `grag-mcp apply-schema` against it once (see the same doc) before
`remember`/`recall` will work.

Register the server with your agent:

```bash
# Claude Code
claude mcp add graph-rag-memory --transport http http://127.0.0.1:8766/mcp
```

```jsonc
// VS Code: .vscode/mcp.json
{ "servers": { "graph-rag-memory": { "type": "http", "url": "http://127.0.0.1:8766/mcp" } } }
```

## What's here

Both agents get the same three layers — an always-on instructions file, an
explicit/proactive prompt for a deliberate recall+remember pass, and a hook
that recalls automatically at session start:

| Layer | Claude Code | VS Code Copilot Chat |
| --- | --- | --- |
| Always-on instructions | [`AGENTS.md.example`](AGENTS.md.example) → project `AGENTS.md` | Same file — VS Code discovers a root `AGENTS.md` automatically — or [`copilot/copilot-instructions.md.example`](copilot/copilot-instructions.md.example) → `.github/copilot-instructions.md` |
| Explicit/proactive prompt | [`skills/agent-memory/SKILL.md`](skills/agent-memory/SKILL.md) → `.claude/skills/agent-memory/` (Claude invokes it proactively based on its description) | [`copilot/prompts/agent-memory.prompt.md`](copilot/prompts/agent-memory.prompt.md) → `.github/prompts/` (run explicitly via `/agent-memory` in Copilot Chat) |
| Automatic recall at session start | [`hooks/session_start_recall.py`](hooks/session_start_recall.py) + [`hooks/settings.snippet.json`](hooks/settings.snippet.json) → `.claude/settings.json` | [`copilot/hooks/session_start_recall.py`](copilot/hooks/session_start_recall.py) + [`copilot/hooks/agent-memory.hooks.json`](copilot/hooks/agent-memory.hooks.json) → `.github/hooks/` |

The always-on file and the prompt/skill cover the same ground — use whichever
your agent supports (or both; they don't conflict). The hook is additive on
top of either: it doesn't replace the agent calling `recall` itself mid-task,
it just guarantees *something* relevant surfaces at session start even if the
agent doesn't think to ask.

There's deliberately no hook that calls `remember` automatically. Deciding
what's worth remembering needs judgment about what just happened in the
conversation, which a hook triggered on a fixed event (session end, before
compaction, ...) doesn't have — that stays a tool call the agent makes on its
own, guided by the instructions/prompt above.

> **Copilot hooks are a Preview VS Code feature** — [VS Code's own docs](https://code.visualstudio.com/docs/agent-customization/hooks)
> say the config format and behavior might still change. If `copilot/hooks/`
> stops working, the instructions file and prompt file above cover the same
> ground without depending on it.

## Using a recall hook

Both hook scripts share the same shape and env vars; only the stdout format
and config file location differ (plain text for Claude, a JSON envelope for
Copilot).

```bash
# pick one, or both
cp examples/agent-memory/hooks/session_start_recall.py ~/somewhere/on/PATH/          # Claude Code
cp examples/agent-memory/copilot/hooks/session_start_recall.py ~/somewhere/on/PATH/  # Copilot
uv pip install mcp   # or: pip install mcp — whatever interprets the script(s)
```

Edit the matching config's command to the script's actual path and merge it
into your project's config (`.claude/settings.json`, or `.github/hooks/` for
Copilot). Configuration is via environment variables — see either script's
module docstring:

```bash
GRAG_MEMORY_MCP_URL=http://127.0.0.1:8766/mcp   # or :8765 for the combined stack
MCP_AUTH_TOKEN=...                              # only if the server requires one
GRAG_MEMORY_RECALL_QUERY="..."                  # defaults to the cwd's basename
GRAG_MEMORY_RECALL_TOP_K=5
```

Verify a script directly before wiring it into a hook:

```bash
echo '{"cwd":"'"$PWD"'"}' | python3 examples/agent-memory/hooks/session_start_recall.py            # Claude
echo '{"cwd":"'"$PWD"'"}' | python3 examples/agent-memory/copilot/hooks/session_start_recall.py    # Copilot
```

Neither ever fails the session — a recall error or an unreachable server
prints a warning to stderr and exits `0` with no context injected.

## Sources for the Copilot hooks contract

`copilot/hooks/` is written against VS Code's official (Preview) reference:

- [Agent hooks in VS Code](https://code.visualstudio.com/docs/agent-customization/hooks) — config file locations, JSON schema, event list, exit-code semantics
- [Hooks reference](https://code.visualstudio.com/docs/agents/reference/hooks-reference) — per-event input/output schemas, including `SessionStart`'s `source` input field and `hookSpecificOutput.additionalContext` output shape
