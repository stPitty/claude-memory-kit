#!/usr/bin/env python3
"""PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit): enforce the vault contract before a write lands.
Guardrails ported from Letta's memory tool: indexed dirs only, read_only, no secrets, no MEMORY.md deletion, no .git/.obsidian."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memkit import config, vault  # noqa: E402


def decide(decision, reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))


def main():
    data = config.read_hook_input()
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not path:
        return
    rel = config.in_vault(path)
    if rel is None:
        return
    parts = rel.parts
    if parts and parts[0] in (".git", ".obsidian", ".trash"):
        return decide("deny", f"memory: {rel} is internal to the vault (git/Obsidian) and must not be edited by the agent")
    if parts and any(p.startswith(".") for p in parts):
        return decide("deny", f"memory: hidden paths inside the vault are not memory: {rel}")
    if rel.suffix != ".md":
        return decide("deny", f"memory: only Markdown files are memory; refusing to write {rel}")
    ua = vault.unindexed_ancestor(rel)
    if ua is not None:
        return decide("deny", f"memory: Memory requires {ua}/MEMORY.md before writing {rel}. "
                              f"Create the frontmatter-free index {ua}/MEMORY.md first (one line per file with a link), "
                              f"and register {ua}/ in its parent MEMORY.md.")
    full = config.vault() / rel
    if full.exists() and vault.is_read_only(full):
        return decide("deny", f"memory: {rel} is read_only and cannot be modified by the agent (edit it by hand in Obsidian if needed)")
    new_text = ti.get("content") or ti.get("new_string") or ""
    if isinstance(ti.get("edits"), list):
        new_text += "\n".join(e.get("new_string", "") for e in ti["edits"] if isinstance(e, dict))
    for rx, label in vault.SECRET_PATTERNS:
        if rx.search(new_text):
            return decide("deny", f"memory: refusing to store what looks like a secret ({label}). Never store credentials, "
                                  f"API keys or tokens in memory — reference them as $SECRET_NAME instead.")
    if rel.name == vault.INDEX and ti.get("content") is not None and ti["content"].lstrip().startswith("---"):
        return decide("deny", "memory: MEMORY.md is a frontmatter-free index; do not add frontmatter to it")
    decide("allow", "memory vault edit (auto-committed by claude-memory-kit)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        config.log(f"pre_tool_guard error: {e!r}")
        sys.exit(0)
