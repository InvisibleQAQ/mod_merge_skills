# Step 0: what the user must prepare

Send the message below first (translate it into the user's language, keep paths and names as they are), then
wait. Do not start inventory until every **required** item is confirmed. If the user does not know what the base
is, look at both mods' download pages / readmes together with them; never assume.

---

> To merge the two mods I need a few tools and the **original** files. Please prepare:
>
> **Tools (Windows 10/11, 64-bit)**
> 1. **Smithbox** - download the Windows release zip from https://github.com/vawser/Smithbox/releases and extract
>    it anywhere. You do not need to run it; I only use its libraries and data files. Tell me the folder that
>    contains `Smithbox.exe`.
> 2. **.NET SDK** - https://dotnet.microsoft.com/download. The version must be at least the one Smithbox is built
>    for; the setup step tells you the exact number if yours is too old.
> 3. **Python 3.9 or newer** - https://www.python.org/downloads/ (tick "Add python.exe to PATH").
> 4. **Git for Windows** - https://git-scm.com/downloads (used for three-way merges of script files).
> 5. Optional: **Lua** (`luac`) for syntax-checking merged scripts.
>
> **Files**
> 1. **Mod A and mod B, as downloaded** - extract each archive to its own folder and do not edit them. Give me the
>    folder that contains the mod's files (`regulation.bin`, `chr\`, `action\`, `parts\` ...) or the extracted
>    package that has a `mod\` folder inside. Keep installers, readmes and `.me3` / `.toml` files that came with
>    them: they say which DLLs must be loaded and which settings the mod changes.
> 2. **The base both mods were made for** - if both are add-ons for an overhaul (for example The Convergence,
>    Elden Ring Reforged, a localized overhaul package), the original download of **exactly the version** both mods
>    name, extracted and untouched. If both mods are for the unmodded game, there is no base folder: say so.
>    A copy that already has one of the mods installed on top is **not** a base.
> 3. **The game folder** - `...\ELDEN RING\Game` (the one with `eldenring.exe`), at the game version the mods
>    require. Nothing in it is changed; unmodded files are read from it when needed.
> 4. **Where you play from** - the mod folder your launcher loads (for example `Game\mod`) and which launcher you
>    use (ME3, ModEngine 2, YAFSML, ...). Only needed at the end, when I install the result.
> 5. **An empty working folder** with free space of about three times the size of the two mods, outside the
>    game and mod folders (for example `D:\mod-merge\A+B`).
>
> Please also tell me each mod's name and version, and the base name and version.

---

## Checks to run once the user replies

- Both mods state the same base and base version; if not, stop: different bases need a port, not a merge.
- `setup.py` passes (it checks Smithbox, the .NET SDK version, the game folder, git and optional luac, builds the
  tool and runs a smoke test). If the only SDK found is too old, ask for the SDK or pass `--dotnet <path>` to a
  newer one.
- `inventory.py` finds a mod root in each folder. A folder that "does not look like an Elden Ring mod folder"
  usually means the user pointed at the archive's parent or at a launcher folder.
- Regulation versions: `reg-merge` refuses mods built for different game versions (the base's regulation version
  must equal both mods').
- If the user's play folder already contains one of the mods, `deploy.py` will notice (files differ from the base)
  and stop unless told `--force`; explain that the merge replaces that installation.
