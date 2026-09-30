"""Ingest source files and promote reviewed video frames to formal observations."""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess

from .common import BINDINGS, CATALOG, KINDS, ROOT, checksum, read, redistribution, resolve, source_record, write


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", value):
        raise argparse.ArgumentTypeError("Use a portable ID of letters, digits, underscores, or hyphens")
    return value


def timestamp(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("Timestamp must be a finite, nonnegative number of seconds")
    return number


def video_source(sid: str) -> tuple[dict, dict]:
    catalog = read(CATALOG)
    source = catalog["sources"][sid]
    if source["kind"] != "videos":
        raise ValueError(f"Source is not an observation video: {sid}")
    return catalog, source


def duration(path) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    value = float(json.loads(result.stdout)["format"]["duration"])
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Video duration is not a positive finite value")
    return value


def extract(path, at: float, destination) -> float | None:
    # Filter selection exposes the selected frame's source presentation time,
    # unlike treating a seek request as an exact camera frame timestamp.
    filter_graph = f"select=gte(t\\,{at:.9f}),showinfo"
    result = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-i", str(path),
                             "-vf", filter_graph, "-fps_mode", "passthrough", "-frames:v", "1", "-update", "1", str(destination)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode or not destination.is_file():
        raise RuntimeError(f"Frame extraction failed: {result.stderr[-1600:]}")
    times = re.findall(r"\bn:\s*\d+\s+pts:\s*\d+\s+pts_time:\s*([\d.eE+-]+)", result.stderr)
    return float(times[0]) if times else None


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


def select_frame(args) -> None:
    catalog, source = video_source(args.source_id)
    bindings = read(BINDINGS)
    binding = next((b for b in bindings["bindings"] if b["asset_id"] == args.asset_id), None)
    if not binding:
        raise ValueError(f"Asset has no formal observation binding: {args.asset_id}")
    source_path = resolve(source["local_path"])
    if args.at >= duration(source_path):
        raise ValueError("Requested timestamp is outside the video")
    if source["sha256"] != checksum(source_path):
        raise ValueError("Original video changed after ingestion")
    sid = args.id or f"{args.source_id}-frame-{round(args.at * 1000):09d}"
    if sid in catalog["sources"]:
        raise ValueError(f"Source ID already exists: {sid}")
    destination = resolve(f"observations/images/{sid}.png")
    if destination.exists():
        raise ValueError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    decoded_at = extract(source_path, args.at, destination)
    entry = source_record(sid, destination, "selected_video_frame", source["redistribution"]["license"],
                          photo_taken_at=None, selection_reason=args.reason,
                          derived_from={"source_ids":[args.source_id],"source_sha256":source["sha256"],
                                        "requested_timestamp_seconds":args.at,"decoded_pts_seconds":decoded_at,
                                        "method":"FFmpeg select first frame at or after requested source presentation time"})
    entry["redistribution"] = dict(source["redistribution"])
    catalog["sources"][sid] = entry
    binding["source_ids"] = sorted(set(binding["source_ids"]) | {sid})
    binding.setdefault("components", []).append({"source_id":sid,"component":args.component,
                                                "control_points":[],"camera_pose":None,"precision":"unregistered"})
    # The frame and both indexes are formal source artifacts; Git commits them together.
    write(CATALOG, catalog)
    write(BINDINGS, bindings)
    print(json.dumps(entry, ensure_ascii=False, indent=2))


def preview_video(args) -> None:
    _, source = video_source(args.source_id)
    source_path = resolve(source["local_path"])
    end = duration(source_path)
    directory = resolve(f"build/processing/observations/{args.source_id}")
    directory.mkdir(parents=True, exist_ok=True)
    # Preview sampling is deliberately separate from acceptance. Reuse previews
    # only when they come from precisely the same registered video content.
    current_hash = checksum(source_path)
    if current_hash != source["sha256"]:
        raise ValueError("Original video changed after ingestion")
    entries = []
    at = 0.0
    while at < end:
        target = directory / f"candidate-{round(at * 1000):09d}.png"
        if target.exists():
            raise ValueError(f"Preview output exists; clear its generated directory before rebuilding: {target}")
        decoded_at = extract(source_path, at, target)
        entries.append({"requested_timestamp_seconds":at,"decoded_pts_seconds":decoded_at,
                        "local_path":target.relative_to(ROOT).as_posix()})
        at += args.interval
    write(directory / "candidates.json", {"source_id":args.source_id,"source_sha256":current_hash,"candidates":entries})
    print(json.dumps({"preview_count":len(entries),"directory":directory.relative_to(ROOT).as_posix()}))


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
    frame_parser = commands.add_parser("select-frame", help="Promote a reviewed source-video timestamp to a formal image")
    frame_parser.add_argument("--source-id", required=True)
    frame_parser.add_argument("--at", required=True, type=timestamp)
    frame_parser.add_argument("--asset-id", required=True)
    frame_parser.add_argument("--reason", required=True, help="What this selected frame contributes to the campus reconstruction")
    frame_parser.add_argument("--component", default=None, help="Known facade, roof, entrance, or other observed component")
    frame_parser.add_argument("--id", type=identifier)
    frame_parser.set_defaults(run=select_frame)
    preview_parser = commands.add_parser("preview-video", help="Create candidate frames in build for visual curation")
    preview_parser.add_argument("--source-id", required=True, type=identifier)
    preview_parser.add_argument("--interval", type=timestamp, default=5.0)
    preview_parser.set_defaults(run=preview_video)
    ignore_parser = commands.add_parser("export-ignore", help="Derive the Git ignore block from current source permissions")
    ignore_parser.add_argument("--write", action="store_true", help="Refresh only the observation permission block in repository .gitignore")
    ignore_parser.set_defaults(run=export_ignore)
    args = parser.parse_args()
    if getattr(args,"interval",1) <= 0:
        parser.error("Preview interval must be positive")
    try:
        args.run(args)
    except (ValueError, KeyError, FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
