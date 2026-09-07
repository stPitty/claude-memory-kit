---
name: memory-reflect
description: Run the sleep-time reflection now over the current conversation — extract corrections, preferences and facts into the memory vault and commit them.
argument-hint: "[optional focus]"
disable-model-invocation: true
context: fork
agent: memory-reflection
background: false
---

Reflect on the conversation in your context (this is a fork of the primary session; no transcript digest file is needed). Focus hint from the user: "$ARGUMENTS". Memory vault: `__VAULT__` (`$MEMORY_DIR`). Follow your five phases, commit once with trailers, or report "no changes needed".
