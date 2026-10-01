"""Exact bytes and separately labelled canonical identities of exporter inputs."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import pyproj
import shapely


def canonical_json_sha256(content):
    value = json.loads(content)
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def pipeline_source_hashes(root: Path):
    """Hash a path-to-content-hash map; raw byte identity is never normalized.

    The separate LF digest ignores only CRLF/LF checkout differences. Including
    map/*.py closes the previous runtime-only producer provenance gap.
    """
    files = sorted([*(root/'src/map').glob('*.py'), *(root/'src/runtime').glob('*.py')])
    raw, lf = {}, {}
    for path in files:
        name = path.relative_to(root).as_posix()
        content = path.read_bytes()
        raw[name] = hashlib.sha256(content).hexdigest()
        lf[name] = hashlib.sha256(content.replace(b'\r\n', b'\n')).hexdigest()

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

    return {'pipeline_sources_sha256': digest(raw),
            'pipeline_sources_lf_sha256': digest(lf),
            'pipeline_sources_hash_format': 'sha256-of-sorted-compact-json-path-to-sha256-v1',
            'pipeline_sources': list(raw)}


def toolchain(root: Path):
    return {'pipeline': 'njupt-map-runtime-v2',
            'python': platform.python_version(),
            'python_implementation': platform.python_implementation(),
            'system': platform.system(), 'machine': platform.machine(),
            'shapely': shapely.__version__, 'geos': shapely.geos_version_string,
            'pyproj': pyproj.__version__, 'proj': pyproj.proj_version_str,
            'dependencies': 'uv.lock',
            'uv_lock_sha256': hashlib.sha256((root/'uv.lock').read_bytes()).hexdigest(),
            **pipeline_source_hashes(root)}
