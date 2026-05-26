#!/usr/bin/env python3
"""Generate a handoff brief from a Claude Code session JSONL.

Reimplements ccdiag's `--output handoff` mode in a single stdlib-only script.
Improvement over ccdiag: filters <task-notification> / <system-reminder>
messages out of the "Last N User Messages" section and backfills from
earlier real messages.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

LAST_N = 20
SKIP_TYPES = {
    "file-history-snapshot",
    "queue-operation",
    "progress",
    "system",
    "last-prompt",
    "permission-mode",
}

# ---------- session lookup ----------

def resolve_session(arg: str) -> Path:
    home = Path.home()
    pattern = str(home / ".claude" / "projects" / "*" / f"{arg}*.jsonl")
    matches = [Path(p) for p in glob.glob(pattern)]
    if not matches:
        # Also try as exact full path
        p = Path(arg)
        if p.is_file():
            return p
        print(f"error: no JSONL found matching prefix '{arg}' under ~/.claude/projects/*/", file=sys.stderr)
        sys.exit(1)
    if len(matches) == 1:
        return matches[0]
    print(f"error: prefix '{arg}' matched {len(matches)} files; please disambiguate:", file=sys.stderr)
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in matches:
        mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"  {p}  (mtime {mt} UTC, project {p.parent.name})", file=sys.stderr)
    sys.exit(2)

# ---------- JSONL parsing ----------

def parse_ts(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None

def content_blocks(content) -> list[dict]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []

def block_text(blocks: list[dict]) -> str:
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text" and b.get("text"))

def input_str(inp, key: str) -> str:
    if isinstance(inp, dict):
        v = inp.get(key)
        return v if isinstance(v, str) else ""
    return ""

URL_RE = re.compile(r"https?://[^\s\"'`)\]>|]+")
# ccdiag parity: full digit run must be 3-6 chars (so #29081008 is rejected, not truncated)
ISSUE_RE = re.compile(r"#(\d+)")

def extract_urls(text: str, urlset: set[str]):
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:!?")
        if len(url) > 15:
            urlset.add(url)

def extract_issues(text: str, line: int, issues: dict):
    for m in ISSUE_RE.finditer(text):
        num = m.group(1)
        if not (3 <= len(num) <= 6):
            continue
        ref = issues.setdefault(num, {"commented": False, "created": False, "lines": []})
        if not ref["lines"] or ref["lines"][-1] != line:
            ref["lines"].append(line)

def classify_gh(cmd: str) -> str:
    if "gh issue create" in cmd: return "issue-create"
    if "gh issue comment" in cmd: return "issue-comment"
    if "gh pr create" in cmd: return "pr-create"
    if "gh pr comment" in cmd: return "pr-comment"
    if "gh api" in cmd: return "api"
    return "other"

def track_gh_issue(cmd: str, issues: dict, commented: bool, created: bool):
    parts = cmd.split()
    for i, p in enumerate(parts):
        if p in ("comment", "view") and i + 1 < len(parts):
            num = re.sub(r"\D", "", parts[i + 1])
            if num:
                ref = issues.setdefault(num, {"commented": False, "created": False, "lines": []})
                if commented: ref["commented"] = True
                if created: ref["created"] = True

TRIVIAL_PREFIXES = ("ls", "cat ", "head ", "tail ", "echo ", "pwd", "cd ",
                    "wc ", "stat ", "file ", "which ", "mkdir ", "test ")
NOTABLE_PREFIXES = ("go ", "npm ", "node ", "cargo ", "make", "python",
                    "docker ", "kubectl ", "curl ", "wget ", "tar ", "grep ",
                    "find ", "sed ", "awk ", "patch ", "diff ")

def is_notable_bash(cmd: str) -> bool:
    lower = cmd.lower()
    if any(lower.startswith(t) for t in TRIVIAL_PREFIXES):
        return False
    if any(lower.startswith(n) for n in NOTABLE_PREFIXES):
        return True
    return len(cmd) > 20

def recover_session(path: Path) -> dict:
    rs = {
        "session_id": "", "file_path": str(path), "version": "", "model": "",
        "start": None, "end": None,
        "user_msgs": [], "files": [],
        "gh_actions": [], "git_cmds": [], "bash_cmds": [], "web": [],
        "issues": {}, "urls": set(),
        "todos": [], "plans": [], "last_result": None,
        "usage": {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0, "samples": 0},
        "stats": {"total": 0, "user": 0, "assistant": 0, "tool_use": 0,
                  "files_written": 0, "files_edited": 0, "files_read": 0,
                  "bash": 0, "github": 0, "web": 0},
    }
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.rstrip("\n")
            if not raw:
                continue
            rs["stats"]["total"] = lineno
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = parse_ts(msg.get("timestamp"))
            if ts:
                if rs["start"] is None or ts < rs["start"]:
                    rs["start"] = ts
                if rs["end"] is None or ts > rs["end"]:
                    rs["end"] = ts
            mtype = msg.get("type", "")
            if mtype in SKIP_TYPES:
                continue
            inner = msg.get("message")
            if not isinstance(inner, dict):
                continue
            if not rs["session_id"] and msg.get("sessionId"):
                rs["session_id"] = msg["sessionId"]
            if not rs["version"] and msg.get("version"):
                rs["version"] = msg["version"]
            if not rs["model"] and inner.get("model"):
                rs["model"] = inner["model"]

            blocks = content_blocks(inner.get("content"))
            role = inner.get("role", "")

            if role == "user":
                rs["stats"]["user"] += 1
                text = block_text(blocks)
                # skip slash-command echo lines (ccdiag parity)
                if "<command-name>" in text or "<local-command" in text:
                    continue
                if text:
                    rs["user_msgs"].append({"line": lineno, "text": text})
                extract_urls(text, rs["urls"])
                extract_issues(text, lineno, rs["issues"])

            elif role == "assistant":
                rs["stats"]["assistant"] += 1
                for b in blocks:
                    if b.get("type") != "tool_use":
                        continue
                    rs["stats"]["tool_use"] += 1
                    process_tool_use(b, lineno, rs)
                text = block_text(blocks)
                extract_urls(text, rs["urls"])
                extract_issues(text, lineno, rs["issues"])
                # accumulate usage (may be missing/null on older entries)
                usage = inner.get("usage")
                if isinstance(usage, dict):
                    u = rs["usage"]
                    u["input"] += int(usage.get("input_tokens") or 0)
                    u["output"] += int(usage.get("output_tokens") or 0)
                    u["cache_create"] += int(usage.get("cache_creation_input_tokens") or 0)
                    u["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                    u["samples"] += 1
                # scan text blocks for the most recent "result:" line
                for b in blocks:
                    if b.get("type") != "text":
                        continue
                    btext = b.get("text") or ""
                    if not btext:
                        continue
                    for raw_line in btext.splitlines():
                        stripped = raw_line.lstrip()
                        if stripped.startswith("result:"):
                            after = stripped[len("result:"):].lstrip()
                            rs["last_result"] = {"line": lineno, "text": after}
    return rs

def process_tool_use(block: dict, line: int, rs: dict):
    name = block.get("name", "")
    inp = block.get("input")
    if name == "Write":
        p = input_str(inp, "file_path")
        if p:
            rs["files"].append({"line": line, "tool": "Write", "path": p})
            rs["stats"]["files_written"] += 1
    elif name == "Edit" or name == "MultiEdit":
        p = input_str(inp, "file_path")
        if p:
            rs["files"].append({"line": line, "tool": "Edit", "path": p})
            rs["stats"]["files_edited"] += 1
    elif name == "Read":
        p = input_str(inp, "file_path")
        if p:
            rs["files"].append({"line": line, "tool": "Read", "path": p})
            rs["stats"]["files_read"] += 1
    elif name == "Bash":
        cmd = input_str(inp, "command")
        if not cmd:
            return
        rs["stats"]["bash"] += 1
        if "gh issue" in cmd or "gh api" in cmd or "gh pr" in cmd:
            rs["gh_actions"].append({"line": line, "cmd": cmd, "type": classify_gh(cmd)})
            rs["stats"]["github"] += 1
            if "gh issue comment" in cmd:
                track_gh_issue(cmd, rs["issues"], True, False)
            if "gh issue create" in cmd:
                track_gh_issue(cmd, rs["issues"], False, True)
        elif cmd.startswith("git "):
            rs["git_cmds"].append({"line": line, "cmd": cmd})
        elif is_notable_bash(cmd):
            rs["bash_cmds"].append({"line": line, "cmd": cmd})
    elif name == "WebSearch":
        q = input_str(inp, "query")
        if q:
            rs["web"].append({"line": line, "tool": "WebSearch", "q": q})
            rs["stats"]["web"] += 1
    elif name == "WebFetch":
        u = input_str(inp, "url")
        if u:
            rs["web"].append({"line": line, "tool": "WebFetch", "q": u})
            rs["stats"]["web"] += 1
    elif name == "TodoWrite":
        todos = inp.get("todos") if isinstance(inp, dict) else None
        if isinstance(todos, list):
            rs["todos"].append({"line": line, "todos": todos})
    elif name == "ExitPlanMode":
        plan = inp.get("plan") if isinstance(inp, dict) else None
        if isinstance(plan, str) and plan.strip():
            rs["plans"].append({"line": line, "plan": plan})

# ---------- formatting ----------

def fmt_duration(start, end) -> str:
    if not start or not end:
        return "0s"
    secs = int((end - start).total_seconds())
    if secs < 60:
        return f"{secs}s"
    hours, rem = divmod(secs, 3600)
    mins = rem // 60
    if hours > 0:
        return f"{hours}h{mins}m"
    return f"{mins}m"

def shorten(p: str) -> str:
    home = str(Path.home())
    if p.startswith(home + "/"):
        return "~/" + p[len(home) + 1:]
    if p == home:
        return "~"
    return p

def files_summary_rows(files: list[dict]):
    idx = OrderedDict()
    for fa in files:
        info = idx.get(fa["path"])
        if info is None:
            info = {"writes": 0, "edits": 0, "reads": 0, "first": fa["line"]}
            idx[fa["path"]] = info
        if fa["tool"] == "Write":
            info["writes"] += 1
        elif fa["tool"] == "Edit":
            info["edits"] += 1
        elif fa["tool"] == "Read":
            info["reads"] += 1
    rows = []
    for path, info in idx.items():
        if info["writes"] == 0 and info["edits"] == 0:
            continue
        rows.append((shorten(path), info["writes"], info["edits"], info["first"]))
    return rows

PLAN_PATH_RE = re.compile(r"(plan|design|spec|\.md)", re.IGNORECASE)

def associate_plan_files(rs: dict, window: int = 50):
    """For each plan, find a plausibly plan-related Write within `window` JSONL lines after it."""
    writes = [f for f in rs["files"] if f["tool"] == "Write"]
    for plan in rs["plans"]:
        plan["file"] = None
        pl = plan["line"]
        for w in writes:
            if pl <= w["line"] <= pl + window and PLAN_PATH_RE.search(w["path"]):
                plan["file"] = w["path"]
                break

def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s.lstrip("#").strip()
    return ""

def filter_real_user_msgs(msgs: list[dict]) -> list[dict]:
    """Drop harness-noise wrappers from user messages."""
    out = []
    for m in msgs:
        t = m["text"].lstrip()
        if t.startswith("<task-notification>") or t.startswith("<system-reminder>"):
            continue
        out.append(m)
    return out

def render(rs: dict) -> str:
    out = []
    out.append(f"# Session Recovery — {rs['session_id']}\n")
    out.append(f"> **File**: `{rs['file_path']}`")
    start = rs["start"]; end = rs["end"]
    if start and end:
        # render in UTC (matches ccdiag on UTC hosts)
        sfmt = start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        efmt = end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        out.append(f"> **Period**: {sfmt} → {efmt} ({fmt_duration(start, end)})")
    out.append(f"> **Model**: {rs['model']} | **Version**: {rs['version']}\n")

    s = rs["stats"]
    out.append("## Stats\n")
    out.append("| Metric | Count |\n|--------|-------|")
    out.append(f"| JSONL lines | {s['total']} |")
    out.append(f"| User messages | {s['user']} |")
    out.append(f"| Assistant messages | {s['assistant']} |")
    out.append(f"| Tool uses | {s['tool_use']} |")
    out.append(f"| Files written | {s['files_written']} |")
    out.append(f"| Files edited | {s['files_edited']} |")
    out.append(f"| Bash commands | {s['bash']} |")
    out.append(f"| GitHub actions | {s['github']} |")
    out.append(f"| Web searches | {s['web']} |\n")

    rows = files_summary_rows(rs["files"])
    if rows:
        out.append("## Files Modified\n")
        out.append("| File | Writes | Edits | First Line |\n|------|--------|-------|------------|")
        for path, w, e, first in rows:
            out.append(f"| `{path}` | {w} | {e} | L{first} |")
        out.append("")

    # ----- Open Todos -----
    if rs["todos"]:
        last = rs["todos"][-1]
        open_items = [t for t in last["todos"]
                      if isinstance(t, dict) and t.get("status") in ("pending", "in_progress")]
        if open_items:
            out.append("## Open Todos\n")
            out.append(f"(from last TodoWrite at L{last['line']})\n")
            for t in open_items:
                status = t.get("status", "")
                marker = "→" if status == "in_progress" else " "
                content = t.get("content", "") or t.get("activeForm", "")
                out.append(f"- [{marker}] {content}  ({status})")
            out.append("")

    # ----- Approved Plans -----
    if rs["plans"]:
        out.append("## Approved Plans\n")
        for plan in rs["plans"]:
            title = first_nonempty_line(plan.get("plan", ""))
            if len(title) > 100:
                title = title[:100] + "..."
            out.append(f"- **L{plan['line']}**: {title}")
            if plan.get("file"):
                out.append(f"  file: `{shorten(plan['file'])}`")
        out.append("")

    # ----- Last Completed -----
    if rs["last_result"]:
        lr = rs["last_result"]
        out.append("## Last Completed\n")
        text = lr["text"].replace("\n", " ")
        out.append(f"L{lr['line']}: {text}")
        out.append("")

    # ----- Usage -----
    u = rs["usage"]
    if u["samples"] > 0 and (u["input"] or u["output"] or u["cache_create"] or u["cache_read"]):
        total = u["input"] + u["output"] + u["cache_create"] + u["cache_read"]
        denom = u["cache_read"] + u["cache_create"] + u["input"]
        ratio = (u["cache_read"] / denom * 100.0) if denom else 0.0
        out.append("## Usage\n")
        out.append("| Metric | Tokens |\n|--------|--------|")
        out.append(f"| Input (uncached) | {u['input']:,} |")
        out.append(f"| Output | {u['output']:,} |")
        out.append(f"| Cache creation | {u['cache_create']:,} |")
        out.append(f"| Cache read | {u['cache_read']:,} |")
        out.append(f"| **Total** | **{total:,}** |")
        out.append("")
        out.append(f"Cache hit ratio: {ratio:.1f}%\n")

    if rs["issues"]:
        out.append("## GitHub Issues\n")
        out.append("| Issue | Commented | Created | Lines |\n|-------|-----------|---------|-------|")
        for num in sorted(rs["issues"].keys()):
            r = rs["issues"][num]
            c = "yes" if r["commented"] else "—"
            cr = "yes" if r["created"] else "—"
            lines_str = "[" + " ".join(str(x) for x in r["lines"]) + "]"
            out.append(f"| #{num} | {c} | {cr} | {lines_str} |")
        out.append("")

    if rs["gh_actions"]:
        out.append("## GitHub Commands\n")
        for ga in rs["gh_actions"]:
            cmd = ga["cmd"]
            if len(cmd) > 200:
                cmd = cmd[:200] + "..."
            out.append(f"- L{ga['line']} [{ga['type']}]: `{cmd}`")
        out.append("")

    if rs["git_cmds"]:
        out.append("## Git Commands\n")
        for gc in rs["git_cmds"]:
            cmd = gc["cmd"]
            if len(cmd) > 200:
                cmd = cmd[:200] + "..."
            out.append(f"- L{gc['line']}: `{cmd}`")
        out.append("")

    if rs["web"]:
        out.append("## Web Searches\n")
        for ws in rs["web"]:
            q = ws["q"]
            if len(q) > 150:
                q = q[:150] + "..."
            out.append(f"- L{ws['line']} [{ws['tool']}]: {q}")
        out.append("")

    if rs["urls"]:
        out.append("## URLs Referenced\n")
        for u in sorted(rs["urls"]):
            out.append(f"- {u}")
        out.append("")

    real = filter_real_user_msgs(rs["user_msgs"])
    msgs = real[-LAST_N:] if len(real) > LAST_N else real
    out.append(f"## Last {LAST_N} User Messages\n")
    for m in msgs:
        text = m["text"]
        if len(text) > 200:
            text = text[:200] + "..."
        text = text.replace("\n", " ")
        out.append(f"- **L{m['line']}**: {text}")
    out.append("")
    return "\n".join(out) + "\n"

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="Generate a handoff brief from a Claude Code session JSONL.")
    ap.add_argument("session", help="Session UUID, prefix, or full path to JSONL")
    args = ap.parse_args()
    path = resolve_session(args.session)
    rs = recover_session(path)
    associate_plan_files(rs)
    sys.stdout.write(render(rs))

if __name__ == "__main__":
    main()
