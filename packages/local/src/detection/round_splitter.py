"""ラウンド境界の分割ロジック（ADR-048）

動画から検出した ROUND バナーの時刻と、既存パイプラインが検出した試合開始時刻から、
試合内のラウンド境界を組み立てる。

- ラウンド開始 = ROUND バナー検出時刻
- ラウンド終端（boundary_time）= 次のラウンドのバナー時刻、最終ラウンドは試合終端
  （ゲージ変化点をどのラウンドに割り当てるかの上限として使う）
- HUD が表示されていた範囲の切り出しは GaugeAnalyzer 側で行う

`end_time` は「HUD が見えていた最後の時刻」ではなく境界時刻であることに注意。
ゲージの変化点をラウンドに割り当てるための境界として使う。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..utils.logger import get_logger

logger = get_logger()

# 同一ラウンド開始とみなすバナー検出のまとめ幅（秒）
BANNER_MERGE_WINDOW_SEC = 3.0

# 試合開始より前のバナーを第1ラウンドとして採用する許容幅（秒）
MATCH_START_LEAD_SEC = 3.0

# バナー未検出時に試合開始時刻を第1ラウンド開始として採用する閾値（秒）
FIRST_ROUND_FALLBACK_SEC = 5.0

# 試合終端の手前この秒数以内のバナーは「次試合の ROUND 1」とみなし、現在の試合には含めない
# （次試合のバナーは、次試合の検出時刻よりわずかに手前に現れる）
TRAILING_BANNER_MARGIN_SEC = 3.0

# ラウンド数の上限（SF6は最大3ラウンド）
MAX_ROUNDS = 3


@dataclass
class RoundWindow:
    """1ラウンドぶんの境界情報"""

    index: int  # 1始まり
    start_time: float  # ROUND バナー時刻（秒）
    end_time: float  # 次ラウンド開始 or 試合終端（秒）
    boundary_time: float | None  # サンプルを割り当てる上限（次ラウンド開始 or 試合終端）
    end_reason: str  # "next_round" | "match_end" | "video_end"
    banner_detected: bool = True


def merge_banner_times(times: list[float], window_sec: float = BANNER_MERGE_WINDOW_SEC) -> list[float]:
    """同一バナーの多重検出をまとめる（先頭の時刻を採用）"""
    merged: list[float] = []
    for time in sorted(times):
        if merged and time - merged[-1] < window_sec:
            continue
        merged.append(time)
    return merged


def split_rounds(
    match_start: float,
    match_end: float,
    round_banner_times: list[float],
) -> list[RoundWindow]:
    """試合をラウンド単位に分割する

    Args:
        match_start: 試合の開始時刻（既存パイプラインの検出時刻）
        match_end: 試合の終端（次試合の開始時刻 or 動画終端）
        round_banner_times: 動画全体で検出した ROUND バナー時刻

    Returns:
        RoundWindow のリスト（ラウンド番号順）
    """
    if match_end <= match_start:
        match_end = match_start

    banners = merge_banner_times(round_banner_times)

    # 試合範囲内のバナー（第1ラウンドは試合開始直前に出るため少し手前まで許容）
    # 末尾付近のバナーは次試合の ROUND 1 なので除外する
    tail_limit = match_end - TRAILING_BANNER_MARGIN_SEC
    in_match = [t for t in banners if match_start - MATCH_START_LEAD_SEC <= t < tail_limit]

    if not in_match:
        # バナー未検出: 試合開始時刻を第1ラウンド開始として扱う
        logger.warning(
            "ROUND banner not found for match at %.2fs; falling back to match start as round 1",
            match_start,
        )
        return [
            RoundWindow(
                index=1,
                start_time=match_start,
                end_time=match_end,
                boundary_time=match_end,
                end_reason="match_end",
                banner_detected=False,
            )
        ]

    first = in_match[0]
    synthetic_leader = False
    if first - match_start > FIRST_ROUND_FALLBACK_SEC:
        logger.warning(
            "First ROUND banner (%.2fs) is %.2fs after match start (%.2fs); using match start as round 1",
            first,
            first - match_start,
            match_start,
        )
        in_match = [match_start, *in_match]
        synthetic_leader = True

    windows: list[RoundWindow] = []
    for i, start_time in enumerate(in_match):
        is_last = i + 1 >= len(in_match)
        if is_last:
            end_time = match_end
            boundary_time = match_end
            end_reason = "match_end"
        else:
            end_time = in_match[i + 1]
            boundary_time = in_match[i + 1]
            end_reason = "next_round"
        windows.append(
            RoundWindow(
                index=i + 1,
                start_time=start_time,
                end_time=end_time,
                boundary_time=boundary_time,
                end_reason=end_reason,
                # 先頭に試合開始時刻を代用した場合はバナー検出ではない
                banner_detected=not (synthetic_leader and i == 0),
            )
        )

    if len(windows) > MAX_ROUNDS:
        logger.warning("Detected %d rounds for match at %.2fs (max %d)", len(windows), match_start, MAX_ROUNDS)
        windows = windows[:MAX_ROUNDS]

    return windows
