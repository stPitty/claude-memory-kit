#!/usr/bin/env bash
# Remove claude-memory-kit hooks/agents/skills/CLAUDE.md section. The vault itself is NOT deleted.
set -euo pipefail
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
python3 - "$SETTINGS" <<'PY'
import json, sys, os
p = sys.argv[1]
if os.path.exists(p):
    d = json.load(open(p))
    d.pop("autoMemoryDirectory", None)
    hooks = d.get("hooks", {})
    for ev in list(hooks):
        hooks[ev] = [e for e in hooks[ev] if not any("memory-kit/hooks" in h.get("command", "") for h in e.get("hooks", []))]
        if not hooks[ev]: del hooks[ev]
    json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
PY
python3 - "$CLAUDE_DIR/CLAUDE.md" <<'PY'
import sys, os, re
p = sys.argv[1]
if os.path.exists(p):
    s = open(p).read()
    s = re.sub(r"\n?<!-- claude-memory-kit:start -->.*?<!-- claude-memory-kit:end -->\n?", "\n", s, flags=re.S)
    open(p, "w").write(s)
PY
rm -f "$CLAUDE_DIR"/agents/memory-reflection.md "$CLAUDE_DIR"/agents/memory-recall.md "$CLAUDE_DIR"/agents/memory-history-analyzer.md
for s in remember memory-reflect memory-recall memory-doctor memory-init memory-status memory-sleeptime; do rm -rf "$CLAUDE_DIR/skills/$s"; done
rm -rf "$CLAUDE_DIR/memory-kit"
echo "claude-memory-kit removed. Vault, config ($CLAUDE_DIR/memory-config.json) and state ($CLAUDE_DIR/memory-state) were kept."
