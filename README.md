# claude-handoff

Compact handoff briefs for Claude Code sessions.

## Flow

In a fresh session, type:

```
/handoff <session-id-prefix>          # direct ID/prefix lookup
/handoff "<any keywords>"             # fuzzy search, requires claude-history
```

The skill locates the matching `~/.claude/projects/*/<id>.jsonl`, parses it with a stdlib-only Python script (zero LLM calls, zero API cost), and prints a structured Markdown brief. You read the brief and continue the work in the new session.

## The numbers

Measured on a real 1.1 MB / 686-line session:

| | Tokens |
|---|---:|
| Raw JSONL into context (what most session-loader tools do) | ~298,000 |
| handoff brief | ~970 |
| **Ratio** | **1 / 307** |

Deterministic parser — no LLM summarization at runtime. Output is stable run-to-run.

## Comparison

Why compare: the Claude Code ecosystem has 15+ session-handoff / session-loader projects, and most fall into one of three patterns — (a) instruct the **active** session to write a brief from its own in-memory context (regenerating what the dying session already has), (b) `cat` the raw JSONL and let the new session's model parse 300K tokens from scratch, or (c) hook on `SessionEnd`, summarize via a small model, auto-load on `SessionStart`. `claude-handoff` belongs to a fourth category: deterministic parser, on demand, zero LLM at runtime.

Surveyed alternatives:

| Project | Approach | Runtime LLM | Brief size (1.1 MB session) | Triggered |
|---|---|---|---|---|
| **claude-handoff (this)** | Deterministic Python parser | None | **~970 tok** | On demand |
| [ccdiag](https://github.com/kolkov/ccdiag) | Deterministic Go parser (this project's reference) | None | ~970 tok | On demand |
| [AccidentalRebel/claude-skill-session-retrospective](https://github.com/accidentalrebel/claude-skill-session-retrospective) | `cat` raw JSONL → in-session model parses | current session | ~298,000 tok (raw) | On demand |
| [REMvisual/claude-handoff](https://github.com/REMvisual/claude-handoff) | Active session writes brief from in-memory context | current session | varies | Mid-session |
| [thepushkarp/handoff](https://github.com/thepushkarp/handoff) | Stop-hook forces active session to fill brief sections | current session | varies | Pre-compact |
| [Digital-Process-Tools/claude-remember](https://github.com/Digital-Process-Tools/claude-remember) | Haiku summarizes JSONL on SessionEnd, auto-loads on next start | Haiku | ~150–500 tok layered | SessionEnd hook |
| [Vvkmnn/claude-historian-mcp](https://github.com/Vvkmnn/claude-historian-mcp) | MCP server; `inspect(session_id)` returns pre-shaped summary | None | structured per query | On demand (per query) |
| [jhammant/ClaudeHistoryMCP](https://github.com/jhammant/ClaudeHistoryMCP) | MCP server; BM25 + TF-IDF cross-session search | None | structured per query | On demand (per query) |

Approaches (a) and (b) re-pay (in current-model tokens) for context the source session already has on disk. Approach (c) is fine for continuous background memory but doesn't help when you want to start a new session **right now** from one specific old one. The two MCP servers are great when you don't know which session you want and need to search across history; they don't replace a focused brief.

`claude-handoff` is the on-demand, deterministic path: you supply an ID or keyword, you get a brief, you're moving in seconds.

## Brief contents

Header (file / period / model / version) · stats table · files modified · open todos (from last `TodoWrite`) · approved plans · last `result:` line · token usage with cache hit ratio · GitHub issues · URLs · last 20 real user messages (line-anchored, harness noise filtered).

## Install

```bash
cp -r skill ~/.claude/skills/handoff
```

Restart Claude Code. Python 3.8+, stdlib only. Optional: `cargo install claude-history` for the keyword search path.

## Credits

Brief format reimplemented from [ccdiag](https://github.com/kolkov/ccdiag) `--output handoff` mode.

## License

MIT — see [LICENSE](LICENSE).
