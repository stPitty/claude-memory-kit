---
name: remember
description: Commit something from the current conversation to long-term memory (a correction, a preference, a fact, a rule). Use when the user says "запомни", "remember", "не забудь", or asks to persist a decision.
argument-hint: "[what to remember]"
allowed-tools: Read, Edit, Write, Bash(__MEMORYCTL__ *), Bash(git *)
---

Persist to memory: **$ARGUMENTS** (if empty — infer from the last few turns what the user wants remembered).

The vault is `__VAULT__`; its current state is compiled in the `<memory_system>` block of this context. Three steps:

1. **Decide what exactly to remember.** Classify: correction / preference / fact / rule / project knowledge. Generalize it (not an event log), make it concrete (a command, a path, or *why*), convert relative dates to absolute. If it is derivable from code, git, or a recall search, say so and don't store it.
2. **Pick the right file.** Existing file covering the topic → edit it (fix contradictions at the source; don't append duplicates). Project-specific → `projects/<slug>/` (create `projects/<slug>/MEMORY.md` first if missing and register it in `projects/MEMORY.md`). Person/preferences → root `human-*.md`. Only create a new file when the topic is genuinely distinct; then add its line to the directory's `MEMORY.md` and link related notes with `[[wikilinks]]`. Frontmatter: `name` (== file stem) + `description` (what kind of info). Never store secrets.
3. **Confirm** to the user in one or two sentences: what was written and to which file. The hook auto-commits the edit; it takes effect at the next session start — keep acting on it now.
