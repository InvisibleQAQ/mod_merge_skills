# mod_merge_skills (maintainers)

- Skill `elden-ring-mod-merge/`: English docs; `SKILL.md` stays under ~100 lines, details live in the linked files
  (one level deep). This file is the only maintainer doc; the skill folder is what users install, so maintainer
  notes stay out of it. Code map: `TOOLS.md` (scripts, plan.json, ermerge commands, workspace layout).
- Tool source `elden-ring-mod-merge/tools/ErMergeKit/` builds only through `scripts/setup.py` into a workspace
  (`<W>/.kit`); never commit `bin/` or `obj/`. Rebuilding clears `<W>/dumps/cache` (dumps keyed by file hash).
- Merge semantics are shared by the C# tool (`Three.Decide` in `Common.cs`) and the independent Python check
  (`decide` in `scripts/verify.py`). Change both together, and keep them independent implementations. The text3
  check in `verify.py` uses difflib, never git.
- Scripts must not write outside the workspace or into the skill folder (`sys.dont_write_bytecode` in every entry
  script, temporary files inside the workspace).

## Regression test (after any change)

Case: Convergence 3.0.2 + Nightreign Movement 1.0.0-beta.16 + Suncatcher 1.4.1 (inputs under
`Desktop/00_backup/07_mod/01_mod/`). Reference build: `Desktop/00_backup/07_mod/diff_nrm_sun_20260930/build/mod`.
Fixture: `regression/nrm_suncatcher/` (`plan.files.json` for A = NRM package root, B = Suncatcher, names
`NRM 1.0.0-beta.16` / `Suncatcher 1.4.1`; `post_merge.py` = the reference hook, comment text included).

1. Follow run (tests the pipeline): new workspace; setup, inventory, analyze; put the fixture's `exclude` /
   `files` into `plan.json` and the fixture hook into `<W>/hooks/`; analyze again; build.
2. Expected: `build ok`; VERIFY.md all ok, take row drops `f000001800.fxr` + `f000001800.ffxreslist`, hook section
   2 hunks (c0000.hks +1 line at 450, nrm-extension.hks 1 line changed at 670); CROSSCHECK 0 errors, 8 warnings
   (SpEffect 100360 / 112045010 from both mods; Suncatcher's decoded literals `W_AttackBothLightDash`,
   `L_Foot_Target2`, `R_Foot_Target2`; FXR 400 / 410 / 420), 1 info (FXR 1800: Suncatcher's references use NRM's
   copy), nameid +38 / +36 / +15, 21 new engine-call names; SUMMARY marks KEEP Suncatcher blocked (NRM's 64).
   `python -B regression/compare.py --workspace <W> --reference <reference build>` prints `regression OK`
   (47 files; all byte-identical except `regulation.bin`, whose param dumps must be identical).
3. Blind run (tests the analysis): an agent that has not seen this pair works with `EXAMPLE.md` and `regression/`
   hidden. Pass: it chooses KEEP NRM for the blocked reason, finds decision points 1.1-1.5 of the user's document
   and reports the `VGhoMVNB` side effect of the `NjiwOxnT` patch. Then install the fixture hook and run step 2
   (hook comment text is the agent's own otherwise, so bytes differ only there).
4. Negative checks: a `drop_entries` fragment that matches nothing stops the build (exit 3); a hook anchor off by
   one byte fails the hook; `setup.py` warns when luac is not Lua 5.1; `scripts/__pycache__` never appears.
