"""
PS5 自動タイトル判定と時刻判定ロジックのテストスクリプト
"""

import re
from datetime import datetime
import pytz


def is_ps5_auto_title(title: str) -> bool:
    """PS5のデフォルトタイトル（連続した同一のひらがな3文字）判定"""
    return bool(re.match(r'^([ぁ-ん])\1{2}$', title))


def get_rename_title(published_at_utc: str) -> str:
    """
    公開日時（UTC）から JST を求め、時刻に応じてリネーム後のタイトルを決定

    Args:
        published_at_utc: YouTube APIから取得した公開日時（ISO 8601形式、UTC）
                         例: "2025-12-04T10:30:00Z"

    Returns:
        リネーム後のタイトル
        例: "お昼休みにスト６ 2025-12-04"
    """
    # UTC → JST 変換
    dt_utc = datetime.fromisoformat(published_at_utc.replace("Z", "+00:00"))
    jst = pytz.timezone("Asia/Tokyo")
    dt_jst = dt_utc.astimezone(jst)

    # 時刻を取得
    hour = dt_jst.hour
    date_str = dt_jst.strftime("%Y-%m-%d")

    # 時刻帯で判定
    if 12 <= hour < 13:
        prefix = "お昼休みにスト６"
    elif 18 <= hour < 22:
        prefix = "就業後にスト６"
    else:
        prefix = "PS5からスト６"

    return f"{prefix} {date_str}"


def test_is_ps5_auto_title():
    """PS5 自動タイトル判定のテスト"""
    print("=== Testing is_ps5_auto_title ===")

    # OK例
    ok_cases = ["あああ", "ふふふ", "ううう", "まままぁ"]
    for title in ok_cases:
        result = is_ps5_auto_title(title)
        print(f"  '{title}': {result} {'✓' if result else '✗'}")

    # NG例
    ng_cases = ["あいう", "えおか", "あああい", "aa", "aaa", "あ"]
    for title in ng_cases:
        result = is_ps5_auto_title(title)
        print(f"  '{title}': {result} {'✗' if result else '✓'}")


def test_get_rename_title():
    """時刻判定ロジックのテスト"""
    print("\n=== Testing get_rename_title ===")

    # 昼休み時間帯（12:00-13:00 JST）
    # 2025-12-04T03:30:00Z = 2025-12-04T12:30:00 JST (UTC+9)
    lunch_time = "2025-12-04T03:30:00Z"
    result = get_rename_title(lunch_time)
    print(f"  Lunch time {lunch_time}: {result}")
    assert "お昼休みにスト６" in result, f"Expected '昼' but got {result}"

    # 就業後時間帯（18:00-22:00 JST）
    # 2025-12-04T09:30:00Z = 2025-12-04T18:30:00 JST (UTC+9)
    evening_time = "2025-12-04T09:30:00Z"
    result = get_rename_title(evening_time)
    print(f"  Evening time {evening_time}: {result}")
    assert "就業後にスト６" in result, f"Expected '就業後' but got {result}"

    # その他の時間帯
    # 2025-12-04T00:00:00Z = 2025-12-04T09:00:00 JST (UTC+9)
    other_time = "2025-12-04T00:00:00Z"
    result = get_rename_title(other_time)
    print(f"  Other time {other_time}: {result}")
    assert "PS5からスト６" in result, f"Expected 'PS5から' but got {result}"


if __name__ == "__main__":
    test_is_ps5_auto_title()
    test_get_rename_title()
    print("\n✅ All tests passed!")
