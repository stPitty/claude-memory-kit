---
name: memory-doctor
description: Diagnose and treat memory degradation — budget, redundancy, broken discovery paths, tier placement — without aggressive compression. Use when memory feels bloated, stale or over budget.
disable-model-invocation: true
allowed-tools: Read, Edit, Write, Bash(__MEMORYCTL__ *), Bash(git *)
---

# Memory doctor

Vault: `__VAULT__`. Current compiled state is in `<memory_system>` above.

## Measurements

Token budget per injected file:
```!
__MEMORYCTL__ tokens
```

Contract check:
```!
__MEMORYCTL__ validate || true
```

Recent history:
```!
__MEMORYCTL__ log -n 15
```

## Why detail is load-bearing (read this before cutting anything)

In-context detail does more than carry information. It does at least four things, and byte-counting sweeps only see the first:
1. **Information** — the literal facts stated
2. **Attention anchoring** — makes certain topics feel important to the model when it's reasoning
3. **Semantic priming** — raises the prior on codebase-specific patterns
4. **Reasoning templates** — past examples become heuristics for new bugs; rationale in "why" prose becomes scaffolding

Compression preserves (1) and destroys (2), (3), (4). A compressed prompt can make the agent measurably worse even though the explicit facts are all "still there" in deferred files. **Reference links are NOT equivalent to in-context presence** — they are latent until fetched, and the agent only fetches when it already knows it doesn't know.

## Policy

- Intervene on size **only if core memory is meaningfully over target** (target ≤ 20k tokens; warn ≥ 30k). At or near target, leave it alone. A prompt that feels "a bit long" is almost always better than one aggressively trimmed.
- When reducing: preserve persona and user identity; **preserve the distribution of attention** (if 50% was about topic X, keep it 50%); prefer moving *whole files* to a deferred directory and deleting stale/contradicted content over compressing detailed sections.
- Fix every `[error]` from the validator. Then the `[warning]`s: unreferenced files (add index lines — otherwise future you never finds them), broken links, unknown frontmatter keys.
- Check for redundancy and overlapping descriptions between files; merge only when two files are genuinely the same topic (combine unique details, never rewrite from scratch).
- Tier check: root files that are really project-specific → `projects/<slug>/`; deferred material that is needed on every turn → promote.
- Structural contract: `persona.md` exists; no file/dir name collisions (`foo.md` next to `foo/`); each subdirectory with memory has `MEMORY.md`.
- Ask the user about their **goals for you**, not about structure — the memory is for you, not for them.

Make the edits (hooks auto-commit), re-run `__MEMORYCTL__ validate`, and finish by telling the user that changes apply at the next session start (or `/clear`).
