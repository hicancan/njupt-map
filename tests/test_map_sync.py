import json
from pathlib import Path

from src.map.authored import load_authored, source_digest
from src.map.build_authored import main as build_main
from src.map.validate import validate

def test_authored_layers_are_the_only_map_input():
    campus = load_authored()
    assert len(campus['buildings']) == 116
    assert len(source_digest()) == 64
    assert validate()['passed']

def test_authored_build_contract(tmp_path, monkeypatch):
    monkeypatch.setattr('src.map.build_authored.OUT', tmp_path / 'space')
    monkeypatch.setattr('src.map.build_authored.OBS', Path('missing-routes.jsonl'))
    build_main()
    checks = json.loads((tmp_path / 'space' / 'checks.json').read_text(encoding='utf-8'))
    assert checks['passed']
