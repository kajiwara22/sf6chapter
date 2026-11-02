"""バックラー（Buckler's Boot Camp）公開統計 API クライアント

ADR-072: 公開統計を R2 の Parquet に一元化するため、月次で取得する。
API は月1回（第二木曜に先月分）しか更新されないため、呼び出し頻度は低い。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any

BASE_URL = "https://www.streetfighter.com/6/buckler/api"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

# 使用率のみロケール依存。dia は日本語固定で取得する（ADR-072 決定事項 2）
SUPPORTED_USAGE_LOCALES = ("ja-jp", "en")
DIA_LOCALE = "ja-jp"

LEAGUE_NAMES: dict[int, str] = {
    1: "ROOKIE",
    2: "IRON",
    3: "BRONZE",
    4: "SILVER",
    5: "GOLD",
    6: "PLATINUM",
    7: "DIAMOND",
    8: "MASTER",
}

# 最古の公開データ（2023年6月）
OLDEST_YEAR = 2023
OLDEST_MONTH = 6


class BucklerAPIError(RuntimeError):
    """バックラー API の取得に失敗した"""


def format_data_month(year: int, month: int) -> str:
    """(2025, 8) -> "202508\""""
    if not 1 <= month <= 12:
        raise ValueError(f"month は 1〜12 で指定してください: {month}")
    return f"{year}{month:02d}"


def parse_data_month(data_month: str) -> tuple[int, int]:
    """ "202508" -> (2025, 8)"""
    if len(data_month) != 6 or not data_month.isdigit():
        raise ValueError(f"data_month は YYYYMM 形式で指定してください: {data_month}")
    year, month = int(data_month[:4]), int(data_month[4:])
    if not 1 <= month <= 12:
        raise ValueError(f"data_month の月が不正です: {data_month}")
    return year, month


def latest_available_month(today: date | None = None) -> tuple[int, int]:
    """取得可能な最新のデータ年月を返す

    バックラーは毎月第二木曜日に先月分を公開する。第二木曜より前は先々月、
    以降は先月が最新となる。
    """
    today = today or date.today()
    first_day = today.replace(day=1)

    # date.weekday(): 月曜=0, 木曜=3
    days_until_thursday = (3 - first_day.weekday()) % 7
    second_thursday = first_day + timedelta(days=days_until_thursday + 7)

    months_back = 2 if today < second_thursday else 1

    year, month = today.year, today.month - months_back
    while month <= 0:
        month += 12
        year -= 1

    if (year, month) < (OLDEST_YEAR, OLDEST_MONTH):
        raise ValueError(f"バックラーの最古の公開データは {OLDEST_YEAR}-{OLDEST_MONTH:02d} です")
    return year, month


def _get_json(url: str, timeout: float = 60.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.build_opener().open(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as e:
        raise BucklerAPIError(f"バックラー API が HTTP {e.code} を返しました: {url}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise BucklerAPIError(f"バックラー API に接続できません: {url} ({e})") from e

    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise BucklerAPIError(f"バックラー API のレスポンスが JSON ではありません: {url}") from e


def fetch_usage_rates(data_month: str, locale: str = "ja-jp") -> dict[str, Any]:
    """キャラクター使用率を取得する

    Args:
        data_month: "YYYYMM"
        locale: "ja-jp" / "en"
    """
    if locale not in SUPPORTED_USAGE_LOCALES:
        raise ValueError(f"未対応のロケールです: {locale}（対応: {', '.join(SUPPORTED_USAGE_LOCALES)}）")
    parse_data_month(data_month)
    return _get_json(f"{BASE_URL}/{locale}/stats/usagerate/{data_month}")


def fetch_matchup_diagram(data_month: str) -> dict[str, Any]:
    """キャラクター別マッチアップ（相性ダイアグラム）を取得する

    dia はロケール非依存のため ja-jp 固定で取得する。
    """
    parse_data_month(data_month)
    return _get_json(f"{BASE_URL}/{DIA_LOCALE}/stats/dia/{data_month}")
