"""Memory vault: layout contract, compilation into context, tree, validation, budget.

Layout contract (memfs-v2, ported from Letta):
  - Root and child MEMORY.md are frontmatter-free indexes.
  - Every other memory .md file has `name` + `description` frontmatter (name == file stem).
  - A child directory is memory only when it contains MEMORY.md.
  - Root .md files (except MEMORY.md / ARCHIVE.md) are core memory: injected in full every session.
  - projects/<slug>/*.md are core memory *for that project* (injected in full when cwd matches).
  - Everything else is deferred: only path + description are visible; content is read on demand.
"""
import re
from pathlib import Path
from . import config, frontmatter, gitops, mounts

INDEX = "MEMORY.md"
ARCHIVE = "ARCHIVE.md"
PROJECTS = "projects"
ALLOWED_META = {"name", "description", "metadata", "modified", "read_only", "tags", "type", "aliases", "created"}

SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "API key (sk-...)"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}"), "GitLab token"),
    (re.compile(r"\bxox[abp]-[A-Za-z0-9\-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\b(password|passwd|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+=]{12,}"), "password/secret assignment"),
]


# ---------- filesystem helpers ----------

def _is_hidden(p: Path):
    return any(part.startswith(".") for part in p.parts)


def is_memory_dir(d: Path):
    v = config.vault()
    return d == v or (d / INDEX).exists()


def md_files(d: Path):
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".md")


def subdirs(d: Path):
    return sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith("."))


def read_meta(p: Path):
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None, ""
    return frontmatter.parse(text)


def description(p: Path):
    meta, _ = read_meta(p)
    if isinstance(meta, dict):
        return str(meta.get("description", "")).strip()
    return ""


def is_read_only(p: Path):
    meta, _ = read_meta(p)
    return bool(isinstance(meta, dict) and meta.get("read_only") is True)


def core_files():
    """Root core files, persona first."""
    v = config.vault()
    files = [p for p in md_files(v) if p.name not in (INDEX, ARCHIVE)]
    files.sort(key=lambda p: (0 if p.stem == "persona" else 1, p.name))
    return files


def project_dir(slug):
    d = config.vault() / PROJECTS / slug
    return d if is_memory_dir(d) else None


def unindexed_ancestor(rel: Path):
    """Return the first directory (relative) between vault root and `rel` that lacks MEMORY.md, or None.
    The file itself may be the MEMORY.md of its own directory."""
    v = config.vault()
    parts = list(rel.parts[:-1])
    if rel.name == INDEX and parts:
        parts = parts[:-1]  # its own dir is allowed to be un-indexed yet
    cur = v
    for part in parts:
        cur = cur / part
        if not (cur / INDEX).exists():
            return cur.relative_to(v)
    return None


# ---------- tree rendering ----------

def render_tree(root: Path = None, show_root=True, skip_root_files=True):
    v = config.vault()
    root = root or v
    lines = []
    if show_root:
        lines.append(f"{root}/")

    def walk(d: Path, prefix: str):
        entries = []
        if not (skip_root_files and d == v):
            for f in md_files(d):
                entries.append(("f", f))
        for sd in subdirs(d):
            entries.append(("d", sd))
        for i, (kind, p) in enumerate(entries):
            last = i == len(entries) - 1
            branch = "└── " if last else "├── "
            ext = "    " if last else "│   "
            if kind == "f":
                if p.name == INDEX:
                    lines.append(f"{prefix}{branch}{p.name}")
                else:
                    desc = description(p)
                    ro = " [read_only]" if is_read_only(p) else ""
                    lines.append(f"{prefix}{branch}{p.name}{ro}" + (f" — {desc}" if desc else ""))
            else:
                if is_memory_dir(p):
                    lines.append(f"{prefix}{branch}{p.name}/")
                    walk(p, prefix + ext)
                else:
                    lines.append(f"{prefix}{branch}{p.name}/  (no MEMORY.md — NOT memory, invisible until indexed)")

    walk(root, "")
    return "\n".join(lines)


# ---------- compilation ----------

def _block(tag, p: Path, body_only=False):
    meta, body = read_meta(p)
    desc = str(meta.get("description", "")).strip() if isinstance(meta, dict) else ""
    ro = isinstance(meta, dict) and meta.get("read_only") is True
    out = [f"<{tag}>", f"<projection>{p}</projection>"]
    if desc:
        out.append(f"<description>{desc}</description>")
    if ro:
        out.append("<read_only>true</read_only>")
    out.append(body.strip())
    out.append(f"</{tag}>")
    return "\n".join(out)


def estimate_tokens(text):
    bpt = config.load()["budget"]["bytesPerToken"]
    return len(text.encode("utf-8")) // bpt


