# Conflicts: kinds, how to present them, how to implement the answer

## Presenting

- One decision per question. Use the ask-the-user tool when available; otherwise a numbered list.
- Recommended option first, marked as recommended, with the reason in one line.
- Describe consequences in play terms ("pressing L3 while running starts both sprints"), not file terms.
- Offer only options that are fully specified and implementable; "leave it and hope" is not an option when the
  outcome is unknown (e.g. two copies of one effect ID).
- A decision can create a follow-up question (e.g. removing a feature frees a button): ask it before building.
- Record every question, the options, the answer and the implementation in `W/decisions.md`.

## Kinds

| kind | found by | typical options | implemented with |
|---|---|---|---|
| Data item both changed differently (param field, animation, binder entry, FMG text) | dry-run `CONFLICTS` | take A / take B per key | `resolve` map in the file's plan entry |
| Table numbering (nameid, behavior event/variable/animation indices, state IDs) | always when both append | none - mechanical | `keep` side; the other side is renumbered |
| Behavior slot both repointed | beh-merge `WRAP` log line | which wrapper is outer (matters only when both wrappers' variables are active at once) | `wrap_order` |
| Behavior structure conflict (non-wrapper) | beh-merge conflict | pick the other KEEP direction, or give up that mod's change | `keep`, or manual |
| Script text conflict | text3 conflict hunks | hand merge | `manual` + `resolved/<path>` |
| Same input used by both | review lead + code reading | drop one mod's use of the button / accept both / disable one feature in the mod's own settings | hook patch at the feature's entry point |
| Runtime wrapper bypasses the other mod's new logic | review lead + code reading | accept (who wins in which situation) / add a condition to the wrapper / drop one feature | hook patch |
| Feature overlap (two sprint systems, two landing rolls, two dodge variants) | code reading | keep one, keep both with a guard, accept precedence | hook patch or plan |
| State or index gate: one mod's state value fails the other's state check (e.g. `UpperDefaultState00 == MOVE_DEF0`), or one mod's selector index exceeds the children of a selector only the other side uses | code reading + selector child counts in the behavior dump; in game, a feature silently does nothing or a pose breaks | accept / widen the gate for that state (keyed on the state's own SpEffect or variable) / keep the index in range where that selector is active | hook patch |
| Effect ID collision across packs | analyze FXR section | share one copy / renumber one side (manual) | `take` + `drop_entries` (the dry-run in SUMMARY.md lists what is dropped), or manual |
| Reference a decision leaves dangling (dropped effect, excluded file, resolved row) | `crosscheck.py` error | undo / change the decision, or supply the target | plan or hook |
| One-sided file both need (e.g. a text file one mod replaces wholesale) | inventory + readmes | take / merge by hand | `take`, `manual` |
| Localization replaced by a mod | inventory (msg files) | accept / keep the base's language file (the mod's new text IDs then show blank) | `exclude` or `take` |
| DLL interplay | readmes, DLL strings | accept / drop one DLL | `exclude` + launcher profile |

## Patching code decisions (hooks)

`W/hooks/post_merge.py` runs after verification with the staging folder as argument. Keep each patch:
- **minimal**: one early return / one extra condition at the single place a feature starts, not a rewrite;
- **anchored**: replace exact bytes that must occur exactly once (assert it), including the file's line endings;
- **labelled**: a trailing `-- merge ...` comment naming the decision, so the change is findable in game logs and
  future diffs;
- **one contiguous edit per `patch()` call**: `build.py` diffs every patched file against its pre-hook copy
  (`reports/hooks.diff`) and fails if a changed hunk has no `-- merge` label or the hunk count differs from the
  number of `patch()` calls;
- **syntax-checked**: `build.py` runs `luac -p` on every `.hks` when Lua is installed. In Lua, `return` must be the
  last statement of a block; use `do return FALSE end` for an early return.

Example (disable a feature whose only entry point is function `StartFeature`):

```python
patch('action/script/c0000.hks', b'function StartFeature(arg)\r\n',
      b'function StartFeature(arg)\r\ndo return FALSE end -- merge: feature X disabled (decision 1)\r\n')
```

Find a feature's entry point by following the event that enters it (`ExecEvent*("W_...")`) back to the one function
that fires it. Before an early return in that function, read **every caller**:
- a second caller that does not test the result: the feature may still start another way;
- a caller that picks its branch with another predicate (`if P() then F() elseif ... end`) where `F()` is the branch's
  only action: after the patch `P()` still selects that branch, so the caller's other branches are skipped
  whenever `P()` is true. Either patch `P()` as well (or instead), or accept it - and tell the user. Example:
  Suncatcher's `SpeedUpdate` does `if VGhoMVNB() then NjiwOxnT(TRUE) elseif ...`; with `NjiwOxnT` returning early,
  holding L3 still skips every `ChangeMoveSpeedIndex` branch below.
Write what the patch skips into the decision's **side effects** in `decisions.md` and offer the alternative as an
option, even when the user already prescribed the patch location.
