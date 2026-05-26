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
