---
name: elden-ring-mod-merge
description: Merges two Elden Ring mods built on the same base (the unmodded game or an overhaul such as The Convergence) into one mod folder, three-way against that base - regulation.bin params, behavior graphs (c0000.behbnd), TAE animations (anibnd), HKX / effect / text binders, HKS scripts and nameid tables - with conflict analysis, user decisions, independent verification, backup and rollback. Use when a user wants to combine, merge or stack two Elden Ring mods, asks why two mods overwrite each other or cannot be used together, or mentions regulation.bin, c0000.hks, behbnd, anibnd or ME3 / ModEngine mod folders together with two mods (艾尔登法环 mod 合并).
---

# Elden Ring two-mod merge

Mod loaders (ME3, ModEngine 2, YAFSML) replace whole files by path: when two mods ship the same file, the one
loaded last silently wins and the other mod breaks. This skill rebuilds every such file three-way (base, A, B)
with the bundled `ermerge` tool and Python scripts, then verifies the result independently.

## Hard rules

- **Step 0 comes first.** Before touching anything, tell the user what to prepare using the message in
  [PREREQUISITES.md](PREREQUISITES.md), in the user's language, and wait until they confirm. Never guess the base.
- Inputs are read-only: the two mods, the base and the game are never modified. Everything is written to a
  workspace folder; the game's mod folder is written only by `deploy.py --yes` after the user approves.
- Every gameplay-level choice belongs to the user. Present options with a recommendation, record the answer in
  `decisions.md` ([template](templates/decisions.md)) before building.
- Report only what was verified. Nothing here tests in game: say so, and mark unverified claims `[UNKNOWN]`.
- A merged mod contains both authors' work: before the user shares it, remind them to get permission.

## Workflow

Copy this checklist and tick it off:

```
- [ ] 0 prerequisites confirmed (PREREQUISITES.md)
- [ ] 1 setup.py ok (tool built, smoke test passed)
- [ ] 2 inventory.py run; inventory.md and the mods' installers/readmes read
- [ ] 3 analyze.py run; analysis/SUMMARY.md leads reviewed in the code
- [ ] 4 decisions asked (with side effects), recorded in decisions.md, applied to plan.json / hooks
- [ ] 5 build.py finished "build ok" (merge, verify, hooks + hook diff check, luac, cross-file checks)
- [ ] 6 user approved; deploy.py --yes; loader profile updated
- [ ] 7 hand-over: results, in-game test list, rollback command
```

Commands (all take `--workspace W`; W = a new empty folder outside the game and the mods):

1. `python scripts/setup.py --workspace W --smithbox <Smithbox folder> --game <...\ELDEN RING\Game> [--dotnet <dotnet.exe>]`
2. `python scripts/inventory.py --workspace W --a <mod A> --b <mod B> [--base <base mod>] --a-name .. --b-name .. --base-name ..`
3. `python scripts/analyze.py --workspace W`
4. edit `W/plan.json` (strategies, sides, resolutions) and `W/hooks/post_merge.py` ([template](templates/post_merge.py))
5. `python scripts/build.py --workspace W` - exit 3 means decisions are still missing; reports in `W/reports/`
   (BUILD.md, VERIFY.md, hooks.diff, CROSSCHECK.md)
6. `python scripts/deploy.py --workspace W --target <game mod folder>` (preview), then add `--yes`

Details for each step, including what to read and ask: [WORKFLOW.md](WORKFLOW.md).

## Choosing sides (defaults the analysis may overrule)

| file | knob | pick |
|---|---|---|
| `chr/c0000.behbnd.dcx` | `keep` | the mod whose scripts or DLL hard-code behavior IDs (analysis lists them and marks a direction that would renumber them **blocked**, even with 0 conflicts); else the one whose dry-run as KEEP has no conflicts; else the one with more changes |
| `action/*nameid.txt` | `keep` | same side as the behavior KEEP |
| `regulation.bin` | `primary` | the side whose rows still carry names (row names are editor-only) |
| `c0000.anibnd.dcx`, other binders | `primary` | the side with more changes (header, entry order and compression follow it; when both sides only add entries to an ID-sorted binder, either side gives the same bytes) |
| `.hks` / text | `encoding_from` | the side the merged text mostly comes from (BOM / line endings are copied from it; the game accepts either) |

Why and how each format is merged: [FILE-TYPES.md](FILE-TYPES.md). Conflict types and how to present them:
[CONFLICTS.md](CONFLICTS.md). Command and `plan.json` reference: [TOOLS.md](TOOLS.md). A complete real run
(The Convergence 3.0.2 + Nightreign Movement + Suncatcher Mode): [EXAMPLE.md](EXAMPLE.md).
