# Tool reference

## Contents
- Scripts
- plan.json
- ermerge commands
- Workspace layout
- Exit codes

## Scripts (`scripts/`, Python 3.9+, all take `--workspace W`)

| script | does | writes |
|---|---|---|
| `setup.py --smithbox S --game G [--dotnet D]` | checks prerequisites, builds ermerge, smoke test | `kit.json`, `.kit/` |
| `inventory.py --a A --b B [--base BASE] [--a-name/--b-name/--base-name] [--force]` | file-level comparison, draft plan | `inventory.json/.md`, `plan.json` |
| `analyze.py` | dry-run merges, review leads, write-back checks | `analysis/SUMMARY.md`, `analysis/*.json`, `vanilla/` |
| `build.py` | merge, verify, hooks, luac | `staging/`, `reports/` |
| `verify.py` | independent three-way check of `staging/` (build runs it) | `reports/VERIFY.md` |
| `deploy.py --target T [--yes] [--force] [--rollback]` | preview / deploy with backup / roll back | `backup/<time>/` |

Modules: `kit.py` (workspace, file walking), `text_merge.py` (nameid + git merge-file), `hks_analyze.py`
(script heuristics).

## plan.json

```json
{
  "base": {"name": "Convergence 3.0.2", "dir": "D:/mods/convergence/mod"},
  "a": {"name": "ModA", "dir": "D:/mods/moda/mod"},
  "b": {"name": "ModB", "dir": "D:/mods/modb"},
  "exclude": ["msg/zhocn/menu_dlc02.msgbnd.dcx"],
  "files": {
    "regulation.bin":              {"strategy": "regulation", "base_source": "base", "primary": "a", "label_b": "ModB", "resolve": {"SpEffectParam/100/effectEndurance": "b"}},
    "action/eventnameid.txt":      {"strategy": "nameid", "base_source": "base", "keep": "a"},
    "action/script/c0000.hks":     {"strategy": "text3", "base_source": "base", "encoding_from": "b"},
    "chr/c0000.behbnd.dcx":        {"strategy": "behavior", "base_source": "base", "keep": "a", "wrap_order": "move-outer"},
    "chr/c0000.anibnd.dcx":        {"strategy": "tae", "base_source": "base", "primary": "b", "resolve": {"a29.tae/30000": "a"}},
    "chr/c0000_a00_hi.anibnd.dcx": {"strategy": "bnd", "base_source": "vanilla", "primary": "b"},
    "sfx/sfxbnd_c0000.ffxbnd.dcx": {"strategy": "take", "side": "b", "drop_entries": ["f000001800."]},
    "event/m10_00_00_00.emevd.dcx":{"strategy": "manual", "source": "resolved/event/m10_00_00_00.emevd.dcx"}
  }
}
```

- Keys of `files` are mod-relative paths as listed in `inventory.md` (case as found).
- `base_source`: `base` (the base mod's copy), `vanilla` (extracted from the game archives into `W/vanilla/`),
  `none` (no ancestor: identical additions merge, different ones conflict).
- `strategy`: `regulation` | `nameid` | `text3` | `behavior` | `tae` | `bnd` | `take` | `manual`.
- `primary` (regulation/tae/bnd): whose file the result is built on; `keep` (behavior/nameid): whose indices stay.
- `resolve`: conflict key -> `"a"` or `"b"`; keys are exactly those printed in dry-run reports.
- Files not listed are copied if only one side changed them; a both-changed file without an entry stops the build.

## ermerge commands

Run as `dotnet W/.kit/bin/ermerge.dll <command> ...` (paths may be relative to the current folder; `-` = no file).

| command | purpose |
|---|---|
| `bnd-list <binder> <out.tsv> [extractDir]` | entries (ID, name, flags, size, SHA-256); optional extraction |
| `tae-dump <anibnd> <out.jsonl> [template.xml]` | every animation with a content signature and raw event bytes |
| `param-dump <regulation.bin> <defsDir> <outDir>` | one TSV per param (all fields, names) |
| `beh-dump <behbnd or hkx> <outPrefix>` | keyed objects (`.nodes.jsonl`) and tables (`.tables.json`) |
| `roundtrip <file> [--defs dir]` | can the libraries rewrite this file byte-exactly |
| `vanilla-extract <gameDir> <outDir> <gamePath>...` | copy unmodded files out of the game archives (`regulation.bin` from the game folder) |
| `reg-merge <base> <a> <b> <defsDir> <out> --primary a|b [--label-a T --label-b T]` | regulation three-way, per field |
| `tae-merge <base> <a> <b> <out> --primary a|b` | TAE container three-way, per animation |
| `bnd-merge <base> <a> <b> <out> --primary a|b` | any BND4, per entry (FMG per text ID) |
| `beh-merge <base> <keep> <move> <out> [--wrap-order move-outer|keep-outer]` | behavior graph transplant |
| `bnd-drop <in> <out> <nameFragment>...` | remove entries |

Merge commands accept `--resolve r.json`, `--report rep.json` (conflicts, stats, notes; behavior also writes
`rep.log.txt`) and `--dry-run`.

## Workspace layout

```
W/kit.json  plan.json  inventory.json  inventory.md  decisions.md
W/.kit/            built tool
W/analysis/        SUMMARY.md, dry-run reports, hks heuristics
W/vanilla/         extracted unmodded files (mirrors mod paths)
W/dumps/           dumps used by analysis / verification
W/staging/         merged mod files - what deploy copies
W/reports/         BUILD.md/json, VERIFY.md, per-file merge reports, behavior logs
W/conflicts/       text files with conflict markers (to resolve by hand)
W/resolved/        hand-merged files referenced by "manual" entries
W/hooks/post_merge.py
W/backup/<time>/   files replaced by deploy + manifest.tsv
```

## Exit codes

`0` ok · `1` error (message printed) · `2` usage · `3` unresolved conflicts (nothing written for that file;
`build.py` stops).
