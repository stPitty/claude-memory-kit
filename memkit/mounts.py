"""Shared / external memory mounts (Letta `shared-memory` analogue).

A mount is an external git repository (someone else's memory, a team knowledge repo) that is
attached next to the vault: only its file tree + descriptions are compiled into context; file
contents are read on demand. Mounts are read-only by default and pulled at session start.
"""
import fnmatch
import re
import subprocess
from pathlib import Path
from . import config, frontmatter, gitops

MOUNTS_DIR = config.HOME / ".claude" / "memory-mounts"
DEFAULT = {"readOnly": True, "autoPull": True, "only": [], "maxEntries": 80, "maxDepth": 3, "subdir": "",
           "descMax": 110, "exclude": [], "collapse": [], "focus": True}


def all_mounts():
    out = []
    for m in config.load().get("mounts", []) or []:
        mm = dict(DEFAULT)
        mm.update(m)
        out.append(mm)
    return out


def root(m):
    p = Path(m["path"]).expanduser()
    if m.get("subdir"):
        p = p / m["subdir"]
    return p


def repo_root(m):
    return Path(m["path"]).expanduser()


def matches(m, slug):
    only = m.get("only") or []
    return not only or any(fnmatch.fnmatch(slug, pat) for pat in only)


def active(slug):
    return [m for m in all_mounts() if matches(m, slug)]


def find(path):
    """Return (mount, relpath) if `path` is inside a mount, else None."""
    try:
        p = Path(path).expanduser().resolve()
    except Exception:  # noqa: BLE001
        return None
    for m in all_mounts():
        try:
            rel = p.relative_to(repo_root(m).resolve())
            return m, rel
        except Exception:  # noqa: BLE001
            continue
    return None


def pull(m, timeout=25):
    """git pull --ff-only; returns a short status string."""
    rp = repo_root(m)
    if not rp.exists():
        return "missing"
    if not (rp / ".git").exists():
        return "not a git repo"
    if not m.get("autoPull", True):
        return "pull disabled"
    rc, out, err = gitops.run(["remote"], cwd=rp)
    if rc != 0 or not out.strip():
        return "no remote"
    try:
        r = subprocess.run(["git", "pull", "--ff-only", "-q"], cwd=str(rp), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "pull timed out"
    if r.returncode != 0:
        return "pull failed: " + (r.stderr.strip().splitlines() or ["?"])[-1][:120]
    return "up to date"


def status(m):
    rp = repo_root(m)
    if not rp.exists():
        return {"revision": None, "dirty": False, "exists": False}
    if not (rp / ".git").exists():
        return {"revision": None, "dirty": False, "exists": True}
    return {"revision": gitops.head(cwd=rp), "dirty": gitops.is_dirty(cwd=rp), "exists": True}


_H1 = re.compile(r"^#\s+(.+)$", re.M)


def _desc(p: Path):
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:4000]
    except Exception:  # noqa: BLE001
        return ""
    meta, body = frontmatter.parse(text)
    if isinstance(meta, dict) and meta.get("description"):
        return str(meta["description"]).strip()
    m = _H1.search(body if meta is not None else text)
    if m:
        return m.group(1).strip()
    for line in (body if meta is not None else text).splitlines():
        line = line.strip()
        if line and not line.startswith(("---", "<!--")):
            return line[:120]
    return ""


def _md_count(d: Path):
    return sum(1 for p in d.rglob("*.md") if not any(x.startswith(".") for x in p.relative_to(d).parts))


def _match_any(rel: str, globs):
    return any(fnmatch.fnmatch(rel, g) for g in globs or [])


def render_tree(m, slug=None):
    """Depth/entry-limited tree of Markdown files with one-line descriptions.
    exclude: globs (relative to the mount root) hidden entirely.
    collapse: globs of directories shown as one line with a file count — unless `focus` is on and the dir name == current project slug."""
    base = root(m)
    desc_max = int(m.get("descMax", 110))
    excl = m.get("exclude") or []
    coll = m.get("collapse") or []
    focus = bool(m.get("focus", True))
    lines = [f"{base}/"]
    budget = {"n": int(m.get("maxEntries", 80)), "skipped": 0, "other": 0}
    max_depth = int(m.get("maxDepth", 3))
    if not base.exists():
        return f"{base}/  (missing — run: memoryctl mount pull {m['name']})"

    def walk(d: Path, prefix: str, depth: int):
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
        except Exception:  # noqa: BLE001
            return
        entries = [e for e in entries if not e.name.startswith(".") and e.name not in ("node_modules",)
                   and not _match_any(str(e.relative_to(base)), excl)]
        files = [e for e in entries if e.is_file()]
        mds = [e for e in files if e.suffix.lower() in (".md", ".mdx", ".txt")]
        budget["other"] += len(files) - len(mds)
        dirs = [e for e in entries if e.is_dir()]
        # index files first
        mds.sort(key=lambda p: (0 if p.name.upper() in ("MEMORY.MD", "README.MD", "INDEX.MD") else 1, p.name.lower()))
        items = [("f", p) for p in mds] + [("d", p) for p in dirs]
        for i, (kind, p) in enumerate(items):
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            ext = "    " if last else "│   "
            if budget["n"] <= 0:
                budget["skipped"] += 1
                continue
            budget["n"] -= 1
            if kind == "f":
                d_ = _desc(p)
                if len(d_) > desc_max:
                    d_ = d_[: desc_max - 1].rstrip() + "…"
                lines.append(f"{prefix}{branch}{p.name}" + (f" — {d_}" if d_ else ""))
            else:
                relp = str(p.relative_to(base))
                if _match_any(relp, coll) and not (focus and slug and p.name == slug):
                    lines.append(f"{prefix}{branch}{p.name}/ ({_md_count(p)} md files, collapsed — open when working on '{p.name}')")
                    continue
                if depth >= max_depth:
                    lines.append(f"{prefix}{branch}{p.name}/ …")
                    continue
                lines.append(f"{prefix}{branch}{p.name}/")
                walk(p, prefix + ext, depth + 1)

    walk(base, "", 1)
    if budget["skipped"]:
        lines.append(f"… {budget['skipped']} more entries not shown (raise maxEntries/maxDepth for mount '{m['name']}')")
    if budget["other"]:
        lines.append(f"({budget['other']} non-Markdown files not listed)")
    return "\n".join(lines)


