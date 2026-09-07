---
name: memory-recall
description: Search past conversations (all sessions, all projects) — what was discussed, decided or done before. Use when the user asks "what did we do/decide about X", or refers to something not in memory.
argument-hint: "[query]"
context: fork
agent: memory-recall
background: false
---

Recall request: **$ARGUMENTS**

Use needle + expand over the transcripts (`__MEMORYCTL__ search / expand / sessions`) and return the strict report format (Answer / Findings / When discussed / How it ended).
