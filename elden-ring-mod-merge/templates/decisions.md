# <Mod A> + <Mod B> on <Base>: options and decisions

- Date: <yyyy-mm-dd>
- Base: <name, version, folder> · A: <name, version, folder> · B: <name, version, folder>
- Workspace: <W>
- Nothing below was tested in game; `[UNKNOWN]` marks what could not be verified.

## 1. Decisions the user made

### 1.1 <short title>

Conflict: <what both mods do, in play terms, with file:function evidence>

| option | effect |
|---|---|
| A | ... |
| **B (chosen)** | ... |

Implementation: <plan.json key / hook patch (file, anchor, change)>

## 2. Mechanical choices (no user input needed)

| file | setting | reason |
|---|---|---|
| chr/c0000.behbnd.dcx | keep = <side> | <hard-coded IDs / dry-run direction without conflicts> |
| action/*nameid.txt | keep = <side> | same as behavior KEEP |
| regulation.bin | primary = <side> | <keeps row names> |
| ... | ... | ... |

## 3. Result (filled after build/deploy)

- Build: <counts from reports/BUILD.md>; verification: <reports/VERIFY.md summary>; hooks patched: <files>
- Deployed to: <target>; backup: <W/backup/...>; rollback: `python scripts/deploy.py --workspace W --target <target> --rollback --yes`
- Launcher profile changes: <...>

## 4. In-game test list

- ...

## 5. Known issues not caused by the merge

- ...
