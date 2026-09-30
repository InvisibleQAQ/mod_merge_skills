# Workflow in detail

Paths below are relative to the skill folder; `W` is the workspace. Scripts print what they did; read their
reports rather than re-deriving facts by hand.

## Contents
1. Setup
2. Inventory
3. Analysis
4. Decisions
5. Build
6. Deploy
7. Hand-over
8. Re-running after a mod update

## 1. Setup

`python scripts/setup.py --workspace W --smithbox S --game G [--dotnet D]`

- Builds `ermerge` into `W/.kit/bin` against the libraries in the Smithbox folder (the target framework is read
  from `Andre.SoulsFormats.dll`; `oo2core_6_win64.dll` comes from the game folder) and writes `W/kit.json`.
- Smoke test: re-encrypts the game's `regulation.bin` in memory. Failure means a broken Smithbox copy or a
  missing native library; do not continue.

## 2. Inventory

`python scripts/inventory.py --workspace W --a A --b B [--base BASE] --a-name .. --b-name .. --base-name ..`

Read `W/inventory.md`:

- `only_a` / `only_b` / `same` / `one_changed`: copied as they are. Nothing to decide unless a decision later
  says otherwise (take + `drop_entries`, `exclude`, or a hook patch).
- `both_changed`: must be merged; `plan.json` got a draft entry with a suggested strategy.
- **Package files outside the mod folder**: read every installer script, `install-files.json`, readme and
  launcher profile. They reveal: native DLLs and how they must be loaded (initializer function, load order),
  edits the installer makes to launcher profiles, optional files, hash-checked install sets. Write the
  launcher-profile changes down for step 6.
- Skipped junk (`*.bak`, `*.backup`, logs, `_DSAS_CACHE`) is never merged or deployed. A `regulation.bin.backup`
  shipped by a mod is junk.

## 3. Analysis

`python scripts/analyze.py --workspace W` -> `W/analysis/SUMMARY.md` (re-run after every plan change).

**Merge dry-runs.** Each both-changed file is merged in memory with the current plan:
- `OK` with stats: mechanical merge works. Stats show what the other side contributes.
- `CONFLICTS`: items both sides changed differently, listed with keys. Each needs a decision (step 4).
- Behavior files are dry-run in both directions. Choose KEEP by: hard-coded IDs in a side's scripts (listed under
  review leads) > the direction without conflicts > the side with more new objects. Record the choice.

**Review leads.** These are heuristics that point at code to read; a file merging cleanly does not mean the
mods work together. Read the code behind every lead:
- *extra scripts redefine/wrap functions the other side changed*: one mod loads an extra script at runtime that
  replaces global functions (wrapping the originals). Its wrapper runs first; wherever it returns without calling
  the original, the other mod's new logic in that function is skipped. For each listed function, find the
  conditions under which the wrapper takes over.
- *buttons read by both sides*: find where each mod reacts to the button (`env(ActionRequest|ActionDuration, ACTION_ARM_X)`,
  DLL input hooks) and whether both react in the same situation (same button, both while moving, ...).
- *behavior variables set by both*: both drive the same selector (e.g. `MoveSpeedIndex`); the last writer each
  frame wins.
- *hard-coded IDs*: numbers compared with `MasterActiveState` or state/event/variable IDs. That side must be the
  behavior KEEP side, and none of its numbers may move.
- *obfuscated*: `string.char(...)`, random names, constant arithmetic. Decode names before judging behaviour
  (evaluate the `string.char` arguments; map the random names through the nameid tables and the behavior dump).
- *FXR IDs*: an effect ID both mods add with different content in different packs. Which copy the game uses is
  unknown; it is a decision.
- *Native DLLs*: they may hook the same game functions; nothing can merge them. Check readmes for known
  incompatibilities; list them in the hand-over.

For large scripts, delegate the reading to a subagent with a read-only brief like:

