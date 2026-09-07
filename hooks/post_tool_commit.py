#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write|MultiEdit|NotebookEdit): validate the written memory file and auto-commit it."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memkit import config, gitops, vault  # noqa: E402


def main():
    data = config.read_hook_input()
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not path:
        return
    rel = config.in_vault(path)
    if rel is None:
        return
    full = config.vault() / rel
    issues = vault.validate([full]) if full.exists() else []
    errors = [i for i in issues if i[0] == "error"]
    warnings = [i for i in issues if i[0] == "warning"]
    # discoverability check for the single file
    if full.exists() and rel.name != vault.INDEX:
        idx = full.parent / vault.INDEX
        if idx.exists():
            it = idx.read_text(encoding="utf-8")
            if full.name not in it and full.stem not in it:
                warnings.append(("warning", str(rel), f"not yet referenced from {idx.relative_to(config.vault())} — add one index line so future sessions can discover it"))
    if errors:
        print("memory contract violation — fix the file (it stays uncommitted = not persisted):\n" +
              "\n".join(f"- {p}: {m}" for _, p, m in errors), file=sys.stderr)
        sys.exit(2)
    if config.reflecting() or not config.load().get("autocommit", True):
        return
    if gitops.is_repo():
        tool = data.get("tool_name", "Edit")
        sid = data.get("session_id", "")
        h = gitops.commit_all(f"memory({tool.lower()}): {rel}\n\nSession: {sid}\nGenerated-By: claude-memory-kit")
    else:
        h = None
    msgs = []
    if h:
        msgs.append(f"memory committed ({h}): {rel}. Takes effect at the next session start.")
    for _, p, m in warnings:
        msgs.append(f"memory warning — {p}: {m}")
    if msgs:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n".join(msgs)}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        config.log(f"post_tool_commit error: {e!r}")
        sys.exit(0)
