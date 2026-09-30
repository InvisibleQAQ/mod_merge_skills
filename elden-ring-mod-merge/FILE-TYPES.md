# File types: what they are and how they are merged

Paths are relative to the mod root. "Base" = common ancestor (base mod file, else the vanilla copy extracted
from the game archives, else none). All merges are three-way: an item only one side changed takes that side's
version; an item both changed identically is kept; an item both changed differently is a conflict.

## Contents
- regulation.bin
- action/*nameid.txt
- HKS scripts (action/script/*.hks)
- c0000.behbnd.dcx (behavior graph)
- c0000.anibnd.dcx (TAE)
- HKX animation binders (c0000_a0x ... a9x, a00_hi/md/lo, dlc)
- Effects (sfx/*.ffxbnd.dcx)
- Text (msg/*/*.msgbnd.dcx)
- Not merged automatically
- Loader profiles and DLLs

## regulation.bin (`regulation`)
- AES-encrypted, DCX (ZSTD) compressed BND4 of every `.param`. Game version is stored as the BND version; all
  three must match.
- Merged per row, matched by (ID, occurrence) because a few params repeat IDs; rows both sides changed are merged
  per field. Rows are inserted in ID order. Unchanged params keep their original bytes.
- Row names are editor-only. Some mods strip all names (the file shrinks a lot); make the side that kept names
  `primary`. New rows from a nameless side get `label_a` / `label_b` as name.
- Conflict keys: `Param/ID/field` or `Param/ID` (whole row; add `#n` for the n-th duplicate ID).
- Beware of semantic coupling without a text conflict: two mods may add rows whose IDs they each reference from
  TAE events, HKS (`env(GetSpEffectID, N)`) or other params. Same ID added by both with different content is a
  conflict; different IDs never collide.

## action/*nameid.txt (`nameid`)
- `eventnameid.txt`, `statenameid.txt`, `variablenameid.txt`: `Num = N` then `n = "Name"` lines. HKS refers to
  behavior events/states/variables by name; these tables give the names numbers. Names must match the strings in
  the behavior graph.
- Mods append; both appending from the same number means colliding numbers. Base lines stay byte-identical, the
  KEEP side's appended names keep their numbers, the other side's are appended and renumbered. Use the behavior
  KEEP side as `keep`. A side that edited or removed existing lines needs a manual merge.

## HKS scripts (`text3`)
- `action/script/c0000.hks` (player) is Havok Script, i.e. Lua 5.1 syntax. Overhauls often split it into modules
  (`action/script/modules/`) and some mods ship extra scripts loaded at runtime (`loadfile`) that replace global
  functions after the base script loaded.
- Merged with `git merge-file` after normalising BOM, CRLF and the final newline; output encoding follows
  `encoding_from` (the game accepts UTF-8 with or without BOM, CRLF or LF). Conflict hunks must be merged by hand.
  `verify.py` re-checks the result with its own line diff (every line either side changed is in the result).
- Syntax check: `luac -p` with a Lua 5.1 compiler is exact. Lua 5.2+ accepts `goto`, `//`, bit operators and
  `<const>` that Havok Script rejects, and rejects 5.1 scripts that use `goto` as a name: with them the check is
  necessary, not sufficient.
- A clean text merge is not a clean behaviour merge: see the review leads in WORKFLOW.md (runtime wrappers,
  shared buttons/variables, hard-coded IDs, obfuscation).
- Overhauls can install a `_G` metatable that turns unknown globals into no-op functions: a missing function then
  fails silently instead of erroring, while a missing numeric global still errors in arithmetic.

## c0000.behbnd.dcx (`behavior`)
- BND4 with three HKX files; `Behaviors\c0000.hkx` is the behavior graph (hk2018 tagfile). The other two
  (project, character data) are rarely changed; if MOVE changed them and KEEP did not, MOVE's copy is used.
- Objects are identified by `Type:name`. Graph-wide tables live in `hkbBehaviorGraphData` /
  `hkbBehaviorGraphStringData`: event names, variable names (+ infos, bounds, initial values), animation names.
  Nodes refer to them by index (`m_eventId`, `m_variableIndex`, `m_animationInternalId`), state machines refer
  to their states by `m_stateId`.
