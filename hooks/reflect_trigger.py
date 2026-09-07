#!/usr/bin/env python3
"""PreCompact + Stop hook: decide whether to launch a background reflection (Letta sleep-time compute).
trigger = compaction-event (default) | step-count | both | off"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memkit import config, reflect  # noqa: E402


def main():
    if config.reflecting():
        return
    data = config.read_hook_input()
    event = data.get("hook_event_name")
    cfg = config.load()["reflection"]
    trig = cfg.get("trigger", "compaction-event")
    if trig == "off":
        return
    tp = data.get("transcript_path")
    sid = data.get("session_id", "")
    cwd = data.get("cwd", "")
    if not tp or not sid:
        return
    if event == "PreCompact" and trig in ("compaction-event", "both"):
        reflect.trigger_async(tp, sid, cwd, f"compaction-event ({data.get('trigger', 'auto')})")
        return
    if event == "Stop" and trig in ("step-count", "both"):
        sd = config.state_dir() / "counters"
        sd.mkdir(parents=True, exist_ok=True)
        cf = sd / f"{sid}.txt"
        n = 0
        if cf.exists():
            try:
                n = int(cf.read_text().strip() or 0)
            except Exception:  # noqa: BLE001
                n = 0
        n += 1
        if n >= int(cfg.get("stepCount", 25)):
            cf.write_text("0")
            reflect.trigger_async(tp, sid, cwd, f"step-count ({n} turns)")
        else:
            cf.write_text(str(n))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        config.log(f"reflect_trigger error: {e!r}")
        sys.exit(0)