def compile_context(cwd=None, extra_notes=None, pull_mounts=False):
    """Compile the memory vault into a context block (Letta system-prompt-compilation analogue)."""
    cfg = config.load()
    v = config.vault()
    slug = config.project_slug(cwd)
    parts = []
    parts.append("<memory_system>")
    parts.append(
        f"Reminder: <projection> is the local path of a memory file. Memory vault: {v} (git-tracked).\n"
        "Root files below are your core memory and are always in context. Files in indexed subdirectories are deferred: "
        "only their path + description is shown — read them on demand with Read when the description matches the task.\n"
        "Editing memory does NOT change your behavior in the current turn: it is recompiled at the next session start. "
        "Write for your future self, then keep acting on your decision now. Edits inside the vault are auto-committed; "
        "uncommitted edits are not persisted memory.\n"
        "Recall (past conversations) is separate from memory: use the memory-recall subagent or /memory-recall before assuming you don't know something."
    )

    persona = v / "persona.md"
    if persona.exists():
        parts.append(_block("self", persona))

    parts.append("<memory>")
    for p in core_files():
        if p == persona:
            continue
        parts.append(_block(p.stem, p))

    pdir = project_dir(slug)
    if pdir:
        parts.append(f'<project slug="{slug}" path="{pdir}">')
        idx = pdir / INDEX
        parts.append(f"<index>\n{idx.read_text(encoding='utf-8').strip()}\n</index>")
        for p in md_files(pdir):
            if p.name == INDEX:
                continue
            parts.append(_block(p.stem, p))
        parts.append("</project>")
    else:
        parts.append(
            f'<project slug="{slug}" path="{v / PROJECTS / slug}" exists="false">'
            f"No project memory yet for '{slug}'. To create it: write {PROJECTS}/{slug}/MEMORY.md first (index), "
            f"then topic files; register the directory in {PROJECTS}/MEMORY.md.</project>"
        )

    parts.append("<external_projection>")
    parts.append(render_tree())
    parts.append("</external_projection>")
    parts.append("</memory>")

    shared, shared_notes = mounts.compile_section(slug, do_pull=pull_mounts)
    if shared:
        parts.append(shared)
    extra_notes = list(extra_notes or []) + shared_notes

    body_so_far = "\n".join(parts)
    tokens = estimate_tokens(body_so_far)
    target = cfg["budget"]["targetTokens"]
    warn = cfg["budget"]["warnTokens"]

    meta = ["<memory_metadata>"]
    meta.append(f"- MEMORY_DIR: {v}")
    meta.append(f"- Project slug: {slug} (project memory: {'yes' if pdir else 'no'})")
    if gitops.is_repo():
        meta.append(f"- Memory revision: {gitops.head()} ({gitops.commit_count()} commits), last commit {gitops.last_commit_date()}")
        dirty = gitops.status_porcelain()
        meta.append(f"- Uncommitted changes: {'none' if not dirty else str(len(dirty.splitlines())) + ' files'}")
    else:
        meta.append("- WARNING: vault is not a git repository (history/rollback unavailable)")
    meta.append(f"- Compiled: {config.now_iso()}")
    meta.append(f"- Core memory size: ~{tokens} tokens (target ≤ {target}, warn at {warn})")
    if tokens > warn:
        meta.append("- ⚠ Core memory is meaningfully over budget: run /memory-doctor (move whole files to deferred, delete stale; do not compress).")
    rc = recall_stats()
    meta.append(f"- Recall: {rc['sessions']} past sessions / {rc['user_messages']} user messages stored in {config.projects_dir()} (searchable via memory-recall)")
    st = last_reflection()
    if st:
        meta.append(f"- Last reflection: {st}")
    meta.append(f"- Reflection trigger: {cfg['reflection']['trigger']} (stepCount={cfg['reflection']['stepCount']})")
    am = mounts.active(slug)
    if am or mounts.all_mounts():
        meta.append(f"- Shared memory mounts: {len(am)} active for this project of {len(mounts.all_mounts())} configured (memoryctl mount list)")
    for n in (extra_notes or []):
        meta.append(f"- {n}")
    meta.append("</memory_metadata>")
    parts.extend(meta)
    parts.append("</memory_system>")
    text = "\n".join(parts)
    return text, {"tokens": tokens, "slug": slug, "project_memory": bool(pdir)}


def recall_stats():
    pd = config.projects_dir()
    sessions = 0
    user_msgs = 0
    if pd.exists():
        for f in pd.glob("*/*.jsonl"):
            sessions += 1
            try:
                with open(f, "rb") as fh:
                    for line in fh:
                        if b'"type":"user"' in line and b'"tool_result"' not in line:
                            user_msgs += 1
            except Exception:  # noqa: BLE001
                pass
    return {"sessions": sessions, "user_messages": user_msgs}


def last_reflection():
    p = config.state_dir() / "last-reflection.json"
    if not p.exists():
        return None
    try:
        import json
        d = json.loads(p.read_text(encoding="utf-8"))
        return f"{d.get('at')} — {d.get('outcome')}"
    except Exception:  # noqa: BLE001
        return None


# ---------- budget ----------

