---
name: memory-init
description: Initialize or reorganize the memory vault — build granular core files about the user and the current project, importing knowledge from past Claude Code sessions with parallel history-analyzer subagents.
disable-model-invocation: true
allowed-tools: Read, Edit, Write, Bash(__MEMORYCTL__ *), Bash(git *), Agent
---

# Initialize memory

Vault: `__VAULT__`. Current state:
```!
__MEMORYCTL__ status
```

Past sessions available for import:
```!
__MEMORYCTL__ sessions --limit 40
```

## Principles

- **Core memory is your core program.** What lands in root files is in context on every turn, in every project. `projects/<slug>/` is in context only inside that project. Deeper directories are deferred.
- **Don't ask what you can discover.** Infer the user's identity from git (`git config user.name/email`, `git shortlog -sn`) and from the transcripts. Learn rules and preferences from observation. Ask the user only about their *goals for you*.
- **Generalize, don't memorize.** "Always use `uv` for Python — chronic failure, never bare `pip`" is memory; "on March 3rd we debugged a crash" is recall.
- **Don't over-prune.** When in doubt, keep the detail. Lost specificity is hard to recover.
- **Granularity.** A non-trivial setup yields 6–10 root files (persona, human-identity, human-prefs-communication, human-prefs-coding, human-prefs-workflow, …) plus per-project files under `projects/<slug>/` (overview, conventions, gotchas, tooling-commands, …). If you end with only 3–5 files, verify you didn't merge distinct topics into generic summaries. Name project directories with the real project name, never `project/`.
- Each rule concrete: a command pattern, a path, or *why*.

## Procedure

1. **Analyze history in parallel.** If there are past sessions, launch 2–4 `memory-history-analyzer` subagents at once, each with a distinct question or slice, writing proposals to `~/.claude/memory-state/init/<n>.md`:
   - "Who is the user, their role, how they communicate, what frustrates them, what they correct?"
   - "What do I know about project <slug>: architecture decisions, conventions, commands, gotchas?"
   - "Which repeatable procedures came up more than once (candidate skills)?"
   - one per large slice of sessions if there are many.
2. **Synthesize — combine, never compress.** Read all proposals. For overlapping items, combine unique details from every proposal; never rewrite a file from scratch. Contradictions → newest wins, note the date.
3. **Write the vault.** Edit the existing root files surgically (persona.md especially). Create project files under `projects/<slug>/` — write `projects/<slug>/MEMORY.md` first, then the files, then register the directory in `projects/MEMORY.md`. Keep `[[wikilinks]]` between related notes. Frontmatter: `name` + `description`.
4. **Validate and commit.** `__MEMORYCTL__ validate` must be clean of errors. Hooks auto-commit each edit; finish with `__MEMORYCTL__ log -n 5`.
5. **Report** the resulting tree (`__MEMORYCTL__ status`) and tell the user changes apply at the next session start.

Focus from the user (optional): $ARGUMENTS
