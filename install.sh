#!/usr/bin/env bash
# claude-memory-kit installer — Letta/MemGPT-style memory for Claude Code.
# Idempotent: safe to re-run to upgrade. Usage: ./install.sh [--vault ~/claude-memory] [--no-migrate]
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT="${CLAUDE_MEMORY_VAULT:-$HOME/claude-memory}"
MIGRATE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --vault) VAULT="$2"; shift 2 ;;
    --no-migrate) MIGRATE=0; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
done
VAULT="${VAULT/#\~/$HOME}"
CLAUDE_DIR="$HOME/.claude"
DEST="$CLAUDE_DIR/memory-kit"
MEMORYCTL="$DEST/bin/memoryctl"
CONFIG="$CLAUDE_DIR/memory-config.json"
SETTINGS="$CLAUDE_DIR/settings.json"
CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"
TODAY="$(date +%Y-%m-%d)"

say() { printf '\033[1;35m[memory-kit]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[memory-kit] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 0. prerequisites ----
command -v python3 >/dev/null || die "python3 is required"
command -v git >/dev/null || die "git is required"
command -v claude >/dev/null || say "warning: 'claude' not in PATH — background reflection needs it (install Claude Code CLI)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || die "python3 >= 3.8 required"

# ---- 1. copy the kit ----
say "installing kit → $DEST"
mkdir -p "$DEST"
rm -rf "$DEST/memkit" "$DEST/hooks" "$DEST/bin" "$DEST/templates"
cp -R "$SRC/memkit" "$SRC/hooks" "$SRC/bin" "$SRC/templates" "$DEST/"
cp "$SRC/README.md" "$DEST/README.md" 2>/dev/null || true
cp "$SRC/uninstall.sh" "$DEST/uninstall.sh" 2>/dev/null || true
chmod +x "$DEST/bin/memoryctl" "$DEST/hooks/"*.py
find "$DEST" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# ---- 2. config ----
if [ ! -f "$CONFIG" ]; then
  say "writing config → $CONFIG (vault: $VAULT)"
  sed "s|__VAULT__|$VAULT|g" "$SRC/templates/memory-config.json" > "$CONFIG"
else
  say "config exists, keeping it: $CONFIG"
  VAULT="$(python3 -c "import json,os;print(os.path.expanduser(json.load(open('$CONFIG')).get('vault','$VAULT')))")"
fi

# ---- 3. vault ----
say "vault → $VAULT"
mkdir -p "$VAULT/projects"
for f in MEMORY.md persona.md human-identity.md human-prefs-communication.md human-prefs-coding.md human-prefs-workflow.md ARCHIVE.md projects/MEMORY.md .gitignore; do
  if [ ! -e "$VAULT/$f" ]; then cp "$SRC/templates/vault/$f" "$VAULT/$f"; fi
done
if [ ! -d "$VAULT/.obsidian" ]; then
  cp -R "$SRC/templates/vault/.obsidian" "$VAULT/.obsidian"
fi
if [ ! -d "$VAULT/.git" ]; then
  git -C "$VAULT" init -q -b main 2>/dev/null || git -C "$VAULT" init -q
fi
mkdir -p "$VAULT/.git/hooks"
cp "$SRC/templates/vault-pre-commit" "$VAULT/.git/hooks/pre-commit"
chmod +x "$VAULT/.git/hooks/pre-commit"

# ---- 4. migrate existing Claude Code auto-memory ----
if [ "$MIGRATE" = "1" ]; then
  STATE="$CLAUDE_DIR/memory-state"; mkdir -p "$STATE/migrated"
  for mdir in "$CLAUDE_DIR"/projects/*/memory; do
    [ -d "$mdir" ] || continue
    slug="$(basename "$(dirname "$mdir")")"
    # skip the vault itself if someone pointed a project memory there
    [ "$(cd "$mdir" && pwd -P)" = "$(cd "$VAULT" && pwd -P)" ] && continue
    [ -f "$STATE/migrated/$slug" ] && continue
    n=0
    for f in "$mdir"/*.md; do
      [ -f "$f" ] || continue
      b="$(basename "$f")"
      [ "$b" = "MEMORY.md" ] && continue
      if [ ! -e "$VAULT/$b" ]; then cp "$f" "$VAULT/$b"; n=$((n+1)); fi
    done
    if [ -f "$mdir/MEMORY.md" ]; then
      # append index lines that are not present yet
      while IFS= read -r line; do
        case "$line" in
          -*) grep -qF -- "$line" "$VAULT/MEMORY.md" || printf '%s\n' "$line" >> "$VAULT/MEMORY.md" ;;
        esac
      done < "$mdir/MEMORY.md"
    fi
    mv "$mdir" "$(dirname "$mdir")/memory.pre-kit-backup-$TODAY"
    echo "$TODAY" > "$STATE/migrated/$slug"
    say "migrated $n memory file(s) from $slug (old dir kept as memory.pre-kit-backup-$TODAY)"
  done
fi

# ---- 5. agents & skills ----
mkdir -p "$CLAUDE_DIR/agents" "$CLAUDE_DIR/skills"
for a in "$SRC"/agents/*.md; do cp "$a" "$CLAUDE_DIR/agents/"; done
for s in "$SRC"/skills/*/; do
  name="$(basename "$s")"
  mkdir -p "$CLAUDE_DIR/skills/$name"
  sed -e "s|__MEMORYCTL__|$MEMORYCTL|g" -e "s|__VAULT__|$VAULT|g" "$s/SKILL.md" > "$CLAUDE_DIR/skills/$name/SKILL.md"
done
say "installed agents: $(ls "$SRC"/agents | sed 's/.md$//' | tr '\n' ' ')"
say "installed skills: $(ls "$SRC"/skills | tr '\n' ' ')"

# ---- 6. settings.json: autoMemoryDirectory + hooks ----
say "merging hooks into $SETTINGS"
python3 - "$SETTINGS" "$DEST" "$VAULT" <<'PY'
import json, sys, os
settings_path, dest, vault = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        raw = f.read().strip()
        data = json.loads(raw) if raw else {}
home = os.path.expanduser("~")
vault_disp = vault.replace(home, "~", 1) if vault.startswith(home) else vault
data["autoMemoryDirectory"] = vault_disp
hooks = data.setdefault("hooks", {})
def cmd(script): return f'python3 "{dest}/hooks/{script}"'
PARTS = int(os.environ.get("MEMORY_HOOK_PARTS", "8"))
wanted = {
    # Claude Code caps each hook's injected output at ~10k chars, so the compiled memory is
    # delivered by several instances of the same hook, each printing its own slice.
    "SessionStart": [{"matcher": "startup|resume|clear|compact", "hooks": [
        {"type": "command", "command": cmd("session_start.py") + f" --part {i} --parts {PARTS}", "timeout": 60,
         **({"statusMessage": "Compiling memory"} if i == 0 else {})} for i in range(PARTS)]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": cmd("recall_on_prompt.py"), "timeout": 15}]}],
    "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command": cmd("pre_tool_guard.py"), "timeout": 15}]}],
    "PostToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command": cmd("post_tool_commit.py"), "timeout": 30}]}],
    "PreCompact": [{"matcher": "manual|auto", "hooks": [{"type": "command", "command": cmd("reflect_trigger.py"), "timeout": 20, "async": True}]}],
    "Stop": [{"hooks": [{"type": "command", "command": cmd("reflect_trigger.py"), "timeout": 20, "async": True}]}],
}
for event, entries in wanted.items():
    existing = hooks.get(event, [])
    kept = [e for e in existing if not any("memory-kit/hooks" in h.get("command", "") for h in e.get("hooks", []))]
    hooks[event] = kept + entries
