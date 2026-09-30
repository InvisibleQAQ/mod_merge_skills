# mod_merge_skills

Agent skills for merging game mods. Currently:

- [`elden-ring-mod-merge`](elden-ring-mod-merge/SKILL.md) - merges two Elden Ring mods built on the same base
  (the unmodded game or an overhaul such as The Convergence) into one mod folder: `regulation.bin`, behavior
  graphs, TAE animations, animation/effect/text binders, HKS scripts and nameid tables, three-way against the base,
  with conflict analysis, user decisions, independent verification, backup and rollback.

## Install

Copy the `elden-ring-mod-merge` folder into a skills directory, e.g. `~/.claude/skills/` (personal) or
`<project>/.claude/skills/` (project). The agent loads it when a user asks to merge or combine two Elden Ring mods.

## What the user needs

Windows 10/11 x64, Elden Ring, [Smithbox](https://github.com/vawser/Smithbox/releases) (its libraries are used,
not its UI), a .NET SDK at least as new as Smithbox's target, Python 3.9+, Git; optionally Lua 5.1 for script
syntax checks. The skill asks for these first; see [PREREQUISITES.md](elden-ring-mod-merge/PREREQUISITES.md).

## Layout

```
elden-ring-mod-merge/
  SKILL.md             entry point: rules, workflow checklist, commands
  PREREQUISITES.md     what the user must prepare (message template)
  WORKFLOW.md          each step in detail, what to read, what to ask
  FILE-TYPES.md        formats and how each is merged
  CONFLICTS.md         kinds of conflicts, presenting them, implementing answers
  TOOLS.md             script / plan.json / ermerge reference
  EXAMPLE.md           a complete real merge
  templates/           decisions.md record, post_merge.py hook
  scripts/             Python pipeline (setup, inventory, analyze, build, verify, crosscheck, deploy)
  tools/ErMergeKit/    C# source of the ermerge tool (built by scripts/setup.py)
```
