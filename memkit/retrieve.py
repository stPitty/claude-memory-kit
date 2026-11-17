"""Keyword retrieval over memory for the UserPromptSubmit hook.

Core memory (root files, current project) is already in context via SessionStart; this module
surfaces *deferred* files (deeper vault dirs, other projects, shared mounts) whose name,
description, tags/aliases or body match the words of the user's prompt — so the agent reads
relevant memory without being told to.
"""
import json
import re
from pathlib import Path
from . import config, frontmatter, mounts, vault

_WORD = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9_\-]{2,}", re.I)

STOP = set("""
the and for with that this from what when where which have has not are was were you your our
can will would should could into about just like make need want how why who all any some more
это как что для или если только чтобы тоже также чем там тут вот так уже еще ещё надо нужно
мне меня мой моя мое моё мои тебе тебя твой твоя ты вы вам вас нас нам они она оно его еее
есть быть был была были будет всё все всех всем при над под про без через после перед между
давай сделай посмотри можешь пожалуйста хочу хотел просто сейчас потом всегда когда где какие
который которая которые этот эта эти того тому этом очень более менее кто чего чем
""".split())


def _stem(w):
    w = w.lower().replace("ё", "е")
    # crude stemming: inflected Russian/English forms share a 5-char prefix often enough
    return w[:5] if len(w) >= 6 else w


def terms(text):
    out = set()
    for w in _WORD.findall(text or ""):
        lw = w.lower()
        if lw in STOP or lw.isdigit():
            continue
        out.add(_stem(lw))
        for piece in re.split(r"[-_]", lw):
            if len(piece) >= 3 and piece not in STOP:
                out.add(_stem(piece))
    return out


def _meta_text(meta):
    if not isinstance(meta, dict):
        return ""
    vals = []
    for k in ("description", "tags", "aliases", "type"):
        v = meta.get(k)
        if isinstance(v, list):
            vals.extend(str(x) for x in v)
        elif v:
            vals.append(str(v))
    md = meta.get("metadata")
    if isinstance(md, dict):
        vals.extend(str(x) for x in md.values())
    return " ".join(vals)


def _candidates(slug):
    """Yield (path, origin) for files that are NOT already compiled into context in full."""
    v = config.vault()
    core = set(vault.core_files())
    pdir = vault.project_dir(slug)
    for p in sorted(v.rglob("*.md")):
        rel = p.relative_to(v)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if p.name in (vault.INDEX, vault.ARCHIVE) or p in core:
            continue
        if pdir and p.parent == pdir:
            continue
        if vault.unindexed_ancestor(rel) is not None:
            continue
        yield p, "vault"
    for m in mounts.active(slug):
        r = mounts.root(m)
        if not r.exists():
            continue
        excl = m.get("exclude") or []
        for p in sorted(r.rglob("*.md")):
            rel = p.relative_to(r)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if any(rel.parts[0] == e or rel.as_posix().startswith(e.rstrip("/") + "/") for e in excl):
                continue
            yield p, f"mount:{m['name']}"


def search(prompt, slug, limit=5):
    q = terms(prompt)
    if not q:
        return []
    results = []
    for p, origin in _candidates(slug):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        meta, body = frontmatter.parse(text)
        # directory names are shared by every file inside, so they count like body words
        head_terms = terms(p.stem)
        meta_terms = terms(_meta_text(meta))
        body_terms = terms(body) | terms(p.parent.name) | terms(p.parent.parent.name)
        hit_head = q & head_terms
        hit_meta = (q & meta_terms) - hit_head
        hit_body = (q & body_terms) - hit_head - hit_meta
        score = 3 * len(hit_head) + 2 * len(hit_meta) + min(len(hit_body), 4)
        if not (hit_head or hit_meta) and len(hit_body) < 3:
            continue
        if score < 4:
            continue
        desc = str(meta.get("description", "")).strip() if isinstance(meta, dict) else ""
        results.append({"path": p, "origin": origin, "score": score, "desc": desc, "body": body.strip(),
                        "hits": sorted(hit_head | hit_meta | hit_body)})
    results.sort(key=lambda r: (-r["score"], str(r["path"])))
    return results[:limit]


# ---------- per-session dedupe ----------

def _seen_path(session_id):
    d = config.state_dir() / "recall-on-prompt"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", session_id or "nosession")
    return d / f"{safe}.json"


def load_seen(session_id):
    try:
        return set(json.loads(_seen_path(session_id).read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def save_seen(session_id, seen):
    try:
        _seen_path(session_id).write_text(json.dumps(sorted(seen)), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        config.log(f"recall-on-prompt: cannot save seen set: {e!r}")


def render(results, seen, max_chars=7000, inline_max=3500):
    """Render matches; inline the bodies of small top matches not shown earlier this session."""
    lines = ["<memory_recall_on_prompt>",
             "Memory files matching words of this prompt (keyword search over deferred memory). "
             "Use what applies; Read any listed-but-not-inlined file whose description fits the task before answering."]
    used = sum(len(x) for x in lines)
    newly = set()
    for r in results:
        key = str(r["path"])
        hdr = f'<file path="{key}" origin="{r["origin"]}" matched="{", ".join(r["hits"][:8])}">'
        desc = f"<description>{r['desc']}</description>" if r["desc"] else ""
        body = ""
        if key not in seen and len(r["body"]) <= inline_max and used + len(r["body"]) + 300 < max_chars:
            body = r["body"]
            newly.add(key)
        elif key in seen:
            body = "(content already shown earlier in this session)"
        else:
            body = "(not inlined — Read it if relevant)"
        block = "\n".join(x for x in (hdr, desc, body, "</file>") if x)
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    lines.append("</memory_recall_on_prompt>")
    return "\n".join(lines), newly
