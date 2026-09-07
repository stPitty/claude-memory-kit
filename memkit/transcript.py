"""Claude Code transcript (.jsonl) parsing: digests for reflection, search + expand for recall."""
import json
import re
from pathlib import Path
from . import config

TRUNC_TEXT = 2500
TRUNC_TOOL_INPUT = 400
TRUNC_TOOL_RESULT = 400


def _short(s, n):
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def iter_messages(path, from_line=0):
    """Yield normalized messages: dict(line, ts, role, kind, text, tool, session, cwd).
    kind: user | assistant | tool_use | tool_result | summary"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, raw in enumerate(f, start=1):
            if i <= from_line:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            t = rec.get("type")
            if t == "summary":
                yield {"line": i, "ts": rec.get("timestamp", ""), "role": "system", "kind": "summary",
                       "text": rec.get("summary", ""), "tool": None, "session": rec.get("sessionId"), "cwd": rec.get("cwd")}
                continue
            if t not in ("user", "assistant"):
                continue
            if rec.get("isSidechain"):
                continue
            msg = rec.get("message") or {}
            content = msg.get("content")
            base = {"line": i, "ts": rec.get("timestamp", ""), "session": rec.get("sessionId"), "cwd": rec.get("cwd")}
            if t == "user":
                if rec.get("isMeta"):
                    continue
                if isinstance(content, str):
                    if content.startswith("<command-name>") or content.startswith("<local-command"):
                        continue
                    yield dict(base, role="user", kind="user", text=content, tool=None)
                elif isinstance(content, list):
                    texts = []
                    for b in content:
                        bt = b.get("type")
                        if bt == "text":
                            texts.append(b.get("text", ""))
                        elif bt == "tool_result":
                            c = b.get("content")
                            if isinstance(c, list):
                                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                            yield dict(base, role="user", kind="tool_result", text=c or "", tool=b.get("tool_use_id"))
                    if texts:
                        yield dict(base, role="user", kind="user", text="\n".join(texts), tool=None)
            else:
                if isinstance(content, str):
                    yield dict(base, role="assistant", kind="assistant", text=content, tool=None)
                elif isinstance(content, list):
                    for b in content:
                        bt = b.get("type")
                        if bt == "text" and b.get("text", "").strip():
                            yield dict(base, role="assistant", kind="assistant", text=b["text"], tool=None)
                        elif bt == "tool_use":
                            yield dict(base, role="assistant", kind="tool_use", text=_tool_input_summary(b.get("input")),
                                       tool=b.get("name"))


def _tool_input_summary(inp):
    if not isinstance(inp, dict):
        return json.dumps(inp, ensure_ascii=False)
    for k in ("command", "file_path", "pattern", "query", "prompt", "description", "url"):
        if k in inp:
            return f"{k}={_short(inp[k], TRUNC_TOOL_INPUT)}"
    return _short(inp, TRUNC_TOOL_INPUT)


def line_count(path):
    n = 0
    with open(path, "rb") as f:
        for _ in f:
            n += 1
    return n


def digest(path, from_line=0, max_bytes=350000):
    """Render a compact markdown digest. Returns (text, stats)."""
    out = []
    stats = {"user": 0, "assistant": 0, "tool_use": 0, "tool_result": 0, "summary": 0, "first_ts": None, "last_ts": None}
    msgs = list(iter_messages(path, from_line))
    last_assistant = max((i for i, m in enumerate(msgs) if m["kind"] == "assistant"), default=None)
    for i, m in enumerate(msgs):
        stats[m["kind"]] = stats.get(m["kind"], 0) + 1
        stats["first_ts"] = stats["first_ts"] or m["ts"]
        stats["last_ts"] = m["ts"] or stats["last_ts"]
        ts = (m["ts"] or "")[:19].replace("T", " ")
        if m["kind"] == "user":
            out.append(f"\n### [{m['line']}] USER @ {ts}\n{_short(m['text'], TRUNC_TEXT * 2)}")
        elif m["kind"] == "assistant":
            cap = TRUNC_TEXT * 6 if i == last_assistant else TRUNC_TEXT  # the closing summary is high-signal: keep it whole
            out.append(f"\n### [{m['line']}] ASSISTANT @ {ts}\n{_short(m['text'], cap)}")
        elif m["kind"] == "tool_use":
            out.append(f"- [{m['line']}] → {m['tool']}: {m['text']}")
        elif m["kind"] == "tool_result":
            out.append(f"- [{m['line']}] ← result: {_short(m['text'], TRUNC_TOOL_RESULT)}")
        elif m["kind"] == "summary":
            out.append(f"\n### [{m['line']}] COMPACTION SUMMARY\n{_short(m['text'], TRUNC_TEXT * 2)}")
    text = "\n".join(out)
    if len(text.encode("utf-8")) > max_bytes:
        b = text.encode("utf-8")[-max_bytes:]
        text = "[… digest truncated to the most recent part …]\n" + b.decode("utf-8", errors="ignore")
    stats["lines_total"] = line_count(path)
    stats["conversational"] = stats["user"] + stats["assistant"]
    return text, stats


# ---------- recall ----------

def session_files(project=None):
    pd = config.projects_dir()
    if not pd.exists():
        return []
    files = []
    for d in sorted(pd.iterdir()):
        if not d.is_dir():
            continue
        if project and project != "all" and project not in d.name:
            continue
        files.extend(sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True))
    return files


def find_session(session_id):
    pd = config.projects_dir()
    for f in pd.glob(f"*/{session_id}*.jsonl"):
        return f
    return None


def sessions(project=None, limit=30):
    rows = []
    for f in session_files(project)[:limit]:
        first = None
        n = 0
        last_ts = ""
        cwd = ""
        for m in iter_messages(f):
            if m["kind"] == "user":
                n += 1
                if first is None:
                    first = m["text"]
                    cwd = m.get("cwd") or ""
                last_ts = m["ts"] or last_ts
        if first is None:
            continue
        rows.append({"session": f.stem, "project": f.parent.name, "cwd": cwd, "user_messages": n,
                     "last": last_ts[:19], "first_prompt": _short(first.replace("\n", " "), 120), "path": str(f)})
    return rows


def search(query, project=None, limit=20, roles=("user", "assistant"), regex=False, since=None):
    if regex:
        rx = re.compile(query, re.IGNORECASE)
    else:
        rx = re.compile(re.escape(query), re.IGNORECASE)
    hits = []
    for f in session_files(project):
        for m in iter_messages(f):
            if m["kind"] not in roles:
                continue
            if since and (m["ts"] or "") < since:
                continue
            text = m["text"] or ""
            mm = rx.search(text)
            if not mm:
                continue
            s = max(0, mm.start() - 120)
            snippet = text[s: mm.end() + 160].replace("\n", " ")
            hits.append({"session": f.stem, "project": f.parent.name, "line": m["line"], "ts": (m["ts"] or "")[:19],
                         "role": m["kind"], "snippet": snippet, "path": str(f)})
    hits.sort(key=lambda h: h["ts"], reverse=True)
    return hits[:limit]


def expand(session_id, line, before=3, after=3):
    f = find_session(session_id)
    if not f:
        return None
    msgs = [m for m in iter_messages(f) if m["kind"] in ("user", "assistant", "summary")]
    idx = None
    for i, m in enumerate(msgs):
        if m["line"] >= line:
            idx = i
            break
    if idx is None:
        idx = len(msgs) - 1
    window = msgs[max(0, idx - before): idx + after + 1]
    out = [f"# session {f.stem} ({f.parent.name}) — around line {line}"]
    for m in window:
        mark = ">>>" if m["line"] == msgs[idx]["line"] else "   "
        out.append(f"\n{mark} [{m['line']}] {m['kind'].upper()} @ {(m['ts'] or '')[:19]}\n{_short(m['text'], 3000)}")
    return "\n".join(out)
