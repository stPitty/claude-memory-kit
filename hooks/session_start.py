#!/usr/bin/env python3
"""SessionStart hook: absorb manual edits, compile the vault into additionalContext (Letta recompile)."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memkit import config, gitops, vault  # noqa: E402


def main():
    data = config.read_hook_input()
    cwd = data.get("cwd") or None
    notes = []
    v = config.vault()
    if not v.exists():
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                          "additionalContext": f"<memory_system>Memory vault {v} does not exist. Run the claude-memory-kit installer.</memory_system>"}}))
        return
    if gitops.is_repo() and gitops.is_dirty() and not config.reflecting():
        h = gitops.commit_all("chore(manual): absorb edits made outside Claude Code (Obsidian/editor)\n\nGenerated-By: claude-memory-kit")
        if h:
            notes.append(f"Absorbed manual edits at session start (commit {h}).")
    issues = [i for i in vault.validate() if i[0] == "error"]
    if issues:
        notes.append(f"⚠ {len(issues)} contract error(s) in the vault — run `memoryctl validate` / /memory-doctor: " +
                     "; ".join(f"{p}: {m}" for _, p, m in issues[:5]))
    text, stats = vault.compile_context(cwd, extra_notes=notes, pull_mounts=not config.reflecting())
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    if stats["tokens"] > config.load()["budget"]["warnTokens"]:
        out["systemMessage"] = f"memory: core memory ~{stats['tokens']} tokens is over budget — consider /memory-doctor"
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        config.log(f"session_start hook error: {e!r}")
        sys.exit(0)
