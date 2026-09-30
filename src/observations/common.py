"""The single current observation catalog; no legacy readers or parallel indexes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "observations/catalog.json"
BINDINGS = ROOT / "observations/bindings/assets.json"
KINDS = ("images", "videos", "plans", "maps", "spatial", "documents")
PUBLIC_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "ODbL-1.0"}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def resolve(relative: str) -> Path:
    """Resolve only portable repository paths, never a path supplied by an archive."""
    if "\\" in relative or Path(relative).is_absolute() or ":" in relative:
        raise ValueError(f"Expected a relative forward-slash path: {relative}")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Path leaves the repository: {relative}")
    return path


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redistribution(license_name: str) -> dict:
    return {"license": license_name, "status": "allowed" if license_name in PUBLIC_LICENSES else "local_only"}


def source_record(identifier: str, path: Path, kind: str, license_name: str, **fields) -> dict:
    return {
        "id": identifier,
        "local_path": path.relative_to(ROOT).as_posix(),
        "kind": kind,
        "bytes": path.stat().st_size,
        "sha256": checksum(path),
        "photo_taken_at": None,
        "published_at": None,
        "retrieved_at": now(),
        "status": "available",
        "redistribution": redistribution(license_name),
        **fields,
    }