- Mods typically (a) append to those tables, (b) add nodes, (c) append children to selectors / state machines,
  (d) repoint a slot to a new selector that wraps the original. `beh-merge` keeps KEEP's graph intact and
  transplants MOVE's changes: MOVE's table tails go after KEEP's, MOVE's indices shift by KEEP's growth, MOVE's new
  states get fresh IDs where KEEP already uses the number, and a slot both wrapped gets nested wrappers.
- Unsupported (reported as conflict): a side removing objects or list items, both changing the same scalar or
  repointing the same slot without the wrapper pattern.
- Selector indices written by HKS (`SetVariable("X", n)`) address positions in selector child lists. Appends keep
  positions stable; that is why nothing is ever inserted before existing children.
- Base clip generators may carry out-of-range `m_animationInternalId` values; editors re-index them. Such re-indexing
  on one side shows as thousands of "modified" clip generators and is harmless for the merge.

## c0000.anibnd.dcx (`tae`)
- BND4 of the skeleton and one TAE file per animation category (`a00.tae` = common, `aNN.tae` = weapon types,
  `a1xx`+ = special sets). Each TAE holds animations by ID with events (frames, SpEffects, sounds, FX, flags).
- Merged per TAE file: a file only one side changed is taken byte-for-byte; otherwise per animation (ID,
  occurrence). A TAE header change (e.g. a TAE ID rewritten from 20xxx to 2xxx) follows the side that made it.
- `ImportOtherAnim` headers redirect one animation to another (possibly in a TAE a mod added); treat a redirect
  like any other content change.
- Conflict keys: `aNN.tae/<animID>`.

## HKX animation binders (`bnd`)
- `c0000_a0x.anibnd.dcx` ... `c0000_a9x`, `c0000_a00_hi/md/lo`, `c0000_dlc01/02`: BND4 of `.hkx` animations
  named `aNNN_XXXXXX.hkx` with IDs derived from the name, plus a `.compendium` the animations reference (so an
  animation cannot move to another binder).
- Merged per entry by name. The base mod often does not ship `a00_hi/md/lo`; the plan then uses the vanilla copy
  as base (`base_source: vanilla`).

## Effects (`bnd` + cross-pack check)
- `sfx/*.ffxbnd.dcx`: FXR effects (`effect/fNNNNNNNNN.fxr`), their resource lists and textures/models.
- Merged per entry like other binders. Additionally, FXR IDs are global across all loaded packs: two mods adding
  the same FXR ID to different packs is a collision `analyze.py` reports. Options: share one copy (drop the other
  with `drop_entries`), or give one a new ID (rename the entry, patch the FXR's internal ID, and repoint every TAE
  event / SpEffectVfxParam that spawns it - a manual job). After the build, `crosscheck.py` confirms every FFX ID
  the mods' TAE events newly use is still in some pack, and reports references that now use the other mod's copy.

## Text (`bnd` with FMG)
- `msg/<lang>/*.msgbnd.dcx`: FMG text tables. When both sides changed the same FMG, it is merged per text ID.
- Some mods ship one language's file for every language folder; that replaces the base's translation. Point it
  out to the user.

## Not merged automatically (decide: take one side, or merge by hand with a dedicated tool)
- `script/talk/*.talkesdbnd.dcx` (ESD dialogue/menus: entry-level merge works, an `.esd` both changed needs ESDLang),
  `event/*.emevd.dcx` (DarkScript3), `map/` MSB files, `sd/*.bnk` sound banks (rewwise / wwiser), textures,
  models, `param/` gparams, DLLs. `bnd` strategy still merges these binders per entry; only an inner file both
  changed becomes a conflict.

## Loader profiles and DLLs
- DLLs (`dll/*.dll`) are copied, never merged. They must be listed in the launcher profile (ME3 `[[natives]]`,
  ModEngine 2 `external_dlls`) with the initializer / load order the mod's installer uses.
- Two DLLs hooking the same game function can conflict in ways no file comparison shows; check the mods' notes.
