"""Inspect or synchronize both native campus scenes by stable map identity.

The default is read-only. --apply updates placement only after both scenes pass
the same geometry/identity review; authored geometry and presentation survive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from src.map.store import ROOT, SOURCE, load_campus
from .plan import CATALOG, make_plan

SCENES = {"campus": ROOT / "projects/blender/campus.blend",
          "film": ROOT / "projects/blender/presentation/film.blend"}
OUTPUT = ROOT / "build/checks/sync"


def digest(path: Path):
    with path.open("rb") as stream:
        result = hashlib.file_digest(stream, "sha256")
    return result.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def plans_for_scenes(campus, catalog, actual_by_scene):
    """Review every scene against its actual instances, never just the catalog."""
    return {name: make_plan(campus, catalog, actual) for name, actual in actual_by_scene.items()}


def synchronize(blender: str, apply=False):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inputs = [SOURCE, CATALOG, *SCENES.values()]
    baseline = {path: digest(path) for path in inputs}
    asset_files = sorted((ROOT / "projects/blender/buildings").glob("*.blend"))
    asset_hashes = {path: digest(path) for path in asset_files}
    campus = load_campus()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    actual_by_scene = {}

    def inspect(name, scene, plan_path=None):
        actual_path = OUTPUT / f"{name}.instances.json"
        log_path = OUTPUT / f"{name}.{'apply' if plan_path else 'inspect'}.log"
        command = [blender, "--background", "--factory-startup", str(scene), "--python-exit-code", "1",
                   "--python", str(ROOT / "src/sync/apply.py"), "--", "--output", str(actual_path)]
        if plan_path:
            command.extend(["--plan", str(plan_path), "--apply"])
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"Blender {name} inspection failed; see {log_path}")
        return json.loads(actual_path.read_text(encoding="utf-8"))

    for name, scene in SCENES.items():
        actual_by_scene[name] = inspect(name, scene)
    plans = plans_for_scenes(campus, catalog, actual_by_scene)
    for name, plan in plans.items():
        plan.update(source_file_sha256=baseline[SOURCE], catalog_file_sha256=baseline[CATALOG])
        write_json(OUTPUT / f"{name}.plan.json", plan)
    # Even a read-only check must demonstrate it did not rewrite the sources.
    if any(digest(path) != expected for path, expected in baseline.items()):
        raise RuntimeError("Native source changed during inspection; regenerate plans after concurrent edits finish")
    all_ready = all(plan["ready_to_apply"] for plan in plans.values())
    operations = sum(len(plan["operations"]) for plan in plans.values())
    report = {"schema_version": 1, "applied": False, "ready_to_apply": all_ready,
              "synchronized": all_ready and operations == 0,
              "scenes": {name: {"instances": len(actual_by_scene[name]), "operations": len(plan["operations"]),
                                 "issues": plan["issues"]} for name, plan in plans.items()},
              "native_sources_unchanged": True, "authored_assets_unchanged": True}
    if apply and all_ready and operations:
        for name, scene in SCENES.items():
            # The preceding scene may have updated the shared accepted-placement
            # catalog. Replan from the current catalog and this scene's own snapshot.
            if digest(SOURCE) != baseline[SOURCE] or digest(scene) != baseline[scene]:
                raise RuntimeError(f"Source or {name} scene changed after all-scene review")
            current_catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
            plan = make_plan(campus, current_catalog, actual_by_scene[name])
            if not plan["ready_to_apply"]:
                raise RuntimeError(f"{name} geometry/identity changed after all-scene review")
            plan.update(source_file_sha256=digest(SOURCE), catalog_file_sha256=digest(CATALOG))
            plan_path = OUTPUT / f"{name}.plan.json"
            write_json(plan_path, plan)
            if plan["operations"]:
                actual_by_scene[name] = inspect(name, scene, plan_path)
        current_catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        final = plans_for_scenes(campus, current_catalog, actual_by_scene)
        if any(not p["ready_to_apply"] or p["operations"] for p in final.values()):
            raise RuntimeError("Synchronization left unresolved native scene placement differences")
        report["applied"] = True
        report["synchronized"] = True
        report["native_sources_unchanged"] = False
        report["scenes"] = {name: {"instances": len(actual_by_scene[name]), "operations": 0, "issues": []} for name in SCENES}
    if any(digest(path) != expected for path, expected in asset_hashes.items()):
        raise RuntimeError("An authored building source changed during spatial synchronization")
    write_json(OUTPUT / "summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", default=shutil.which("blender"), help="Blender executable; defaults to PATH")
    parser.add_argument("--apply", action="store_true", help="Update both scenes after all identity/geometry checks pass")
    args = parser.parse_args()
    if not args.blender:
        parser.error("Blender not found; provide --blender with its executable path")
    report = synchronize(args.blender, args.apply)
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["synchronized"] else 1)


if __name__ == "__main__":
    main()
