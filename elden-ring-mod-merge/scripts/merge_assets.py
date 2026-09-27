"""两个 ER Mod 的文件盘点与组装；regulation 由同目录 codec 处理。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


SCHEMA = "er-mod-assets-v1"
MAPPINGS = {"variablenameid.txt", "statenameid.txt", "eventnameid.txt"}
EXCLUDED_SUFFIXES = (
    ".anibnd", ".anibnd.dcx", ".behbnd", ".behbnd.dcx", ".hkx",
    ".hkx.dcx", ".tae", ".tae.dcx", ".hks", ".hks.dcx",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest().upper()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_new(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def exclude_reason(relative: str):
    name = relative.rsplit("/", 1)[-1].lower()
    if name in MAPPINGS:
        return "ID mapping (out of scope)"
    if name.endswith(EXCLUDED_SUFFIXES):
        return "animation / behavior / HKS (out of scope)"
    return None


def safe_relative(value: str) -> Path:
    if not value or "\\" in value or ":" in value:
        raise ValueError(f"Invalid relative path: {value!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Invalid relative path: {value!r}")
    path = Path(*parts)
    if path.is_absolute():
        raise ValueError(f"Absolute asset path: {value}")
    return path


def inventory(root: Path):
    result = {}
    for folder, directories, filenames in os.walk(root, followlinks=False):
        directories.sort()
        for name in directories + filenames:
            item = Path(folder) / name
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise ValueError(f"Linked asset is unsupported: {item}")
        for name in sorted(filenames):
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            key = relative.casefold()
            if key in result:
                raise ValueError(f"Case-insensitive path collision: {relative}")
            if name.casefold() == "regulation.bin" and key != "regulation.bin":
                raise ValueError(f"Nested regulation.bin; select the actual mod root: {path}")
            result[key] = {"path": relative, "sha256": digest(path)}
    if "regulation.bin" not in result:
        raise ValueError(f"Mod root must contain regulation.bin: {root}")
    return result


def choose_source(base, a, b):
    """Mod folders are overlays: an absent file does not mean deletion."""
    if a is None:
        return "b"
    if b is None or a == b:
        return "a"
    if a == base:
        return "b"
    if b == base:
        return "a"
    return None


def validate_destination(path: Path, protected):
    if path.exists():
        raise ValueError(f"Destination already exists: {path}")
    for source in protected:
        if within(path, source) or within(source, path):
            raise ValueError(f"Destination overlaps protected input: {path} / {source}")


def scan(args):
    roots = {"a": args.a.resolve(strict=True), "b": args.b.resolve(strict=True)}
    if any(not p.is_dir() for p in roots.values()):
        raise ValueError("Mod roots must be directories")
    if within(roots["a"], roots["b"]) or within(roots["b"], roots["a"]):
        raise ValueError("Mod roots must be separate non-overlapping directories")
    if args.base_files:
        roots["base"] = args.base_files.resolve(strict=True)
        if not roots["base"].is_dir():
            raise ValueError("--base-files must be a directory")
        if any(within(roots["base"], roots[side]) or within(roots[side], roots["base"])
               for side in ("a", "b")):
            raise ValueError("Base resource root must be separate from both mods")
    report_path = args.report.resolve()
    validate_destination(report_path, roots.values())
    inventories = {side: inventory(roots[side]) for side in ("a", "b")}
    entries, excluded, conflicts = [], [], []
    for key in sorted(inventories["a"].keys() | inventories["b"].keys()):
        sources = {side: inv[key] for side, inv in inventories.items() if key in inv}
        name = next(iter(sources.values()))["path"]
        if key == "regulation.bin":
            continue
        if reason := exclude_reason(name):
            excluded.append({"path": name, "reason": reason, "sources": sources})
            continue
        if "base" in roots:
            candidate = roots["base"] / safe_relative(name)
            resolved = candidate.resolve()
            if not within(resolved, roots["base"]):
                raise ValueError(f"Base asset escapes root: {candidate}")
            if candidate.is_file():
                sources["base"] = {"path": name, "sha256": digest(candidate)}
        hashes = {side: src["sha256"] for side, src in sources.items()}
        selected = choose_source(hashes.get("base"), hashes.get("a"), hashes.get("b"))
        entry = {"path": name, "key": key, "sources": sources, "selected": selected}
        entries.append(entry)
        if selected is None:
            conflicts.append({"key": key, "path": name, "choices": list(sources)})
    report = {
        "schema": SCHEMA,
        "roots": {side: str(path) for side, path in roots.items()},
        "inputs": inventories,
        "entries": entries,
        "conflicts": conflicts,
        "excluded": excluded,
        "absence_semantics": "overlay; no file deletions inferred",
    }
    write_new(report_path, report)
    print(json.dumps({"report": str(report_path), "files": len(entries),
                      "conflicts": len(conflicts), "excluded": len(excluded)}))
    return 2 if conflicts else 0


def assemble(args):
    report_path = args.report.resolve(strict=True)
    report = read_json(report_path)
    if report.get("schema") != SCHEMA:
        raise ValueError("Unsupported report schema")
    roots = {side: Path(value).resolve(strict=True) for side, value in report["roots"].items()}
    # Include excluded resources and regulation in input integrity checks.
    for side in ("a", "b"):
        if inventory(roots[side]) != report["inputs"][side]:
            raise ValueError(f"Mod {side} changed since scan; rescan and reconfirm decisions")
    if "base" in roots:
        for entry in report["entries"]:
            candidate = (roots["base"] / safe_relative(entry["path"])).resolve()
            if not within(candidate, roots["base"]):
                raise ValueError(f"Base asset escapes root: {candidate}")
            prior = entry["sources"].get("base")
            current_hash = digest(candidate) if candidate.is_file() else None
            if current_hash != (prior["sha256"] if prior else None):
                raise ValueError(f"Base asset changed since scan: {candidate}")
    decisions = {}
    if args.decisions:
        raw = read_json(args.decisions)
        if raw.get("report_sha256") != digest(report_path):
            raise ValueError("File decisions do not match the report SHA-256")
        decisions = raw["decisions"]
    expected = {conflict["key"] for conflict in report["conflicts"]}
    if set(decisions) != expected:
        raise ValueError(f"Decision keys must exactly match unresolved file conflicts: {sorted(expected)}")
    selected_files, destination_keys = [], set()
    for entry in report["entries"]:
        relative = safe_relative(entry["path"])
        key = relative.as_posix().casefold()
        if key == "regulation.bin" or exclude_reason(relative.as_posix()):
            raise ValueError(f"Out-of-scope entry in file plan: {relative}")
        if key in destination_keys:
            raise ValueError(f"Duplicate output asset: {relative}")
        destination_keys.add(key)
        side = entry["selected"] or decisions[entry["key"]]
        if side not in entry["sources"]:
            raise ValueError(f"Invalid choice {side!r} for {relative}")
        source = entry["sources"][side]
        original = (roots[side] / safe_relative(source["path"])).resolve(strict=True)
        if not within(original, roots[side]) or digest(original) != source["sha256"]:
            raise ValueError(f"Asset changed or escapes root: {original}")
        selected_files.append((relative, original, source["sha256"], side))
    # Reject a file used as the parent directory of another output file.
    for key in destination_keys:
        parents = list(Path(key).parents)[:-1]
        if any(parent.as_posix() in destination_keys for parent in parents):
            raise ValueError(f"File/directory collision in output: {key}")
    regulation = args.regulation.resolve(strict=True)
    if not regulation.is_file():
        raise ValueError("--regulation must be a verified codec output file")
    verification_path = args.verification.resolve(strict=True)
    verification = read_json(verification_path)
    if (verification.get("schema") != "er-regulation-build-v1"
            or verification.get("status") != "verified"
            or verification.get("outputSha256") != digest(regulation)
            or Path(verification.get("output", "")).resolve() != regulation):
        raise ValueError("Regulation does not match a successful codec verification receipt")
    for side in ("a", "b"):
        if verification["inputs"][side] != report["inputs"][side]["regulation.bin"]["sha256"]:
            raise ValueError(f"Verified regulation input {side} differs from scanned mod")
    output, receipt = args.output.resolve(), args.receipt.resolve()
    protected = list(roots.values()) + [report_path, regulation, verification_path]
    if args.decisions:
        protected.append(args.decisions.resolve(strict=True))
    validate_destination(output, protected)
    validate_destination(receipt, protected + [output])
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for relative, original, expected_hash, side in selected_files:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        if digest(target) != expected_hash:
            raise ValueError(f"Copy verification failed: {target}")
        records.append({"path": relative.as_posix(), "source": side, "sha256": expected_hash})
    regulation_hash = digest(regulation)
    shutil.copyfile(regulation, output / "regulation.bin")
    if digest(output / "regulation.bin") != regulation_hash:
        raise ValueError("Regulation copy verification failed")
    write_new(receipt, {
        "schema": SCHEMA,
        "status": "assembled-with-explicit-exclusions",
        "output": str(output),
        "report_sha256": digest(report_path),
        "regulation_sha256": regulation_hash,
        "regulation_verification": verification,
        "files": records,
        "excluded": report["excluded"],
        "gameplay_verified": False,
        "note": "Parameter validation belongs to codec; excluded resources are not included.",
    })
    print(json.dumps({"output": str(output), "receipt": str(receipt), "files": len(records) + 1}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan_parser = commands.add_parser("scan", help="只读比较两份 Mod；报告写入新路径")
    for option in ("a", "b", "report"):
        scan_parser.add_argument(f"--{option}", type=Path, required=True)
    scan_parser.add_argument("--base-files", type=Path)
    build_parser = commands.add_parser("assemble", help="复制已确认文件并纳入已验证 regulation")
    for option in ("report", "regulation", "verification", "output", "receipt"):
        build_parser.add_argument(f"--{option}", type=Path, required=True)
    build_parser.add_argument("--decisions", type=Path)
    args = parser.parse_args(argv)
    try:
        return scan(args) if args.command == "scan" else assemble(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
