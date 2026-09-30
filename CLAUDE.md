# mod_merge_skills (maintainers)

- Skill `elden-ring-mod-merge/`: English docs; `SKILL.md` stays under ~100 lines, details live in the linked files
  (one level deep).
- Tool source `elden-ring-mod-merge/tools/ErMergeKit/` builds only through `scripts/setup.py` into a workspace
  (`<W>/.kit`); never commit `bin/` or `obj/`.
- Merge semantics are shared by the C# tool (`Three.Decide` in `Common.cs`) and the independent Python check
  (`decide` in `scripts/verify.py`). Change both together, and keep them independent implementations.
- Regression test after any change: run the full pipeline on the Convergence 3.0.2 + Nightreign Movement
  1.0.0-beta.16 + Suncatcher 1.4.1 case (`EXAMPLE.md` has the plan and hook). Expected: build ok, verification
  0 problems, output byte-identical to the reference build except `regulation.bin` (random IV; compare
  `param-dump` output instead). Reference build of the author: `Desktop/00_backup/07_mod/diff_nrm_sun_20260930/build/mod`.
