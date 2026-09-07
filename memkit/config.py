"""Configuration, paths and small shared helpers."""
import json
import os
import subprocess
import sys
import datetime as _dt
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
HOME = Path.home()
CONFIG_PATH = Path(os.environ.get("CLAUDE_MEMORY_CONFIG", str(HOME / ".claude" / "memory-config.json")))

DEFAULTS = {
    "vault": "~/claude-memory",
    "stateDir": "~/.claude/memory-state",
    "projectsDir": "~/.claude/projects",
    "autocommit": True,
    "mounts": [],
    "reflection": {
        # off | step-count | compaction-event | both
        "trigger": "compaction-event",
        "stepCount": 25,
        "model": "sonnet",
        "maxTurns": 60,
        "minNewMessages": 6,
        "digestMaxBytes": 350000,
    },
    "budget": {
        "targetTokens": 20000,
        "warnTokens": 30000,
        "bytesPerToken": 4,
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    data = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log(f"config parse error {CONFIG_PATH}: {e}")
    return _merge(DEFAULTS, data)


def save(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _expand(p):
    return Path(os.path.expanduser(str(p))).resolve()


def vault():
    return _expand(load()["vault"])


def state_dir():
    d = _expand(load()["stateDir"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def projects_dir():
    return _expand(load()["projectsDir"])


def reflecting():
    """True when we are running inside a background reflection session."""
    return os.environ.get("CLAUDE_MEMORY_REFLECTING") == "1"


def project_slug(cwd):
    """Name of the project for the given cwd: git toplevel basename, else cwd basename."""
    cwd = Path(cwd or os.getcwd())
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(cwd),
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip()).name
    except Exception:  # noqa: BLE001
        pass
    return cwd.name or "root"


def now_iso():
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def log(msg):
    try:
        d = _expand(load()["stateDir"]) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "kit.log", "a", encoding="utf-8") as f:
            f.write(f"{now_iso()} {msg}\n")
    except Exception:  # noqa: BLE001
        print(msg, file=sys.stderr)


def read_hook_input():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        return {}


def in_vault(path):
    """Return the path relative to the vault, or None if outside."""
    try:
        p = Path(path).expanduser().resolve()
        rel = p.relative_to(vault())
        return rel
    except Exception:  # noqa: BLE001
        return None
