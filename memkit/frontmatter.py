"""Minimal YAML-frontmatter parser/serializer (subset sufficient for memory files)."""
import re

_KV = re.compile(r"^([A-Za-z0-9_\-]+):\s*(.*)$")


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _scalar(v):
    v = v.strip()
    if v in ("true", "True", "yes"):
        return True
    if v in ("false", "False", "no"):
        return False
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_unquote(x) for x in inner.split(",") if x.strip()] if inner else []
    return _unquote(v)


def split(text):
    """Return (frontmatter_lines or None, body)."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    return None, text


def parse(text):
    """Return (meta: dict|None, body: str). meta is None when there is no frontmatter."""
    fm, body = split(text)
    if fm is None:
        return None, text
    meta = {}
    # stack of (indent, container, pending_key)
    stack = [(0, meta)]
    pending = None  # (container, key) for a "key:" with no inline value
    for raw in fm:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("- "):
            if pending is not None:
                cont, key = pending
                if not isinstance(cont.get(key), list):
                    cont[key] = []
                cont[key].append(_unquote(line[2:]))
            continue
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        cur = stack[-1][1]
        m = _KV.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            cur[key] = {}
            stack.append((indent + 1, cur[key]))
            pending = (cur, key)
        else:
            cur[key] = _scalar(val)
            pending = None
    return meta, body


def serialize(meta, body):
    out = ["---"]
    for k, v in meta.items():
        if isinstance(v, dict):
            out.append(f"{k}:")
            for k2, v2 in v.items():
                out.append(f"  {k2}: {v2}")
        elif isinstance(v, list):
            out.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        elif isinstance(v, bool):
            out.append(f"{k}: {'true' if v else 'false'}")
        else:
            out.append(f"{k}: {v}")
    out.append("---")
    return "\n".join(out) + "\n" + body.lstrip("\n")
