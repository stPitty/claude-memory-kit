"""Thin git helpers over the memory vault."""
import subprocess
from . import config


def run(args, cwd=None, check=False, timeout=60):
    cwd = str(cwd or config.vault())
    r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def is_repo(cwd=None):
    rc, out, _ = run(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
    return rc == 0 and out == "true"


def head(cwd=None):
    rc, out, _ = run(["rev-parse", "--short", "HEAD"], cwd=cwd)
    return out if rc == 0 else None


def status_porcelain(cwd=None):
    rc, out, _ = run(["status", "--porcelain"], cwd=cwd)
    return out if rc == 0 else ""


def is_dirty(cwd=None):
    return bool(status_porcelain(cwd))


def commit_all(message, author=None, cwd=None, no_verify=False):
    """Stage everything and commit. Returns the new short hash or None if nothing to commit."""
    if not is_dirty(cwd):
        return None
    run(["add", "-A"], cwd=cwd)
    args = ["commit", "-q", "-m", message]
    if author:
        args += ["--author", author]
    if no_verify:
        args.append("--no-verify")
    rc, out, err = run(args, cwd=cwd)
    if rc != 0:
        config.log(f"git commit failed: {err}")
        return None
    return head(cwd)


def log_lines(n=10, cwd=None):
    rc, out, _ = run(["log", f"-{n}", "--date=short", "--format=%h %ad %s"], cwd=cwd)
    return out.splitlines() if rc == 0 else []


def last_commit_date(cwd=None):
    rc, out, _ = run(["log", "-1", "--format=%ci"], cwd=cwd)
    return out if rc == 0 and out else None


def commit_count(cwd=None):
    rc, out, _ = run(["rev-list", "--count", "HEAD"], cwd=cwd)
    return int(out) if rc == 0 and out.isdigit() else 0
