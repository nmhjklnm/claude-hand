---
name: hand
description: Generate a structured brief from an old Claude Code session's JSONL so the user can paste it into a NEW session to pick up the work. Use when user types /hand <session-id-or-keywords> or asks to summarize an old session to resume in a fresh conversation. Output goes to chat (not written to disk). Distinct from the claude-remember SessionStart hook which writes ".remember/remember.md" — do not conflate.
---

# /hand — Session brief from old conversation

Generate a compact Markdown brief from a prior Claude Code session JSONL so the user can continue the work in a fresh session without rereading the entire conversation.

**Output destination:** chat (for the user to paste into a new session). Do NOT write the brief to `.remember/remember.md` or any other file — that path belongs to the separate claude-remember SessionStart hook, which is unrelated to this skill.

## Invocation

The user supplies one of:
- A session UUID, UUID prefix (e.g. `abc03363`), or absolute path to a `.jsonl` → **ID path**.
- A keyword / phrase (e.g. `"skill review session"`) → **search path**.

### Argument shape detection

Treat the argument as an ID if it matches `^[0-9a-f]{4,32}(-[0-9a-f-]+)?$` OR ends in `.jsonl`. Otherwise treat it as a keyword query.

## ID path

Run the helper and stream stdout verbatim:

```bash
python3 ~/.claude/skills/hand/hand.py <session-id-or-prefix>
```

Always quote the argument. Capture both stdout and stderr.

- Exit 0: stdout is the Markdown brief. Present it as-is — that IS the brief. Do not rewrite or summarize.
- Exit 1: no JSONL matched. Show stderr; ask for a more specific id.
- Exit 2: prefix matched multiple files. Stderr lists candidates with project dir + mtime. Ask user to pick one.

## Search path (keyword query)

1. **Check tool**: run `command -v claude-history`. If missing, tell the user:
   > `claude-history` is not installed. Install via `cargo install claude-history`, or download a release binary from https://github.com/raine/claude-history/releases and put it on PATH.
   Then stop.

2. **Search**. Pass the user's query verbatim as a single argument:

   ```bash
   claude-history --debug-search "<query>" 2>&1
   ```

   Output begins with `intent:` / `literals:` lines, then ranked results, one per block. Each result header has the exact shape:

   ```
   # N score=S freshness=F | <project-label> | <UUID> | <Nh ago>
   ```

   Parse the lines starting with `# ` (regex: `^#\s+\d+\s+score=\S+\s+freshness=\S+\s+\|\s+(?P<proj>[^|]+?)\s+\|\s+(?P<uuid>[0-9a-f-]{36})\s+\|\s+(?P<age>[^|]+?)\s*$`). Take the **top 5** by listed order (already ranked).

3. **Enrich each candidate** with the first real user message. For each UUID, find its JSONL via `ls ~/.claude/projects/*/<uuid>.jsonl` (there will be exactly one) and run:

   ```python
   import json
   for line in open(path):
       d = json.loads(line)
       if d.get("type") != "user": continue
       msg = d.get("message", {})
       c = msg.get("content", "")
       txt = c if isinstance(c, str) else next(
           (it.get("text","") for it in c if isinstance(it, dict) and it.get("type")=="text"), "")
       if not txt: continue
       if txt.startswith("<task-notification") or "<system-reminder" in txt[:60]: continue
       print(d.get("timestamp","")[:19], "|", d.get("cwd",""))
       print(txt[:160].replace("\n"," "))
       break
   ```

   That yields date + cwd + a 160-char snippet of the first real user prompt.

4. **Present as numbered list** (max 5). Format each entry:

   ```
   1. <UUID-prefix-8>  <age>  <project-label>
      <date>  <cwd>
      "<snippet>"
   ```

   Then ask: *"Which one? Pick a number or paste a UUID prefix."*

5. **On user pick**: extract that candidate's UUID (full or 8-char prefix) and run the **ID path** above: `python3 ~/.claude/skills/hand/hand.py <uuid>`.

## What the brief contains

Header (file, period, model, version), stats table, files modified, GitHub issues referenced, URLs referenced, and the last 20 real user messages with line-number anchors. Harness noise (`<task-notification>` / `<system-reminder>` wrapped messages) is filtered out.

## Intent

The brief is meant to be loaded as context at the START of a new session so the assistant can pick up where the previous one left off. After presenting it, ask the user what they want to do next.
