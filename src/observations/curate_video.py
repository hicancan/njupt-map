"""Promote explicitly reviewed current-video PTS to persistent source images.

The decisions come only from formal annotations. Preview manifests and machine
validation reports never become facts. One sequential source decode per video
preserves native resolution, exact source PTS and inherited media permissions.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import math
from fractions import Fraction

from .common import BINDINGS, CATALOG, ROOT, checksum, read, resolve, source_record, write

ANNOTATIONS = ROOT / "observations/annotations/video-review"


def selections(annotation: dict) -> dict[float, dict]:
    result = {}
    for segment in annotation["segments"]:
        for pts in segment.get("selected_frame_pts_seconds", []):
            if not isinstance(pts, (int, float)) or not math.isfinite(pts):
                raise ValueError("Curated PTS must be finite")
            if (segment["status"] != "accepted" or segment["campus"] != "xianlin"
                    or segment.get("eligibility") != "current_candidate"):
                raise ValueError("Excluded or unknown footage cannot be promoted as current modeling input")
            if not segment["start_seconds"] <= pts < segment["end_seconds"]:
                raise ValueError("Curated PTS leaves its reviewed segment")
            if pts in result:
                raise ValueError("A selected PTS must belong to exactly one segment")
            result[pts] = segment
    return result


def promote(annotation: dict, catalog: dict, bindings: dict) -> int:
    sid = annotation["source_id"]
    source = catalog["sources"][sid]
    path = resolve(source["local_path"])
    if source["sha256"] != annotation["source_sha256"] or checksum(path) != source["sha256"]:
        raise ValueError(f"Source identity changed: {sid}")
    chosen = selections(annotation)
    if not chosen:
        return 0
    bound_assets = {binding["asset_id"] for binding in bindings["bindings"]}
    if any(set(segment.get("asset_ids", [])) - bound_assets for segment in chosen.values()):
        raise ValueError("Selected observation references an unknown building asset")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=time_base", "-of", "json", str(path)], capture_output=True,
                           text=True, encoding="utf-8", check=True)
    base = Fraction(json.loads(probe.stdout)["streams"][0]["time_base"])
    ticks = {}
    for pts, segment in chosen.items():
        tick = round(Fraction(str(pts)) / base)
        if abs(float(tick * base) - pts) > 1e-7:
            raise ValueError(f"Selected time is not an actual source PTS: {sid} at {pts}")
        ticks[tick] = (pts, segment)
    bvid = source["platform_identifiers"]["bvid"]
    if not re.fullmatch(r"[A-Za-z0-9]+", bvid):
        raise ValueError("Unsafe video identity")
    output = resolve(f"observations/images/bilibili/{bvid}")
    output.mkdir(parents=True, exist_ok=True)
    pending = {}
    for tick, (pts, segment) in ticks.items():
        frame_id = f"{sid}-frame-pts-{tick:012d}"
        existing = catalog["sources"].get(frame_id)
        if existing:
            lineage = existing.get("derived_from", {})
            if lineage.get("source_sha256") != source["sha256"] or lineage.get("decoded_pts") != tick:
                raise ValueError("Existing curated identity refers to different footage")
            if checksum(resolve(existing["local_path"])) != existing["sha256"]:
                raise ValueError("Existing curated image was changed; preserve authored source work")
            expected_path = f"observations/annotations/video-review/{bvid}.json"
            expected_parents = {field: set(segment.get(field, [])) for field in
                                ("asset_ids", "map_feature_ids", "map_object_ids", "place_ids")}
            spatial = existing.get("spatial_binding", {})
            if (existing.get("annotation_path") != expected_path
                    or existing.get("annotation_segment_id") != segment["id"]
                    or existing.get("redistribution") != source["redistribution"]
                    or existing.get("temporal_status") != "current_candidate"
                    or any(set(spatial.get(field, [])) != value for field, value in expected_parents.items())):
                raise ValueError("Existing curated metadata differs; reconcile formal annotations and bindings before reusing the image")
            associated = {b["asset_id"] for b in bindings["bindings"] if frame_id in b.get("source_ids", [])}
            if associated != expected_parents["asset_ids"]:
                raise ValueError("Existing curated asset references differ; reconcile formal bindings before rerunning")
            if frame_id not in segment.get("selected_frame_source_ids", []):
                segment.setdefault("selected_frame_source_ids", []).append(frame_id)
        else:
            pending[tick] = (pts, segment)
    if not pending:
        return 0
    staging = resolve(f"build/processing/observations/curation/{bvid}")
    staging.mkdir(parents=True, exist_ok=True)
    expression = "+".join(f"eq(pts,{tick})" for tick in pending)
    # Only explicitly selected source timestamps, native image dimensions.
    result = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-y",
                             "-copyts", "-i", str(path), "-an", "-vf", f"select='{expression}',showinfo",
                             "-fps_mode", "passthrough", "-enc_time_base", str(base), "-frame_pts", "1",
                             "-compression_level", "4", "selected-pts-%012d.png"], cwd=staging,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr[-1600:])
    decoded = [int(v) for v in re.findall(r"\bn:\s*\d+\s+pts:\s*(-?\d+)\s+pts_time:", result.stderr)]
    if set(decoded) != set(pending) or len(decoded) != len(pending):
        raise ValueError("Selected time is not an actual source PTS of a decoded frame")
    # Validate every output before moving any image into formal observations.
    for tick in decoded:
        pts, segment = pending[tick]
        staged = staging / f"selected-pts-{tick:012d}.png"
        frame = output / staged.name
        if not staged.is_file():
            raise RuntimeError("Encoded filename and source PTS differ")
        if frame.exists() and checksum(frame) != checksum(staged):
            raise ValueError(f"Refusing to replace an existing source image: {frame}")
    for tick in decoded:
        pts, segment = pending[tick]
        staged = staging / f"selected-pts-{tick:012d}.png"
        frame = output / staged.name
        if not frame.exists():
            staged.replace(frame)
        else:
            staged.unlink()
        frame_id = f"{sid}-frame-pts-{tick:012d}"
        entry = source_record(frame_id, frame, "selected_video_frame", source["redistribution"]["license"],
                              selection_reason=" / ".join(segment.get("observed_features", [])) or segment["place_label"],
                              url=source.get("url"), published_at=source.get("published_at"),
                              temporal_status="current_candidate", annotation_segment_id=segment["id"],
                              annotation_path=f"observations/annotations/video-review/{bvid}.json",
                              spatial_binding={"status": "semantic_only", "asset_ids": segment.get("asset_ids", []),
                                               "map_feature_ids": segment.get("map_feature_ids", []),
                                               "map_object_ids": segment.get("map_object_ids", []),
                                               "place_ids": segment.get("place_ids", []),
                                               "coordinate_frame": "campus_local_m", "camera_pose": None,
                                               "control_points": [], "precision": "unregistered"},
                              derived_from={"source_ids": [sid], "source_sha256": source["sha256"],
                                            "requested_timestamp_seconds": pts, "decoded_pts_seconds": float(tick * base),
                                            "decoded_pts": tick, "time_base": str(base),
                                            "method": "FFmpeg exact source integer PTS selection, native-resolution PNG"})
        entry["redistribution"] = dict(source["redistribution"])
        catalog["sources"][frame_id] = entry
        segment.setdefault("selected_frame_source_ids", []).append(frame_id)
        for aid in segment.get("asset_ids", []):
            binding = next(b for b in bindings["bindings"] if b["asset_id"] == aid)
            binding["source_ids"] = sorted(set(binding["source_ids"]) | {frame_id})
            binding.setdefault("components", []).append({"source_id": frame_id, "component": segment["place_label"],
                                                         "annotation_segment_id": segment["id"],
                                                         "annotation_path": entry["annotation_path"],
                                                         "temporal_status": "current_candidate",
                                                         "control_points": [], "camera_pose": None,
                                                         "precision": "unregistered"})
    return len(decoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", help="Otherwise promote all formal annotations")
    args = parser.parse_args()
    catalog, bindings = read(CATALOG), read(BINDINGS)
    count = 0
    for annotation_path in sorted(ANNOTATIONS.glob("*.json")):
        annotation = read(annotation_path)
        if args.source_id and annotation["source_id"] != args.source_id:
            continue
        from .video_review import validate_annotation, _map_ids
        topology = read(ROOT / "observations/bindings/topology.json")
        errors = validate_annotation(annotation, catalog["sources"],
                                     _map_ids("asset_id"), _map_ids("map_feature_id"), set(topology["places"]))
        if errors:
            raise ValueError("Formal annotation is invalid: " + "; ".join(errors))
        count += promote(annotation, catalog, bindings)
        write(CATALOG, catalog)
        write(BINDINGS, bindings)
        write(annotation_path, annotation)
    print(json.dumps({"promoted_frame_count": count}))


if __name__ == "__main__":
    main()