def compile_section(slug, do_pull=False):
    mounts = active(slug)
    if not mounts:
        return "", []
    parts = ["<shared_memory>",
             "External memory repositories mounted next to the vault (owned by others or shared with the team). "
             "Their contents are NOT loaded automatically: when a task touches a topic listed below, Read the file from its path. "
             "Read-only mounts must not be edited; writable ones are auto-committed in their own repository."]
    notes = []
    for m in mounts:
        st = status(m)
        pulled = pull(m) if do_pull else None
        attrs = [f'name="{m["name"]}"', f'path="{root(m)}"', f'read_only="{"true" if m.get("readOnly", True) else "false"}"']
        if st["revision"]:
            attrs.append(f'revision="{st["revision"]}"')
        if pulled:
            attrs.append(f'sync="{pulled}"')
        if st["dirty"]:
            attrs.append('dirty="true"')
            notes.append(f"mount '{m['name']}' has uncommitted changes")
        if pulled and pulled.startswith("pull failed"):
            notes.append(f"mount '{m['name']}': {pulled}")
        parts.append(f"<mount {' '.join(attrs)}>")
        parts.append(render_tree(m, slug))
        parts.append("</mount>")
    parts.append("</shared_memory>")
    return "\n".join(parts), notes


# ---------- management ----------

def _is_url(s):
    return s.startswith(("http://", "https://", "git@", "ssh://")) or (":" in s and not Path(s).expanduser().exists())


def add(source, name=None, read_only=True, auto_pull=True, only=None, subdir="", exclude=None, collapse=None):
    cfg = config.load()
    mounts = cfg.setdefault("mounts", [])
    if _is_url(source):
        name = name or re.sub(r"\.git$", "", source.rstrip("/").split("/")[-1].split(":")[-1])
        dest = MOUNTS_DIR / name
        if not dest.exists():
            MOUNTS_DIR.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["git", "clone", "-q", source, str(dest)], capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError("git clone failed: " + r.stderr.strip())
        path = str(dest)
        remote = source
    else:
        p = Path(source).expanduser().resolve()
        if not p.exists():
            raise RuntimeError(f"path does not exist: {p}")
        name = name or p.name
        path = str(p)
        rc, out, _ = gitops.run(["remote", "get-url", "origin"], cwd=p)
        remote = out if rc == 0 else None
    if any(m["name"] == name for m in mounts):
        raise RuntimeError(f"mount '{name}' already exists (memoryctl mount rm {name})")
    entry = {"name": name, "path": path.replace(str(config.HOME), "~", 1), "readOnly": read_only, "autoPull": auto_pull}
    if remote:
        entry["remote"] = remote
    if only:
        entry["only"] = only
    if subdir:
        entry["subdir"] = subdir
    if exclude:
        entry["exclude"] = exclude
    if collapse:
        entry["collapse"] = collapse
    mounts.append(entry)
    config.save(cfg)
    return entry


def remove(name):
    cfg = config.load()
    before = len(cfg.get("mounts", []))
    cfg["mounts"] = [m for m in cfg.get("mounts", []) if m["name"] != name]
    config.save(cfg)
    return len(cfg["mounts"]) < before


def set_option(name, key, value):
    import json as _json
    cfg = config.load()
    for m in cfg.get("mounts", []):
        if m["name"] == name:
            try:
                value = _json.loads(value)
            except Exception:  # noqa: BLE001
                if "," in str(value):
                    value = [x.strip() for x in str(value).split(",") if x.strip()]
            m[key] = value
            config.save(cfg)
            return m
    raise RuntimeError(f"no such mount: {name}")
