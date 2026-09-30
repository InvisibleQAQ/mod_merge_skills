# Worked example: The Convergence 3.0.2 + Nightreign Movement + Suncatcher Mode

A real merge this skill was built from. Base: The Convergence 3.0.2 (a localized package of it). A = Nightreign
Movement 1.0.0-beta.16, Convergence edition (NRM: sprint/wall-jump/climb system; native DLL + runtime script).
B = Suncatcher Mode 1.4.1 for Convergence 3.0.2 (stance system, katana moveset, third-tier sprint). Each mod
worked alone on the base; installed together, whichever was copied last overwrote ten shared files.

## Inventory

47 files: 33 only NRM (DLL, sounds, 15 `menu_dlc02` text files, talk ESD, `nrm-extension.hks`, DLC effects),
4 only Suncatcher, 10 changed by both: `regulation.bin`, three nameid tables, `c0000.hks`,
`c0000.behbnd.dcx`, `c0000.anibnd.dcx`, `c0000_a0x/a1x/a00_hi.anibnd.dcx` (`a00_hi` not in the base -> vanilla
base). Suncatcher shipped a stray `regulation.bin.backup` (junk). NRM's package: installer scripts,
`install-files.json`, and it adds an ME3 `[[natives]]` entry (`initializer = NrmInitialize`, `load_after` the
base's DLLs).

## Analysis highlights

- All dry-runs OK: regulation +36 rows / 4 changed by Suncatcher; TAE +447 NRM animations; binders pure
  additions; nameid append-only on both sides (colliding numbers -> renumber).
- Behavior: both directions dry-run with 0 conflicts and remap Master_SM stateId 64 -> 87. KEEP NRM / MOVE
  Suncatcher: 233 new objects, 50 changed, Suncatcher's new state 64 becomes 87 (Suncatcher reads no state numbers);
  one slot both wrapped: `Jump_D_Direction_MSG[0]`. KEEP Suncatcher is **blocked**: it would renumber NRM's new
  state 64 (`NRM_SprintStart`), which NRM hard-codes. "0 conflicts" alone does not make a direction usable.
- HKS leads: NRM changed `<preamble>` (split of the module-path line), `ImportModules (redefined)`,
  `NrmInstallConvergence` and top-level code at the end (its loader); its runtime script wraps 11 functions
  Suncatcher changed (`SpeedUpdate`, `ExecJump`, `FallCommonFunction`, ...); NRM hard-codes Master_SM states 31, 42,
  48, 56, 63 (through `local master = GetVariable("MasterActiveState")`) and 64 (`SprintStartMaster`) -> NRM must be
  KEEP; both read L3 (NRM in `NrmTick`, Suncatcher in `SpeedUpdate` / `VGhoMVNB` / ...); Suncatcher's code is
  obfuscated (`string.char`).
- FXR 1800 added by both (NRM in `sfxbnd_commoneffects_dlc02`, Suncatcher in `sfxbnd_c0000`), different textures.
- Reading the wrapped functions (subagent, read-only) showed: both mods start a sprint on L3 while moving; NRM's
  sprint ignores Suncatcher's stance SpEffect; NRM's fall protection caps fall height so Suncatcher's heavy-landing
  roll never fires.

## Decisions asked (user's answers in bold)

1. L3: **drop Suncatcher's third-tier sprint** / drop NRM's L3 toggle / leave both.
   -> hook: `do return FALSE end` at the start of Suncatcher's sprint entry function `NjiwOxnT` (the only function
   that fires the third tier). Side effect found by reading its callers: `SpeedUpdate` does
   `if VGhoMVNB() then NjiwOxnT(TRUE) elseif ...`, so while L3 is held it still skips its speed-index branches;
   offered alternative: patch `VGhoMVNB` too.
2. Crouch after that: restore plain L3 / **keep Suncatcher's ACTION+L3**. -> nothing.
3. NRM sprint during stance: **block it** / allow. -> hook: `and NrmOriginalEnv(1116,102032)==FALSE` appended to
   NRM's sprint-allowed condition.
4. FXR 1800: renumber Suncatcher's / **share NRM's**. -> `take` Suncatcher's `sfxbnd_c0000` with
   `drop_entries: ["f000001800."]`.
5. Heavy landing: **NRM handles it** / remove NRM's roll + disable fall protection. -> nothing.

Mechanical: behavior `keep: a` (hard-coded IDs; the other direction is blocked), nameid `keep: a`, regulation
`primary: a` (Suncatcher stripped all row names), TAE `primary: b` (Suncatcher changed 787 TAE files plus 91
animations, NRM added 447 animations), HKX binders `primary: a` (NRM adds 90 / 270 / 87 entries, Suncatcher
13 / 42 / 7; for pure additions either side gives byte-identical output, measured), `c0000.hks`
`encoding_from: b`.

## plan.json (the parts that differ from the draft)

```json
"regulation.bin": {"strategy": "regulation", "base_source": "base", "primary": "a", "label_b": "Suncatcher 1.4.1"},
"action/script/c0000.hks": {"strategy": "text3", "base_source": "base", "encoding_from": "b"},
"chr/c0000.anibnd.dcx": {"strategy": "tae", "base_source": "base", "primary": "b"},
"sfx/sfxbnd_c0000.ffxbnd.dcx": {"strategy": "take", "side": "b", "drop_entries": ["f000001800."]}
```

analyze's dry-run of the last entry lists exactly `f000001800.fxr` and `f000001800.ffxreslist`.

## Result

- Build: `c0000.hks` merged cleanly by `git merge-file` (verify accounts for NRM's 2 and Suncatcher's 150 changed
  blocks); behavior 36,905 objects = 36,672 (NRM) + 233; TAE 19,442 animations = 18,995 + 447; nameid
  3126 / 2469 / 656 entries; `sfxbnd_c0000` 10 of 12 entries; all verification checks passed; the hook diff is 2
  labelled hunks (`c0000.hks` +1 line at 450, `nrm-extension.hks` 1 line changed at 670); `luac -p` passed (Lua
  5.5 on that machine: approximate).
- Cross-file checks: 0 errors. Warnings, none caused by the merge: SpEffects 100360 / 112045010 referenced by new
  TAE events of both mods but in no regulation (the base references them too); Suncatcher's decoded literals
  `W_AttackBothLightDash` (an event that exists nowhere) and `L_Foot_Target2` / `R_Foot_Target2` (probably bone
  names); FXR 400 / 410 / 420 used by Suncatcher's new events and the base but in no shipped or base pack. Info:
  Suncatcher's 27 references to FXR 1800 now use NRM's copy (decision 4; they belong to the disabled third tier).
- Deploy: 27 files overwritten (backed up, identical to the base package), 20 added; ME3 profiles already had
  NRM's natives entry.
- Hand-over included the in-game test list (L3 sprint, stance + dodge, jumps and landings, walk/run/roll animations
  of every weight class, the NRM log line confirming its script loaded) and three pre-existing issues found while
  reading (one in the base's scripts, one in each mod), reported as not caused by the merge.