with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False); f.write("\n")
print("  autoMemoryDirectory =", vault_disp)
print("  hooks:", ", ".join(wanted))
PY

# ---- 7. ~/.claude/CLAUDE.md section ----
say "updating $CLAUDE_MD"
python3 - "$CLAUDE_MD" "$SRC/templates/CLAUDE.md.section" "$MEMORYCTL" "$VAULT" <<'PY'
import sys, os, re
path, tpl, memoryctl, vault = sys.argv[1:5]
section = open(tpl, encoding="utf-8").read().replace("__MEMORYCTL__", memoryctl).replace("__VAULT__", vault)
cur = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
pat = re.compile(r"<!-- claude-memory-kit:start -->.*?<!-- claude-memory-kit:end -->\n?", re.S)
if pat.search(cur):
    new = pat.sub(section, cur)
else:
    new = (cur.rstrip() + "\n\n" if cur.strip() else "") + section
open(path, "w", encoding="utf-8").write(new)
PY

# ---- 8. initial commit + validation ----
if [ -z "$(git -C "$VAULT" rev-parse --verify HEAD 2>/dev/null)" ] || [ -n "$(git -C "$VAULT" status --porcelain)" ]; then
  git -C "$VAULT" add -A
  git -C "$VAULT" -c user.name="${GIT_AUTHOR_NAME:-$(git config user.name || echo claude-memory-kit)}" \
     -c user.email="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo memory@localhost)}" \
     commit -q --no-verify -m "chore(kit): install/upgrade claude-memory-kit ($TODAY)

Generated-By: claude-memory-kit" || true
fi
say "validating vault contract"
python3 "$MEMORYCTL" validate || say "warning: contract issues above — run /memory-doctor in Claude Code"

cat <<EOF

$(printf '\033[1;32m')Done.$(printf '\033[0m')
  vault:      $VAULT   (git: $(git -C "$VAULT" rev-parse --short HEAD))
  kit:        $DEST
  config:     $CONFIG
  CLI:        $MEMORYCTL   (alias memoryctl='python3 $MEMORYCTL')

Next steps:
  1. Restart Claude Code (hooks/skills load at startup). Run /memory-status to check.
  2. Optional: install Obsidian and open the vault:   brew install --cask obsidian && open "obsidian://open?path=$VAULT"
  3. Optional: bootstrap memory from past sessions:   /memory-init
  4. Reflection runs in the background on context compaction (change with /memory-sleeptime).
EOF
