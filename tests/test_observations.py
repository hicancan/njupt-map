"""Verify source preservation, selected-frame lineage, and publication boundaries."""
from __future__ import annotations

import argparse
import os
from contextlib import ExitStack, redirect_stdout
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.observations import __main__ as cli
from src.observations import common
from src.observations import validate as validator


class ObservationPipelineTest(unittest.TestCase):
    def setUp(self):
        task_root = (Path("D:/Temp/codex/njupt-map-observations-test") if os.name == 'nt'
                     else Path(tempfile.gettempdir()) / 'njupt-map-tests')
        task_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=task_root)
        self.root = Path(self.temporary.name).resolve()
        self.stack = ExitStack()
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        catalog = self.root / "observations/catalog.json"
        bindings = self.root / "observations/bindings/assets.json"
        for module in (common, cli, validator):
            for name, value in (("ROOT", self.root), ("CATALOG", catalog), ("BINDINGS", bindings)):
                if hasattr(module, name):
                    self.stack.enter_context(patch.object(module, name, value))
        common.write(catalog, {"schema_version":1,"sources":{}})
        common.write(bindings, {"schema_version":1,"bindings":[{"asset_id":"building-a","observation_group":None,
                            "source_ids":[],"floorplans":[],"assertions":[],
                            "spatial_binding":{"coordinate_frame":"campus_local_m"}}]})
        common.write(self.root / "observations/bindings/groups.json", {"schema_version":1,"groups":[]})

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def test_paths_cannot_leave_repository(self):
        for relative in ("../secret", "C:/secret", "observations\\image.png"):
            with self.assertRaises(ValueError):
                common.resolve(relative)

    def test_unknown_source_is_preserved_and_local_only(self):
        original = self.root / "original.bin"
        original.write_bytes(b"original source bytes")
        cli.ingest(argparse.Namespace(file=original,id="source-a",kind="documents",license="unknown",
                                      captured_at=None,source_url=None,reason=None))
        source = common.read(common.CATALOG)["sources"]["source-a"]
        self.assertEqual(source["redistribution"]["status"], "local_only")
        self.assertEqual(common.resolve(source["local_path"]).read_bytes(), original.read_bytes())
        self.assertTrue(validator.validate(hashes=True,strict_local=True)["valid"])

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_public_validation_rejects_tracked_unknown_media(self):
        original = self.root / "restricted.bin"
        original.write_bytes(b"restricted source")
        cli.ingest(argparse.Namespace(file=original,id="restricted-a",kind="documents",license="unknown",
                                      captured_at=None,source_url=None,reason=None))
        subprocess.run(["git","init","-q"], cwd=self.root, check=True)
        subprocess.run(["git","add","observations/documents/restricted-a.bin"], cwd=self.root, check=True)
        result = validator.validate(public=True)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Local-only source must not be publicly tracked" in e for e in result["errors"]))

    def test_permission_ignore_block_is_generated_and_idempotent(self):
        original = self.root / "restricted.bin"
        original.write_bytes(b"restricted source")
        cli.ingest(argparse.Namespace(file=original,id="restricted-a",kind="documents",license="unknown",
                                      captured_at=None,source_url=None,reason=None))
        (self.root / ".gitignore").write_text("/.venv/\n/build/\n", encoding="utf-8")
        cli.export_ignore(argparse.Namespace(write=True))
        first = (self.root / ".gitignore").read_text(encoding="utf-8")
        cli.export_ignore(argparse.Namespace(write=True))
        self.assertEqual(first, (self.root / ".gitignore").read_text(encoding="utf-8"))
        self.assertIn("/observations/documents/restricted-a.bin", first)
        self.assertIn("/.venv/", first)



if __name__ == "__main__":
    unittest.main()
