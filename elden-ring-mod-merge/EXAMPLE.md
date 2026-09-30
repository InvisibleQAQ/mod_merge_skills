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
- Behavior: KEEP NRM / MOVE Suncatcher -> 0 conflicts (233 new objects, 50 changed; Master_SM stateId 64
  collides -> 87; one slot both wrapped: `Jump_D_Direction_MSG[0]`). KEEP Suncatcher -> conflicts.
- HKS leads: NRM's runtime script wraps 11 functions Suncatcher changed (`SpeedUpdate`, `ExecJump`,
  `FallCommonFunction`, ...); NRM hard-codes `SprintStartMaster=64` (-> NRM must be KEEP); both read L3;
  Suncatcher's code is obfuscated (`string.char`).
- FXR 1800 added by both (NRM in `sfxbnd_commoneffects_dlc02`, Suncatcher in `sfxbnd_c0000`), different textures.
- Reading the wrapped functions (subagent, read-only) showed: both mods start a sprint on L3 while moving; NRM's
  sprint ignores Suncatcher's stance SpEffect; NRM's fall protection caps fall height so Suncatcher's heavy-landing
  roll never fires.

## Decisions asked (user's answers in bold)

1. L3: **drop Suncatcher's third-tier sprint** / drop NRM's L3 toggle / leave both.
   -> hook: `do return FALSE end` at the start of Suncatcher's sprint entry function (its only entry point).
2. Crouch after that: restore plain L3 / **keep Suncatcher's ACTION+L3**. -> nothing.
3. NRM sprint during stance: **block it** / allow. -> hook: `and NrmOriginalEnv(1116,102032)==FALSE` appended to
   NRM's sprint-allowed condition.
4. FXR 1800: renumber Suncatcher's / **share NRM's**. -> `take` Suncatcher's `sfxbnd_c0000` with
   `drop_entries: ["f000001800."]`.
5. Heavy landing: **NRM handles it** / remove NRM's roll + disable fall protection. -> nothing.

Mechanical: behavior `keep: a` (hard-coded ID), nameid `keep: a`, regulation `primary: a` (Suncatcher stripped
all row names), TAE and binders `primary: b` (more changes), `c0000.hks` `encoding_from: b`.

## plan.json (the parts that differ from the draft)

```json
"regulation.bin": {"strategy": "regulation", "base_source": "base", "primary": "a", "label_b": "Suncatcher 1.4.1"},
"action/script/c0000.hks": {"strategy": "text3", "base_source": "base", "encoding_from": "b"},
"chr/c0000.anibnd.dcx": {"strategy": "tae", "base_source": "base", "primary": "b"},
"chr/c0000_a00_hi.anibnd.dcx": {"strategy": "bnd", "base_source": "vanilla", "primary": "b"},
"sfx/sfxbnd_c0000.ffxbnd.dcx": {"strategy": "take", "side": "b", "drop_entries": ["f000001800."]}
```

## Result

- Build: `c0000.hks` merged cleanly by `git merge-file`; behavior 36,905 objects = 36,672 (NRM) + 233; TAE 19,442
  animations = 18,995 + 447; nameid 3126 / 2469 / 656 entries; all verification checks passed; hooks patched two
  scripts; `luac -p` passed.
- Deploy: 27 files overwritten (backed up, identical to the base package), 20 added; ME3 profiles already had
  NRM's natives entry.
- Hand-over included the in-game test list (L3 sprint, stance + dodge, jumps and landings, walk/run/roll animations
  of every weight class, the NRM log line confirming its script loaded) and three pre-existing issues found while
  reading (one in the base's scripts, one in each mod), reported as not caused by the merge.
