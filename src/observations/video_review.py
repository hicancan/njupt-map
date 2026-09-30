"""Decode full video timelines and validate persistent human shot annotations.

Candidates and contact sheets are disposable build outputs. This module never
promotes a frame, edits a source catalog, or infers a campus from a video title.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sqlite3
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import CATALOG, ROOT, checksum, read, resolve, write

OUTPUT = ROOT / "build/processing/observations/video-review"
PTS = re.compile(r"\bn:\s*\d+\s+pts:\s*(-?\d+)\s+pts_time:\s*([\d.eE+-]+)")
CAMPUS = {"xianlin", "sanpailou", "other", "unknown"}
STATUS = {"accepted", "excluded", "unknown"}


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height,avg_frame_rate,time_base,start_time,duration:format=duration",
                             "-of", "json", str(path)], check=True, capture_output=True,
                            text=True, encoding="utf-8")
    info = json.loads(result.stdout)
    if not info.get("streams"):
        raise ValueError(f"No video stream: {path}")
    stream = info["streams"][0]
    stream["duration_seconds"] = float(info["format"]["duration"])
    if not math.isfinite(stream["duration_seconds"]) or stream["duration_seconds"] <= 0:
        raise ValueError("Video duration must be positive and finite")
    return stream


def _run_decode(path: Path, output: Path, expression: str, pass_name: str,
                *, full_resolution: bool = False) -> list[dict]:
    # Each pass decodes sequentially once. There is no per-candidate seek loop.
    graph = ("" if full_resolution else
             "scale=240:135:force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv444p,"
             "pad=240:135:(ow-iw)/2:(oh-ih)/2,setsar=1,")
    graph += f"select='{expression}',showinfo,metadata=print:file={pass_name}-metadata.txt"
    prefix = "detail" if full_resolution else "frame"
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-y",
               "-copyts", "-i", str(path), "-an", "-vf", graph,
               "-fps_mode", "passthrough", "-enc_time_base", "1/1000",
               "-frame_pts", "1", "-q:v", "2" if full_resolution else "3", f"{prefix}-%010d.jpg"]
    result = subprocess.run(command, cwd=output, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    (output / f"{pass_name}-decode.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"FFmpeg failed for {path.name}: {result.stderr[-2000:]}")
    time_base_match = re.search(r"config in time_base:\s*(\d+/\d+)", result.stderr)
    time_base = Fraction(time_base_match[1]) if time_base_match else None
    available = {int(file.stem.split("-")[-1]): file.name for file in output.glob(f"{prefix}-*.jpg")}
    frames = []
    for pts, printed_time in PTS.findall(result.stderr):
        actual = float(int(pts) * time_base) if time_base is not None else float(printed_time)
        milliseconds = min(available, key=lambda value: abs(value - actual * 1000))
        if abs(milliseconds - actual * 1000) > 1:
            raise RuntimeError(f"Encoded PTS filename does not match decoded source PTS: {actual}")
        frames.append({"decoded_pts": int(pts), "time_base": str(time_base),
                       "decoded_pts_seconds": actual, "pts_milliseconds": milliseconds,
                       "path": available[milliseconds]})
    meta = output / f"{pass_name}-metadata.txt"
    scores = {}
    if meta.exists():
        current = None
        for line in meta.read_text(encoding="utf-8").splitlines():
            match = re.search(r"\bpts:(-?\d+)", line)
            if match:
                current = int(match[1])
            elif current is not None and line.startswith("lavfi.scene_score="):
                scores[current] = float(line.split("=", 1)[1])
    for frame in frames:
        if not (output / frame["path"]).is_file():
            raise RuntimeError(f"Missing decoded frame at {frame['decoded_pts_seconds']}")
        frame["scene_score"] = scores.get(frame["decoded_pts"])
    return frames


def _font(size: int):
    candidates = [Path("C:/Windows/Fonts/msyh.ttc"),
                  Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    return next((ImageFont.truetype(str(path), size) for path in candidates if path.is_file()),
                ImageFont.load_default(size=size))


def time_label(value: float) -> str:
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


def detailed_frames(sid: str, source: dict, requested_times: list[float],
                    output_root: Path = OUTPUT) -> dict:
    """Extract several original-resolution inspection frames in one decode."""
    path = resolve(source["local_path"])
    if checksum(path) != source["sha256"]:
        raise ValueError(f"Registered source content changed: {sid}")
    end = probe(path)["duration_seconds"]
    times = sorted(set(requested_times))
    if not times or any(not math.isfinite(at) or not 0 <= at < end for at in times):
        raise ValueError("Inspection timestamps must lie inside video")
    bvid = source.get("platform_identifiers", {}).get("bvid", sid)
    output = (output_root / bvid).resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", bvid) or not output.is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Inspection frames must stay under build/")
    output.mkdir(parents=True, exist_ok=True)
    expression = "+".join(f"gte(t,{at:.9f})*(isnan(prev_t)+lt(prev_t,{at:.9f}))" for at in times)
    frames = _run_decode(path, output, expression, "details", full_resolution=True)
    for frame in frames:
        candidates = [at for at in times if at <= frame["decoded_pts_seconds"] + 1e-9]
        frame["requested_timestamp_seconds"] = max(candidates)
    result = {"source_id": sid, "source_sha256": source["sha256"], "redistribution": source["redistribution"],
              "method": "One sequential decode; first original-resolution source frame at or after each request",
              "frames": frames}
    write(output / "details.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def contact_sheets(output: Path, sid: str, frames: list[dict]) -> list[dict]:
    pages = []
    font = _font(15)
    heading_font = _font(21)
    for first in range(0, len(frames), 64):
        batch = frames[first:first + 64]
        page = Image.new("RGB", (1920, 40 + 8 * 160), "#15191f")
        draw = ImageDraw.Draw(page)
        draw.text((12, 7), f"{sid} | {time_label(batch[0]['decoded_pts_seconds'])} – "
                  f"{time_label(batch[-1]['decoded_pts_seconds'])} | page {first // 64 + 1}",
                  fill="white", font=heading_font)
        for index, frame in enumerate(batch):
            x, y = index % 8 * 240, 40 + index // 8 * 160
            with Image.open(output / frame["path"]) as source:
                page.paste(source.convert("RGB"), (x, y))
            tags = ",".join(frame["selection"])
            draw.text((x + 4, y + 138), f"{time_label(frame['decoded_pts_seconds'])} {tags}",
                      fill="#ffca6a" if "cut" in frame["selection"] else "#e3e8ee", font=font)
        name = f"sheet-{first // 64 + 1:03d}.jpg"
        page.save(output / name, quality=92)
        pages.append({"path": name, "first_frame_index": first,
                      "last_frame_index": first + len(batch) - 1,
                      "start_pts_seconds": batch[0]["decoded_pts_seconds"],
                      "end_pts_seconds": batch[-1]["decoded_pts_seconds"]})
    return pages


def prepare(sid: str, source: dict, interval: float | None = None, threshold: float = .22,
            output_root: Path = OUTPUT) -> dict:
    path = resolve(source["local_path"])
    digest = checksum(path)
    if source["sha256"] != digest:
        raise ValueError(f"Registered source content changed: {sid}")
    technical = probe(path)
    interval = interval or (2.0 if technical["duration_seconds"] >= 1800 else 1.0)
    if not math.isfinite(interval) or interval <= 0 or not 0 < threshold < 1:
        raise ValueError("Invalid sampling interval or scene threshold")
    bvid = source.get("platform_identifiers", {}).get("bvid", sid)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", bvid):
        raise ValueError("Unsafe output ID")
    output = (output_root / bvid).resolve()
    if not output.is_relative_to(output_root.resolve()) or not output_root.resolve().is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Candidate outputs must remain under repository build/")
    output.mkdir(parents=True, exist_ok=True)
    # Exactly the generated patterns owned by this tool; never original media.
    for pattern in ("frame-*.jpg", "sheet-*.jpg"):
        for previous in output.glob(pattern):
            previous.unlink()
    expression = (f"isnan(prev_t)+gt(floor(t/{interval:.9f}),floor(prev_t/{interval:.9f}))"
                  f"+gt(scene,{threshold:.9f})")
    first = _run_decode(path, output, expression, "timeline")
    cuts = [frame["decoded_pts_seconds"] for frame in first
            if frame.get("scene_score") is not None and frame["scene_score"] > threshold]
    # Consecutive source frames immediately around a cut protect short inserts
    # that do not coincide with the regular one/two-second timeline grid.
    neighbours = []
    if cuts:
        expression = "+".join(f"between(t,{max(0, t-.12):.9f},{t+.12:.9f})" for t in cuts)
        neighbours = _run_decode(path, output, expression, "cut-neighbours")
    merged = {f["pts_milliseconds"]: {**f, "selection": []} for f in first}
    previous = -1
    for frame in first:
        tags = merged[frame["pts_milliseconds"]]["selection"]
        grid = math.floor(frame["decoded_pts_seconds"] / interval + 1e-6)
        if grid > previous:
            tags.append("grid")
            previous = grid
        if frame.get("scene_score") is not None and frame["scene_score"] > threshold:
            tags.append("cut")
    for frame in neighbours:
        current = merged.setdefault(frame["pts_milliseconds"], {**frame, "selection": []})
        current["selection"].append("near-cut")
    frames = sorted(merged.values(), key=lambda f: f["decoded_pts_seconds"])
    if not frames:
        raise RuntimeError("Decoded timeline contains no frames")
    pages = contact_sheets(output, sid, frames)
    manifest = {"source_id": sid, "source_sha256": digest, "source_url": source.get("url"),
                "redistribution": source.get("redistribution"), "technical": technical,
                "duration_seconds": technical["duration_seconds"],
                "sampling": {"interval_seconds": interval, "scene_threshold": threshold,
                             "near_cut_seconds": .12,
                             "method": "Full sequential decode, source-PTS grid and scene-change union; second sequential pass for cut neighbours",
                             "limitations": "Threshold scene detection and sparse frames are review aids, not proof that all visual changes or places were identified"},
                "scene_cuts_seconds": cuts, "frames": frames, "sheets": pages}
    write(output / "manifest.json", manifest)
    print(json.dumps({"source_id": sid, "frames": len(frames), "cuts": len(cuts),
                      "sheets": len(pages), "output": str(output)}, ensure_ascii=False), flush=True)
    return manifest


def validate_annotation(annotation: dict, sources: dict, asset_ids: set[str],
                        map_feature_ids: set[str], place_ids: set[str] | None = None) -> list[str]:
    errors = []
    sid = annotation.get("source_id")
    source = sources.get(sid)
    if not source or source.get("kind") != "videos":
        return [f"Unknown observation video: {sid}"]
    if annotation.get("source_sha256") != source.get("sha256"):
        errors.append("Annotation source hash does not match catalog")
    duration = annotation.get("duration_seconds")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        return errors + ["Invalid annotation duration"]
    catalog_duration = source.get("technical", {}).get("duration_seconds")
    if catalog_duration is not None and abs(duration - catalog_duration) > .1:
        errors.append("Annotation duration does not match registered video")
    cursor = 0.0
    segments = annotation.get("segments", [])
    if not segments:
        errors.append("No reviewed segments")
    for index, segment in enumerate(segments):
        prefix = f"Segment {index}: "
        start, end = segment.get("start_seconds"), segment.get("end_seconds")
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)):
            errors.append(prefix + "Invalid segment times")
            continue
        if abs(start - cursor) > .001:
            errors.append(prefix + "Timeline gap or overlap")
        if start < 0 or end <= start or end > duration + .001:
            errors.append(prefix + "Segment is outside video or empty")
        cursor = end
        if segment.get("campus") not in CAMPUS:
            errors.append(prefix + "Unknown campus classification")
        if segment.get("status") not in STATUS:
            errors.append(prefix + "Unknown review status")
        if segment.get("status") == "accepted" and segment.get("campus") != "xianlin":
            errors.append(prefix + "Only Xianlin footage may enter current modeling set")
        if segment.get("status") == "excluded" and not segment.get("exclusion_reason"):
            errors.append(prefix + "Exclusion requires a reason")
        if segment.get("status") == "unknown" and not segment.get("basis"):
            errors.append(prefix + "Unknown requires an explicit limitation")
        for field, allowed in (("asset_ids", asset_ids), ("map_object_ids", asset_ids), ("map_feature_ids", map_feature_ids)):
            for identifier in segment.get(field, []):
                if identifier not in allowed:
                    errors.append(prefix + f"Unknown {field} reference: {identifier}")
        if place_ids is not None:
            for identifier in segment.get("place_ids", []):
                if identifier not in place_ids:
                    errors.append(prefix + f"Unknown place reference: {identifier}")
        for field in ("selected_frame_pts_seconds", "review_frame_pts_seconds"):
            for at in segment.get(field, []):
                if not isinstance(at, (int, float)) or not start <= at < end:
                    errors.append(prefix + f"{field} frame is outside its segment")
        for edge in segment.get("observed_connections", []):
            if edge.get("basis") not in {"continuous_shot", "plan", "cross_reference", "inferred"}:
                errors.append(prefix + "Topology relation lacks a valid observation basis")
            if place_ids is not None and any(edge.get(k) not in place_ids for k in ("from_place_id", "to_place_id")):
                errors.append(prefix + "Topology relation references an unknown place")
    if abs(cursor - duration) > .001:
        errors.append("Timeline does not finish at video duration")
    return errors


def _map_ids(column: str) -> set[str]:
    if column not in {"asset_id", "map_feature_id"}:
        raise ValueError("Unsupported map identity column")
    database = ROOT / "projects/map/campus.gpkg"
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        result = set()
        for table, in connection.execute("SELECT table_name FROM gpkg_contents"):
            columns = [r[1] for r in connection.execute(f'PRAGMA table_info("{table}")')]
            if column in columns:
                result.update(r[0] for r in connection.execute(f'SELECT {column} FROM "{table}"') if r[0])
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-id", action="append")
    group.add_argument("--all", action="store_true")
    group.add_argument("--validate", type=Path, help="Validate one persistent annotation JSON")
    parser.add_argument("--interval", type=float, default=None)
    parser.add_argument("--scene-threshold", type=float, default=.22)
    parser.add_argument("--max-duration", type=float, default=None)
    parser.add_argument("--places", type=Path, help="Optional JSON containing places keyed by common place ID")
    parser.add_argument("--full-at", nargs="+", type=float, help="Extract original-resolution detail candidates at these source times")
    args = parser.parse_args()
    sources = read(CATALOG)["sources"]
    if args.validate:
        assets = _map_ids("asset_id")
        places = None
        if args.places:
            places = set(read(args.places)["places"])
        errors = validate_annotation(read(args.validate), sources, assets, _map_ids("map_feature_id"), places)
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        raise SystemExit(bool(errors))
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        parser.error("FFmpeg and FFprobe must be installed and available in PATH")
    selected = args.source_id or [sid for sid, source in sources.items()
                                 if source.get("kind") == "videos" and source.get("platform") == "bilibili"]
    selected.sort(key=lambda sid: sources[sid].get("technical", {}).get("duration_seconds", math.inf))
    if args.full_at and len(selected) != 1:
        parser.error("--full-at requires exactly one --source-id")
    for sid in selected:
        source = sources[sid]
        if source.get("kind") != "videos":
            parser.error(f"Not a video source: {sid}")
        if args.max_duration and source.get("technical", {}).get("duration_seconds", math.inf) > args.max_duration:
            continue
        if args.full_at:
            detailed_frames(sid, source, args.full_at)
        else:
            prepare(sid, source, args.interval, args.scene_threshold)


if __name__ == "__main__":
    main()
