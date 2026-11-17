#!/usr/bin/env python3
"""UserPromptSubmit hook: keyword-search deferred memory and inject matching files.

Core memory is compiled at SessionStart; deeper files are only path + description there, and the
agent tends to skip reading them. This hook does the lookup deterministically on every prompt.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memkit import config, retrieve  # noqa: E402


def main():
    if config.reflecting():
        return
    data = config.read_hook_input()
    prompt = data.get("prompt") or ""
    if len(prompt.strip()) < 3:
        return
    cfg = config.load().get("recallOnPrompt", {})
    if cfg.get("enabled", True) is False:
        return
    slug = config.project_slug(data.get("cwd") or None)
    results = retrieve.search(prompt, slug, limit=int(cfg.get("limit", 5)))
    if not results:
        return
    sid = data.get("session_id", "")
    seen = retrieve.load_seen(sid)
    text, newly = retrieve.render(results, seen, max_chars=int(cfg.get("maxChars", 7000)))
    retrieve.save_seen(sid, seen | newly)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        config.log(f"recall_on_prompt hook error: {e!r}")
        sys.exit(0)