def token_report(cwd=None):
    """Per-file token estimate of what gets injected (core + project core + tree)."""
    rows = []
    v = config.vault()
    for p in core_files():
        rows.append((str(p.relative_to(v)), estimate_tokens(p.read_text(encoding="utf-8"))))
    slug = config.project_slug(cwd)
    pdir = project_dir(slug)
    if pdir:
        for p in md_files(pdir):
            rows.append((str(p.relative_to(v)), estimate_tokens(p.read_text(encoding="utf-8"))))
    tree = render_tree()
    rows.append(("<external_projection tree>", estimate_tokens(tree)))
    idx = v / INDEX
    if idx.exists():
        rows.append(("MEMORY.md (loaded by Claude Code auto-memory)", estimate_tokens(idx.read_text(encoding="utf-8"))))
    total = sum(t for _, t in rows)
    return rows, total


# ---------- validation ----------

_LINK = re.compile(r"\[[^\]]*\]\(([^)]+\.md)\)|\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def links_in(text):
    out = []
    for m in _LINK.finditer(text):
        target = m.group(1) or m.group(2)
        if target:
            out.append(target.strip())
    return out


def validate(paths=None):
    """Validate the vault contract. Returns list of (level, relpath, message). level in {error, warning}."""
    v = config.vault()
    issues = []
    all_files = []
    if paths:
        for p in paths:
            p = Path(p).expanduser().resolve()
            if p.is_file():
                all_files.append(p)
    else:
        for p in v.rglob("*.md"):
            if _is_hidden(p.relative_to(v)):
                continue
            all_files.append(p)

    for p in all_files:
        rel = p.relative_to(v)
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            issues.append(("error", str(rel), f"cannot read: {e}"))
            continue
        for rx, label in SECRET_PATTERNS:
            if rx.search(text):
                issues.append(("error", str(rel), f"looks like a secret ({label}) — never store secrets in memory"))
        if p.name == INDEX:
            meta, _ = frontmatter.parse(text)
            if meta is not None:
                issues.append(("error", str(rel), "MEMORY.md must be a frontmatter-free index"))
            # broken links
            for t in links_in(text):
                target = (p.parent / t) if not t.endswith(".md") and (p.parent / t).exists() else (p.parent / t)
                if not target.suffix:
                    target = target.with_suffix(".md")
                if not target.exists() and not (v / t).exists() and not (v / (t + ".md")).exists():
                    issues.append(("warning", str(rel), f"broken link: {t}"))
            continue
        meta, body = frontmatter.parse(text)
        if meta is None:
            issues.append(("error", str(rel), "missing frontmatter: every memory file needs `name` and `description`"))
        else:
            if not meta.get("name"):
                issues.append(("error", str(rel), "frontmatter lacks `name`"))
            elif str(meta.get("name")) != p.stem:
                issues.append(("error", str(rel), f"`name: {meta.get('name')}` must equal the file stem `{p.stem}` (wikilinks resolve by filename)"))
            if not str(meta.get("description", "")).strip():
                issues.append(("error", str(rel), "frontmatter lacks `description` (what kind of information lives here)"))
            unknown = set(meta.keys()) - ALLOWED_META
            if unknown:
                issues.append(("warning", str(rel), f"unknown frontmatter keys: {', '.join(sorted(unknown))}"))
        if not body.strip():
            issues.append(("warning", str(rel), "empty body"))
        ua = unindexed_ancestor(rel)
        if ua is not None:
            issues.append(("error", str(rel), f"directory {ua}/ has no MEMORY.md — the file is invisible to the agent"))

    # discoverability: each non-index file should be referenced from its directory's MEMORY.md
    if not paths:
        for p in all_files:
            if p.name in (INDEX,):
                continue
            rel = p.relative_to(v)
            if p.parent == v and p.name in (ARCHIVE, "persona.md") or p.parent == v:
                # root files are core (always in context); indexing is recommended, not required
                idx = v / INDEX
                if idx.exists() and p.name not in idx.read_text(encoding="utf-8") and p.stem not in idx.read_text(encoding="utf-8"):
                    issues.append(("warning", str(rel), "not referenced from MEMORY.md (root) — add an index line"))
                continue
            idx = p.parent / INDEX
            if idx.exists():
                it = idx.read_text(encoding="utf-8")
                if p.name not in it and p.stem not in it:
                    issues.append(("warning", str(rel), f"not referenced from {idx.relative_to(v)} — future you won't find it"))
        # directories with md files but no index
        for d in v.rglob("*"):
            if d.is_dir() and not _is_hidden(d.relative_to(v)) and d != v:
                if any(f.suffix == ".md" for f in d.iterdir() if f.is_file()) and not (d / INDEX).exists():
                    issues.append(("error", str(d.relative_to(v)) + "/", "contains memory files but no MEMORY.md — not memory"))
    return issues


def format_issues(issues):
    if not issues:
        return "OK — vault contract satisfied"
    lines = []
    for level, rel, msg in issues:
        lines.append(f"[{level}] {rel}: {msg}")
    return "\n".join(lines)
