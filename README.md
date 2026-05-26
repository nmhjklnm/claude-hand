# claude-handoff

A Claude Code skill that turns any past session JSONL into a compact handoff brief — about 1K tokens instead of the ~300K you'd burn `cat`-ing a long session.

## Why

Long Claude Code sessions get expensive: prompt caches expire, every continuation re-reads the full transcript, and `/resume` brings the whole conversation back into context. For most multi-day workflows it is cheaper and faster to start a fresh session and load a short structured brief of the prior session. `claude-handoff` produces that brief from the session's JSONL, with line-number anchors so the new session can drill back into specifics if needed.

## What the brief contains

- Header: session ID, file path, period, model, version
- Stats: JSONL line count, user / assistant / tool-use counts, files written / edited, bash / GitHub / web counts
- Files Modified table (writes, edits, first-touch line)
- Open Todos (from the most recent `TodoWrite`)
- Approved Plans (from `ExitPlanMode`, associated with any plan-doc Write that follows)
- Last Completed (the most recent assistant `result:` line)
- Usage table with cache hit ratio
- GitHub Issues referenced + Git / GitHub / Web command logs
- URLs referenced
- Last 20 real user messages, with line-number anchors (harness noise like `<task-notification>` / `<system-reminder>` wrappers is filtered out)

You invoke it with a UUID, UUID prefix, or — if you have [`claude-history`](https://github.com/raine/claude-history) installed — a keyword phrase.

## Install

```bash
cp -r skill ~/.claude/skills/handoff
```

Then restart Claude Code. The skill registers as `/handoff` and runs the bundled `handoff.py` (Python 3.8+, stdlib only — no dependencies).

## Usage

By UUID or prefix (matches any `.jsonl` under `~/.claude/projects/*/`):

```
/handoff a1b2c3d4
```

By keyword phrase (requires [`claude-history`](https://github.com/raine/claude-history) on `PATH`):

```
/handoff "auth refactor"
```

The keyword flow lists the top 5 matching sessions with date, cwd, and a snippet of the first user prompt, then asks you to pick one before generating the brief.

### Installing claude-history (optional, for keyword search)

```bash
cargo install claude-history
```

Or grab a release binary from <https://github.com/raine/claude-history/releases>.

## Example output

```markdown
# Session Recovery — a1b2c3d4-5e6f-7890-abcd-ef1234567890

> **File**: `~/.claude/projects/-Users-you-projects/a1b2c3d4-...jsonl`
> **Period**: 2026-01-15 09:12 → 2026-01-15 14:48 (5h36m)
> **Model**: claude-opus-4-7 | **Version**: 2.0.41

## Stats

| Metric | Count |
|--------|-------|
| JSONL lines | 1284 |
| User messages | 47 |
| Tool uses | 312 |
| Files edited | 18 |

## Files Modified

| File | Writes | Edits | First Line |
|------|--------|-------|------------|
| `~/proj/src/auth.py` | 1 | 6 | L84 |
| `~/proj/tests/test_auth.py` | 1 | 3 | L201 |

## Open Todos

(from last TodoWrite at L1102)

- [→] Wire refresh-token rotation into middleware  (in_progress)
- [ ] Add integration test for expired-token path  (pending)

## Last 20 User Messages

- **L42**: refactor the auth module so token refresh happens lazily
- **L188**: tests are flaky on CI — look at the fixture setup
...
```

## Credits

The brief format is reimplemented from [ccdiag](https://github.com/kolkov/ccdiag)'s `--output handoff` mode, condensed into a single stdlib-only Python script and extended to filter harness-noise wrappers out of the user-message history.

## License

MIT — see [LICENSE](LICENSE).
