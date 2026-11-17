#!/usr/bin/env python3
"""SessionStart hook: absorb manual edits, compile the vault into additionalContext (Letta recompile).

Claude Code caps a single hook's injected output at ~10k chars; anything larger is replaced by a
preview and a file path, i.e. core memory silently disappears. So the installer registers this
hook N times (`--part 0..N-1 --parts N`); every part compiles the same text and prints its own
slice. Side effects (absorbing manual edits, pulling mounts) happen only in part 0, and mounts are
pulled *after* compiling so all parts slice identical text (fresh mounts show up next session).
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memkit import config, gitops, mounts, vault  # noqa: E402

DEFAULT_PART_CHARS = 9000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--parts", type=int, default=1)
    args, _ = ap.parse_known_args()
    part, parts = args.part, max(1, args.parts)

    data = config.read_hook_input()
    cwd = data.get("cwd") or None
    notes = []
    v = config.vault()
    if not v.exists():
        if part == 0:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                              "additionalContext": f"<memory_system>Memory vault {v} does not exist. Run the claude-memory-kit installer.</memory_system>"}}))
        return
    if part == 0 and gitops.is_repo() and gitops.is_dirty() and not config.reflecting():
        h = gitops.commit_all("chore(manual): absorb edits made outside Claude Code (Obsidian/editor)\n\nGenerated-By: claude-memory-kit")
        if h:
            notes.append(f"Absorbed manual edits at session start (commit {h}).")
    all_issues = vault.validate()
    errors = [i for i in all_issues if i[0] == "error"]
    if errors:
        notes.append(f"⚠ {len(errors)} contract error(s) in the vault — run `memoryctl validate` / /memory-doctor: " +
                     "; ".join(f"{p}: {m}" for _, p, m in errors[:5]))
    unindexed = [p for lvl, p, m in all_issues if lvl == "warning" and "not referenced from" in m]
    if unindexed:
        notes.append(f"⚠ {len(unindexed)} memory file(s) missing from their MEMORY.md index — add one line each now: " +
                     ", ".join(unindexed[:8]))

    cfg = config.load()
    size = int(cfg["budget"].get("hookPartChars", DEFAULT_PART_CHARS))
    text, stats = vault.compile_context(cwd, extra_notes=notes, pull_mounts=False)
    chunks = vault.chunk(text, size)

    if part < len(chunks):
        body = chunks[part]
        if len(chunks) > 1:
            body = f"<memory_part {part + 1}/{len(chunks)}>\n{body}\n</memory_part>"
        if part == parts - 1 and len(chunks) > parts:
            full = config.state_dir() / "compiled-memory.md"
            full.write_text(text, encoding="utf-8")
            body += (f"\n⚠ Memory did not fit into {parts} hook parts ({len(chunks)} needed). "
                     f"Read the rest NOW from {full} (from part {parts + 1}); then run /memory-doctor or raise the part count.")
        out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": body}}
        if part == 0 and stats["tokens"] > cfg["budget"]["warnTokens"]:
            out["systemMessage"] = f"memory: core memory ~{stats['tokens']} tokens is over budget — consider /memory-doctor"
        print(json.dumps(out, ensure_ascii=False))

    if part == 0 and not config.reflecting():
        for m in mounts.active(config.project_slug(cwd)):
            st = mounts.pull(m)
            if st.startswith("pull failed"):
                config.log(f"mount {m['name']}: {st}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        config.log(f"session_start hook error: {e!r}")
        sys.exit(0)