> Read-only. Base `<path>`, mod A `<paths>`, mod B `<paths>`. For each function in <list> and each lead in
> <SUMMARY section>: what A changed, what B changed, under which conditions each side's code runs or is bypassed,
> and whether both act in the same situation (same input, same variable, same animation event). Quote file:line.
> Verdict per item: no conflict / mechanical / needs a user decision (with precise options). Mark anything not
> verified [UNKNOWN]. Do not assume one mod's code will stay unmodified if a small edit resolves a conflict.

**Write-back checks.** `roundtrip` must print `OK` for every file type being merged. A `DIFF` on a binder,
behavior or regulation means the libraries cannot faithfully rewrite that file: stop and report. The TAE
re-serialisation `INFO` line is informational (only TAE files both sides changed are rewritten, and their
content is verified by signature).

## 4. Decisions

See [CONFLICTS.md](CONFLICTS.md) for the kinds of conflict and how to present them. Then:

1. Ask the user (one question per conflict, recommended option first, consequences in plain words).
2. Write `W/decisions.md` from [templates/decisions.md](templates/decisions.md): every option offered, the
   choice, how it is implemented. Mechanical choices (KEEP side, primary side) go in its second table with the
   reason.
3. Implement, in this order of preference:
   - `plan.json`: `resolve` maps, `primary` / `keep`, `take` + `side`, `drop_entries`, `exclude`, `manual`.
   - `W/hooks/post_merge.py` for code-level decisions ([template](templates/post_merge.py)): smallest possible
     edit at a single choke point (for example an early `do return FALSE end` in the one function that starts a
     feature), anchored on exact bytes that must occur exactly once, with a comment naming the decision.
4. Re-run `analyze.py`; the dry-runs must show no unresolved conflicts.

## 5. Build

`python scripts/build.py --workspace W`

Order: vanilla extraction -> copy one-sided files -> merge -> `verify.py` on the raw merge -> hooks -> `luac -p`.

- Exit 3: a merge still has conflicts, a `take` has no side, or a text merge left conflict hunks. Text conflicts
  are saved to `W/conflicts/<path>`; merge them by hand into `W/resolved/<path>` and set that file's strategy to
  `{"strategy": "manual", "source": "resolved/<path>"}`.
- Verification failure: the merge result differs from the three-way expectation. Investigate the tool and the
  inputs; never patch `staging/` by hand to make it pass.
- `reports/BUILD.md` lists every file and how it was produced; `reports/VERIFY.md` the checks;
  `reports/<file>.log.txt` the behavior merge details (index shifts, state-ID remaps, wrapper nesting).

## 6. Deploy

1. Show the user the result summary and `python scripts/deploy.py --workspace W --target <mod folder>` (preview:
   files overwritten / added). Ask for approval.
2. `... --yes` backs up every overwritten file to `W/backup/<time>/` (with `manifest.tsv`), copies, and re-hashes.
   If the target is not the pristine base (another mod installed on top), it stops unless `--force`.
3. Launcher profile: add what the mods' installers would have added - e.g. ME3 `[[natives]]` entries for each
   DLL with the `initializer` and `load_after` the installer uses; ModEngine 2 `external_dlls`. Show the diff to the
   user before saving. Back up the profile first.
4. Rollback: `python scripts/deploy.py --workspace W --target <mod folder> --rollback --yes` (restores the
   backups, removes added files that were not modified since).

## 7. Hand-over

Tell the user, in their language:
- what was merged and how (per file, from `reports/BUILD.md`), and each decision with its effect;
- what was verified (from `reports/VERIFY.md`) and that nothing was tested in game;
- an in-game test list: each mod's headline features, plus every interplay point from step 3 (shared buttons,
  wrapped functions, shared variables, shared effects);
- known issues that are not caused by the merge (found while reading), marked as such;
- where the backup is and the rollback command; the reminder about sharing permission.

## 8. Re-running after a mod update

Use a new workspace (or re-run `inventory.py --force`, keeping `decisions.md` and `hooks/`). Re-run analysis:
decisions may no longer apply, and hook anchors that no longer match make the build fail on purpose.
