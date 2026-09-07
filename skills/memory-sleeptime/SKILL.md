---
name: memory-sleeptime
description: Configure background reflection triggers (off | step-count | compaction-event | both), the step count and the model used for reflection.
argument-hint: "[off|step-count|compaction-event|both] [--step-count N] [--model sonnet]"
disable-model-invocation: true
allowed-tools: Bash(__MEMORYCTL__ *)
---

Current reflection settings:
```!
__MEMORYCTL__ config
```

Requested change: `$ARGUMENTS`. If arguments were given, apply them with `__MEMORYCTL__ sleeptime $ARGUMENTS` and show the result. If none, explain the current settings to the user in Russian in two or three sentences:
- `compaction-event` (default): reflection runs when the context gets compacted;
- `step-count`: every N turns (`stepCount`);
- `both` / `off`.
