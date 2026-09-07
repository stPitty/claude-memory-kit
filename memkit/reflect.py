"""Sleep-time reflection: run the memory-reflection agent over a transcript in the background."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from . import config, gitops, transcript, vault


def _state_paths():
    sd = config.state_dir()
    for sub in ("digests", "reflected", "logs", "counters"):
        (sd / sub).mkdir(parents=True, exist_ok=True)
    return sd


def _lock_acquire(sd):
    lock = sd / "reflect.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text().strip())
            os.kill(pid, 0)
            return None  # alive
        except Exception:  # noqa: BLE001
            lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()))
    return lock


def _record(sd, at, outcome, extra=None):
    d = {"at": at, "outcome": outcome}
    d.update(extra or {})
    (sd / "last-reflection.json").write_text(json.dumps(d, ensure_ascii=False, indent=2))


def trigger_async(transcript_path, session_id, cwd, reason):
    """Spawn a detached reflection process and return immediately."""
    if config.reflecting():
        return False
    sd = _state_paths()
    log = open(sd / "logs" / "spawn.log", "a")
    cmd = [sys.executable, "-m", "memkit.reflect", "--transcript", str(transcript_path),
           "--session", str(session_id), "--cwd", str(cwd or ""), "--reason", reason]
    env = dict(os.environ)
    env["CLAUDE_MEMORY_REFLECTING"] = "1"
    subprocess.Popen(cmd, cwd=str(config.KIT_DIR), env=env, stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    config.log(f"reflection spawned: session={session_id} reason={reason}")
    return True


def run(transcript_path, session_id, cwd, reason, model=None, force=False, from_line=None):
    cfg = config.load()
    rcfg = cfg["reflection"]
    sd = _state_paths()
    at = config.now_iso()
    lock = _lock_acquire(sd)
    if lock is None:
        config.log("reflection skipped: another reflection is running")
        return {"outcome": "skipped: already running"}
    try:
        tp = Path(transcript_path)
        if not tp.exists():
            _record(sd, at, f"skipped: transcript not found {tp}")
            return {"outcome": "skipped: transcript missing"}
        sid = session_id or tp.stem
        state_file = sd / "reflected" / f"{sid}.json"
        prev = {}
        if state_file.exists():
            try:
                prev = json.loads(state_file.read_text())
            except Exception:  # noqa: BLE001
                prev = {}
        start_line = from_line if from_line is not None else (0 if force else int(prev.get("lines_processed", 0)))
        text, stats = transcript.digest(tp, from_line=start_line, max_bytes=rcfg["digestMaxBytes"])
        if stats["conversational"] < rcfg["minNewMessages"] and not force:
            config.log(f"reflection skipped: only {stats['conversational']} new messages in {sid}")
            _record(sd, at, f"skipped: only {stats['conversational']} new messages", {"session": sid})
            return {"outcome": "skipped: too few new messages", "stats": stats}

        stamp = time.strftime("%Y%m%d-%H%M%S")
        digest_path = sd / "digests" / f"{sid[:8]}-{stamp}.md"
        slug = config.project_slug(cwd)
        header = (f"# Transcript digest\n\n- session: {sid}\n- project slug: {slug}\n- cwd: {cwd}\n"
                  f"- lines {start_line + 1}..{stats['lines_total']} of transcript {tp}\n"
                  f"- messages: {stats['user']} user, {stats['assistant']} assistant, {stats['tool_use']} tool calls\n"
                  f"- time span: {stats['first_ts']} .. {stats['last_ts']}\n- trigger: {reason}\n\n")
        digest_path.write_text(header + text, encoding="utf-8")

        head_before = gitops.head()
        prompt = (
            f"Reflection run (trigger: {reason}).\n"
            f"- Memory vault ($MEMORY_DIR): {config.vault()}\n"
            f"- Transcript digest to review: {digest_path}\n"
            f"- Session: {sid}; project slug: {slug}; cwd: {cwd}\n"
            f"- Your current memory (core files + tree) is compiled in the <memory_system> block of this context.\n"
            "Follow your five phases. Read the digest first. Commit once with the required trailers, or make no changes at all."
        )
        model = model or rcfg.get("model") or "sonnet"
        claude = shutil.which("claude") or str(Path.home() / ".claude" / "local" / "claude")
        cmd = [claude, "-p", prompt, "--agent", "memory-reflection", "--model", model,
               "--max-turns", str(rcfg.get("maxTurns", 60)), "--no-session-persistence",
               "--permission-mode", "acceptEdits", "--allowedTools", "Bash", "Edit", "Read",
               "--output-format", "json"]
        env = dict(os.environ)
        env["CLAUDE_MEMORY_REFLECTING"] = "1"
        env["MEMORY_DIR"] = str(config.vault())
        env["CLAUDE_MEMORY_REFLECTION_SESSION"] = sid
        log_path = sd / "logs" / f"reflect-{sid[:8]}-{stamp}.log"
        t0 = time.time()
        with open(log_path, "w", encoding="utf-8") as lf:
            lf.write("$ " + " ".join(cmd[:1] + ["-p", "<prompt>"] + cmd[3:]) + "\n\n")
            lf.flush()
            r = subprocess.run(cmd, cwd=str(config.vault()), env=env, capture_output=True, text=True, timeout=3600)
            lf.write(r.stdout)
            lf.write("\n--- stderr ---\n" + r.stderr)
        result_text = ""
        cost = None
        try:
            j = json.loads(r.stdout)
            result_text = j.get("result", "")
            cost = j.get("total_cost_usd")
        except Exception:  # noqa: BLE001
            result_text = r.stdout[-2000:]
        head_after = gitops.head()
        leftover = None
        if gitops.is_dirty():
            leftover = gitops.commit_all(
                f"chore(reflection): commit leftovers 🔮\n\nReflection left uncommitted edits; committed by claude-memory-kit.\n"
                f"Reviewed transcript: {digest_path}\nSession: {sid}\nGenerated-By: claude-memory-kit", no_verify=True)
            head_after = gitops.head()
        committed = head_before != head_after
        outcome = ("updated memory " + str(head_before) + "→" + str(head_after)) if committed else "no memory changes"
        if r.returncode != 0:
            outcome = f"error rc={r.returncode} (see {log_path.name})"
        state_file.write_text(json.dumps({"lines_processed": stats["lines_total"], "at": at, "digest": str(digest_path)}))
        _record(sd, at, outcome, {"session": sid, "reason": reason, "model": model, "seconds": int(time.time() - t0),
                                  "cost_usd": cost, "log": str(log_path), "summary": result_text[:1500],
                                  "leftover_commit": leftover})
        config.log(f"reflection done: session={sid} {outcome} in {int(time.time() - t0)}s")
        # keep digests for a week
        cutoff = time.time() - 7 * 86400
        for f in (sd / "digests").glob("*.md"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
        return {"outcome": outcome, "summary": result_text, "log": str(log_path), "stats": stats}
    finally:
        try:
            lock.unlink()
        except Exception:  # noqa: BLE001
            pass


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Run a memory reflection over a transcript")
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--session", default=None)
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--reason", default="manual")
    ap.add_argument("--model", default=None)
    ap.add_argument("--force", action="store_true", help="ignore the minimum-new-messages threshold and reflect from line 0")
    ap.add_argument("--from-line", type=int, default=None)
    a = ap.parse_args(argv)
    res = run(a.transcript, a.session, a.cwd, a.reason, model=a.model, force=a.force, from_line=a.from_line)
    print(json.dumps({k: v for k, v in res.items() if k != "summary"}, ensure_ascii=False))
    if res.get("summary"):
        print("\n" + res["summary"])


if __name__ == "__main__":
    main()
