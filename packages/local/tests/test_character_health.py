"""キャラクター別最大体力のユニットテスト（ADR-050）"""

import json
from pathlib import Path

import pytest

from src.character.health import FALLBACK_MAX_HEALTH, CharacterHealthTable, load_character_health

SCHEMA_PATH = Path(__file__).parent.parent.parent.parent / "schema" / "character_health.json"


class TestCharacterHealthTable:
    def test_lookup_is_case_insensitive(self):
        table = CharacterHealthTable({"GOUKI": 9000}, default=10000)
        assert table.max_health("GOUKI") == 9000
        assert table.max_health("gouki") == 9000

    def test_unknown_character_uses_default(self):
        table = CharacterHealthTable({"GOUKI": 9000}, default=10000)
        assert table.max_health("BOSCH") == 10000
        assert table.max_health(None) == 10000

    def test_warn_unknown_lists_characters(self):
        table = CharacterHealthTable({"RYU": 10000}, default=10000)
        assert table.warn_unknown({"RYU", "BOSCH", None}) == ["BOSCH"]

    def test_load_from_repository_schema(self):
        assert SCHEMA_PATH.exists(), f"schema が見つかりません: {SCHEMA_PATH}"
        table = load_character_health(str(SCHEMA_PATH))
        assert table.max_health("GOUKI") == 9000
        assert table.max_health("ZANGIEF") == 11000
        assert table.max_health("MARISA") == 10500
        assert table.max_health("RYU") == 10000  # 既定値

    def test_load_missing_file_falls_back(self, tmp_path):
        table = load_character_health(str(tmp_path / "not_found.json"))
        assert table.max_health("RYU") == FALLBACK_MAX_HEALTH

    def test_schema_file_is_valid_json_with_required_keys(self):
        data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert isinstance(data["default"], int)
        assert all(isinstance(v, int) for v in data["characters"].values())


class TestJsonSchema:
    def test_matches_json_schema(self):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads((SCHEMA_PATH.parent / "character_health.schema.json").read_text(encoding="utf-8"))
        data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)
