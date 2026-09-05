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

Register it with your agent, e.g. for Claude Code:

```bash
claude mcp add graph-rag-memory --transport http http://127.0.0.1:8766/mcp
```

## What's here

| File | What it does |
| --- | --- |
| [`AGENTS.md.example`](AGENTS.md.example) | A snippet to paste into your project's `AGENTS.md` (or `CLAUDE.md`, `.github/copilot-instructions.md`, `.cursor/rules`, ...) telling any agent that reads it when to call `remember`/`recall`/`forget`. |
| [`skills/agent-memory/`](skills/agent-memory/SKILL.md) | The same guidance as a Claude Code [skill](https://docs.claude.com/en/docs/claude-code/skills) — copy the directory into your project's `.claude/skills/`. Claude invokes it proactively based on its description, without the user typing a slash command. |
| [`hooks/session_start_recall.py`](hooks/session_start_recall.py) | A Claude Code `SessionStart` hook: calls `recall` against the memory server and prints the results, which Claude Code injects as context at the start of every session — so relevant memories show up automatically, not just when the agent thinks to ask. |
| [`hooks/settings.snippet.json`](hooks/settings.snippet.json) | Example `.claude/settings.json` wiring for the hook above. |

The `AGENTS.md.example` snippet and the skill cover the same ground — use
whichever your agent supports (or both; they don't conflict). The hook is
additive on top of either: it doesn't replace the agent calling `recall`
itself mid-task, it just guarantees *something* relevant surfaces at session
start even if the agent doesn't think to ask.

There's deliberately no hook that calls `remember` automatically. Deciding
what's worth remembering needs judgment about what just happened in the
conversation, which a hook triggered on a fixed event (session end, before
compaction, ...) doesn't have — that stays a tool call the agent makes on its
own, guided by the skill/`AGENTS.md` instructions above.

## Using the recall hook

```bash
cp examples/agent-memory/hooks/session_start_recall.py ~/somewhere/on/PATH/
uv pip install mcp   # or: pip install mcp — whatever interprets the script
```

Edit `hooks/settings.snippet.json`'s command to the script's actual path and
merge it into your project's (or `~/.claude/`'s) `settings.json`. Configuration
is via environment variables — see the script's module docstring for all of
them:

```bash
GRAG_MEMORY_MCP_URL=http://127.0.0.1:8766/mcp   # or :8765 for the combined stack
MCP_AUTH_TOKEN=...                              # only if the server requires one
GRAG_MEMORY_RECALL_QUERY="..."                  # defaults to the cwd's basename
GRAG_MEMORY_RECALL_TOP_K=5
```

Verify it directly before wiring it into a hook:

```bash
echo '{"cwd":"'"$PWD"'"}' | python3 examples/agent-memory/hooks/session_start_recall.py
```

It never fails the session — a recall error or an unreachable server prints a
warning to stderr and exits `0` with no context injected.
