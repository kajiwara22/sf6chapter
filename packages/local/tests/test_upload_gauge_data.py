"""R2 反映 CLI（ADR-048/049/050）のユニットテスト

scripts/ はパッケージではないため importlib で読み込む。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "upload_gauge_data.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("upload_gauge_data", SCRIPT_PATH)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class TestParseRoundCount:
    def test_parses_list_string(self, module):
        assert module.parse_round_count("[0, 0]") == 2
        assert module.parse_round_count("[1, 0, 1]") == 3

    def test_parses_list(self, module):
        assert module.parse_round_count([1, 1]) == 2

    def test_none_and_invalid(self, module):
        assert module.parse_round_count(None) is None
        assert module.parse_round_count("invalid") is None
        assert module.parse_round_count(2) is None


class TestApplyRoundCountFlags:
    def test_sets_match_mismatch_and_unknown(self, module):
        gauge_result = {
            "matches": {
                "vid_20": {"rounds": [{}, {}]},
                "vid_100": {"rounds": [{}]},
                "vid_200": {"rounds": [{}]},
            }
        }

        module.apply_round_count_flags(gauge_result, {"vid_20": 2, "vid_100": 3})

        assert gauge_result["matches"]["vid_20"]["detectedRoundCount"] == 2
        assert gauge_result["matches"]["vid_20"]["battlelogRoundCount"] == 2
        assert gauge_result["matches"]["vid_20"]["roundCountMatch"] is True

        assert gauge_result["matches"]["vid_100"]["roundCountMatch"] is False

        assert gauge_result["matches"]["vid_200"]["battlelogRoundCount"] is None
        assert gauge_result["matches"]["vid_200"]["roundCountMatch"] is None
