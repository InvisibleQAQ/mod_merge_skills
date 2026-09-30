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
| Effect ID collision across packs | analyze FXR section | share one copy / renumber one side (manual) | `take` + `drop_entries`, or manual |
| One-sided file both need (e.g. a text file one mod replaces wholesale) | inventory + readmes | take / merge by hand | `take`, `manual` |
| Localization replaced by a mod | inventory (msg files) | accept / keep the base's language file (the mod's new text IDs then show blank) | `exclude` or `take` |
| DLL interplay | readmes, DLL strings | accept / drop one DLL | `exclude` + launcher profile |

## Patching code decisions (hooks)

`W/hooks/post_merge.py` runs after verification with the staging folder as argument. Keep each patch:
- **minimal**: one early return / one extra condition at the single place a feature starts, not a rewrite;
- **anchored**: replace exact bytes that must occur exactly once (assert it), including the file's line endings;
- **labelled**: a trailing comment naming the decision, so the change is findable in game logs and future diffs;
- **syntax-checked**: `build.py` runs `luac -p` on every `.hks` when Lua is installed. In Lua, `return` must be the
  last statement of a block; use `do return FALSE end` for an early return.

Example (disable a feature whose only entry point is function `StartFeature`):

```python
patch('action/script/c0000.hks', b'function StartFeature(arg)\r\n',
      b'function StartFeature(arg)\r\ndo return FALSE end -- merge: feature X disabled (decision 1)\r\n')
```

Find a feature's entry point by following the event that enters it (`ExecEvent*("W_...")`) back to the one function
that fires it; verify there is no second caller before patching.
