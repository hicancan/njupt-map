"""Ingest original sources and derive publication exclusions from their permissions."""
from __future__ import annotations

import argparse
import json
import re
import shutil

from .common import CATALOG, KINDS, ROOT, read, resolve, source_record, write


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", value):
        raise argparse.ArgumentTypeError("Use a portable ID of letters, digits, underscores, or hyphens")
    return value


def ingest(args) -> None:
    catalog = read(CATALOG)
    if args.id in catalog["sources"]:
        raise ValueError(f"Source ID already exists: {args.id}")
    original = args.file.resolve()
    if not original.is_file():
        raise ValueError(f"Source is not a file: {original}")
    destination = resolve(f"observations/{args.kind}/{args.id}{original.suffix.lower()}")
    if destination.exists():
        raise ValueError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, destination)
    catalog["sources"][args.id] = source_record(args.id, destination, args.kind, args.license,
                                               photo_taken_at=args.captured_at, url=args.source_url,
                                               selection_reason=args.reason)
    write(CATALOG, catalog)
    print(json.dumps(catalog["sources"][args.id], ensure_ascii=False, indent=2))


def export_ignore(args) -> None:
    """Derive exclusions from current source permissions, never a second registry."""
    begin = "# BEGIN observation permissions (generated from observations/catalog.json)"
    end = "# END observation permissions"
    sources = read(CATALOG)["sources"]
    paths = sorted({s["local_path"] for s in sources.values()
                    if s.get("local_path") and s["redistribution"]["status"] == "local_only"})
    lines = [begin] + ["/" + p.replace("[", "\\[").replace("]", "\\]") for p in paths] + [end]
    block = "\n".join(lines) + "\n"
    if args.write:
        path = ROOT / ".gitignore"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if begin in existing:
            first, _, rest = existing.partition(begin)
            if end not in rest:
                raise ValueError("Existing permission ignore block is incomplete")
            _, _, last = rest.partition(end)
            content = first + block + last.lstrip("\n")
        else:
            content = existing.rstrip("\n") + "\n\n" + block
        path.write_text(content, encoding="utf-8")
        print(json.dumps({"excluded_media_count":len(paths),"path":".gitignore"}))
    else:
        print(block, end="")


def main() -> None:
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser("ingest", help="Archive and register an original source without changing it")
    ingest_parser.add_argument("file", type=Path)
    ingest_parser.add_argument("--id", required=True, type=identifier)
    ingest_parser.add_argument("--kind", required=True, choices=KINDS)
    ingest_parser.add_argument("--license", default="unknown", help="Explicit source license; unknown remains local-only")
    ingest_parser.add_argument("--captured-at", default=None, help="Established camera capture date, not retrieval date")
    ingest_parser.add_argument("--source-url", default=None)
    ingest_parser.add_argument("--reason", default=None)
    ingest_parser.set_defaults(run=ingest)
    ignore_parser = commands.add_parser("export-ignore", help="Derive the Git ignore block from current source permissions")
    ignore_parser.add_argument("--write", action="store_true", help="Refresh only the observation permission block in repository .gitignore")
    ignore_parser.set_defaults(run=export_ignore)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
