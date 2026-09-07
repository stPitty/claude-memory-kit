---
name: memory-status
description: Show the memory vault status — tree, token budget, git history, reflection state.
disable-model-invocation: true
allowed-tools: Bash(__MEMORYCTL__ *)
---

```!
__MEMORYCTL__ status
```

Recent memory commits:
```!
__MEMORYCTL__ log -n 10
```

Summarize the above for the user in a few lines (Russian): size vs budget, last reflection, anything needing attention (contract errors, dirty files). Do not modify anything.
