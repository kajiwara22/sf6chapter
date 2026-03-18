"""
Markdown形式のレポートフォーマッタ
"""

from collections import defaultdict
from datetime import datetime

from .query import LPRow, MatchupRow, Summary


def format_report(
    summary: Summary,
    matchups: list[MatchupRow],
    lp_history: list[LPRow],
    *,
    date_from: str,
    date_to: str,
    player_id: str,
    player_name: str = "ゆたにぃPC",
    battle_type: str = "ranked",
) -> str:
    """レポート全体をMarkdown形式で生成"""
    lines: list[str] = []

    lines.append("# SF6 対戦レポート")
    lines.append(f"期間: {date_from} 〜 {date_to}")
    lines.append(f"プレイヤー: {player_name} ({player_id})")
    lines.append(f"バトルタイプ: {battle_type}")
    lines.append(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # サマリー
    lines.append(_format_summary(summary))
    lines.append("")

    # マッチアップ
    lines.append(_format_matchups(matchups))
    lines.append("")

    # LP推移
    lines.append(_format_lp_history(lp_history))

    return "\n".join(lines)


def format_comparison(
    current: Summary,
    previous: Summary,
    current_matchups: list[MatchupRow],
    previous_matchups: list[MatchupRow],
    *,
    current_period: str,
    previous_period: str,
) -> str:
    """前期間比較セクションをMarkdown形式で生成"""
    lines: list[str] = []
    lines.append("## 前期間比較")
    lines.append(f"今期: {current_period} / 前期: {previous_period}")
    lines.append("")

    # 全体比較テーブル
    cur_wr = (current.wins / current.total_matches * 100) if current.total_matches > 0 else 0
    prev_wr = (previous.wins / previous.total_matches * 100) if previous.total_matches > 0 else 0
    wr_diff = cur_wr - prev_wr

    cur_lp_change = (current.last_lp - current.first_lp) if current.first_lp and current.last_lp else 0
    prev_lp_change = (previous.last_lp - previous.first_lp) if previous.first_lp and previous.last_lp else 0

    cur_mr_change = (current.last_mr - current.first_mr) if current.first_mr and current.last_mr else 0
    prev_mr_change = (previous.last_mr - previous.first_mr) if previous.first_mr and previous.last_mr else 0

    lines.append("| 指標 | 前期 | 今期 | 差分 |")
    lines.append("|------|------|------|------|")
    lines.append(
        f"| 総試合数 | {previous.total_matches} | {current.total_matches} "
        f"| {_format_diff(current.total_matches - previous.total_matches)} |"
    )
    lines.append(f"| 勝率 | {prev_wr:.1f}% | {cur_wr:.1f}% | {_format_diff_pt(wr_diff)} |")
    lines.append(
        f"| LP変動 | {_format_signed(prev_lp_change)} | {_format_signed(cur_lp_change)} | {_format_diff(cur_lp_change - prev_lp_change)} |"
    )

    if cur_mr_change != 0 or prev_mr_change != 0:
        lines.append(
            f"| MR変動 | {_format_signed(prev_mr_change)} | {_format_signed(cur_mr_change)} | {_format_diff(cur_mr_change - prev_mr_change)} |"
        )

    lines.append("")

    # キャラ別勝率変化（試合数5以上）
    lines.append("### キャラ別勝率変化（試合数5以上）")
    lines.append("")

    # 現在期間のキャラ別集計
    cur_by_char = _aggregate_by_opponent(current_matchups)
    prev_by_char = _aggregate_by_opponent(previous_matchups)

    all_chars = sorted(set(cur_by_char.keys()) | set(prev_by_char.keys()))
    char_rows = []
    for char in all_chars:
        cur = cur_by_char.get(char, (0, 0))
        prev = prev_by_char.get(char, (0, 0))
        if cur[0] < 5 and prev[0] < 5:
            continue
        cur_rate = (cur[1] / cur[0] * 100) if cur[0] > 0 else 0
        prev_rate = (prev[1] / prev[0] * 100) if prev[0] > 0 else 0
        diff = cur_rate - prev_rate
        char_rows.append((char, prev_rate, prev[0], cur_rate, cur[0], diff))

    # 変化量の絶対値で降順ソート
    char_rows.sort(key=lambda x: abs(x[5]), reverse=True)

    if char_rows:
        lines.append("| 対戦キャラ | 前期勝率 (n) | 今期勝率 (n) | 変化 |")
        lines.append("|-----------|-------------|-------------|------|")
        for char, prev_rate, prev_n, cur_rate, cur_n, diff in char_rows:
            warn = " ⚠" if diff < -10 else ""
            lines.append(
                f"| {char} | {prev_rate:.1f}% ({prev_n}) | {cur_rate:.1f}% ({cur_n}) | {_format_diff_pt(diff)}{warn} |"
            )
    else:
        lines.append("比較対象のキャラがありません（試合数5以上の条件を満たすデータなし）")

    return "\n".join(lines)


def _format_summary(summary: Summary) -> str:
    """サマリーセクション"""
    lines = ["## サマリー", ""]
    lines.append(f"- 総試合数: {summary.total_matches}")
    lines.append(f"- 勝利: {summary.wins} / 敗北: {summary.losses}")

    if summary.total_matches > 0:
        wr = summary.wins / summary.total_matches * 100
        lines.append(f"- 総合勝率: {wr:.1f}%")

    if summary.first_lp is not None and summary.last_lp is not None:
        lp_diff = summary.last_lp - summary.first_lp
        lines.append(f"- LP変動: {summary.first_lp:,} → {summary.last_lp:,} ({_format_signed(lp_diff)})")

    if summary.first_mr is not None and summary.last_mr is not None:
        mr_first = summary.first_mr
        mr_last = summary.last_mr
        if mr_first > 0 or mr_last > 0:
            mr_diff = mr_last - mr_first
            lines.append(f"- MR変動: {mr_first:,} → {mr_last:,} ({_format_signed(mr_diff)})")

    return "\n".join(lines)


def _format_matchups(matchups: list[MatchupRow]) -> str:
    """マッチアップ結果セクション"""
    lines = ["## マッチアップ結果", ""]

    if not matchups:
        lines.append("データなし")
        return "\n".join(lines)

    # 使用キャラ別にグループ化
    by_my_char: dict[str, list[MatchupRow]] = defaultdict(list)
    for row in matchups:
        by_my_char[row.my_character].append(row)

    for my_char, rows in by_my_char.items():
        lines.append(f"### 使用キャラ: {my_char}")
        lines.append("")

        # 対戦キャラ別に集約（入力タイプ別の内訳付き）
        opponent_data: dict[str, dict] = defaultdict(lambda: {"total": 0, "wins": 0, "by_input": {}})
        for row in rows:
            d = opponent_data[row.opponent_character]
            d["total"] += row.total
            d["wins"] += row.wins
            d["by_input"][row.opponent_input_type] = (row.wins, row.total)

        # 試合数降順でソート
        sorted_opponents = sorted(opponent_data.items(), key=lambda x: x[1]["total"], reverse=True)

        # 存在する入力タイプを収集
        all_input_types = set()
        for _, d in sorted_opponents:
            all_input_types.update(d["by_input"].keys())
        input_type_cols = sorted(all_input_types)

        # ヘッダー
        input_headers = " | ".join(f"{it}勝率" for it in input_type_cols)
        header = f"| 対戦キャラ | 試合数 | 勝利 | 敗北 | 勝率 | {input_headers} |"
        separator = "|" + "|".join(["---"] * (5 + len(input_type_cols))) + "|"
        lines.append(header)
        lines.append(separator)

        total_all = 0
        wins_all = 0
        for opp_char, d in sorted_opponents:
            total = d["total"]
            wins = d["wins"]
            losses = total - wins
            wr = wins / total * 100 if total > 0 else 0
            total_all += total
            wins_all += wins

            input_cols = []
            for it in input_type_cols:
                if it in d["by_input"]:
                    iw, it_total = d["by_input"][it]
                    ir = iw / it_total * 100 if it_total > 0 else 0
                    input_cols.append(f"{ir:.1f}% ({iw}/{it_total})")
                else:
                    input_cols.append("-")

            input_str = " | ".join(input_cols)
            lines.append(f"| {opp_char} | {total} | {wins} | {losses} | {wr:.1f}% | {input_str} |")

        # 合計行
        total_wr = wins_all / total_all * 100 if total_all > 0 else 0
        empty_cols = " | ".join([""] * len(input_type_cols))
        lines.append(
            f"| **合計** | **{total_all}** | **{wins_all}** | **{total_all - wins_all}** | **{total_wr:.1f}%** | {empty_cols} |"
        )
        lines.append("")

    return "\n".join(lines)


def _format_lp_history(lp_history: list[LPRow]) -> str:
    """LP推移セクション"""
    lines = ["## LP推移", ""]

    if not lp_history:
        lines.append("データなし")
        return "\n".join(lines)

    lines.append("| # | 日時 | 対戦キャラ | 結果 | LP | LP変動 | MR | MR変動 |")
    lines.append("|---|------|-----------|------|-----|--------|-----|--------|")

    prev_lp = None
    prev_mr = None
    for i, row in enumerate(lp_history, 1):
        dt_str = (
            row.uploaded_at.strftime("%m-%d %H:%M")
            if isinstance(row.uploaded_at, datetime)
            else str(row.uploaded_at)[:16]
        )

        lp_diff = ""
        if prev_lp is not None and row.lp is not None:
            diff = row.lp - prev_lp
            lp_diff = _format_signed(diff)

        mr_str = "-"
        mr_diff = ""
        if row.master_rating and row.master_rating > 0:
            mr_str = f"{row.master_rating:,}"
            if prev_mr is not None and prev_mr > 0:
                diff = row.master_rating - prev_mr
                mr_diff = _format_signed(diff)

        lp_str = f"{row.lp:,}" if row.lp else "-"
        lines.append(
            f"| {i} | {dt_str} | {row.opponent_character} | {row.result} | {lp_str} | {lp_diff} | {mr_str} | {mr_diff} |"
        )

        prev_lp = row.lp
        prev_mr = row.master_rating if row.master_rating and row.master_rating > 0 else prev_mr

    return "\n".join(lines)


def _aggregate_by_opponent(matchups: list[MatchupRow]) -> dict[str, tuple[int, int]]:
    """対戦キャラ別に集約: {char: (total, wins)}"""
    result: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in matchups:
        result[row.opponent_character][0] += row.total
        result[row.opponent_character][1] += row.wins
    return {k: (v[0], v[1]) for k, v in result.items()}


def _format_signed(value: int) -> str:
    """符号付き数値フォーマット"""
    if value > 0:
        return f"+{value:,}"
    return f"{value:,}"


def _format_diff(value: int) -> str:
    """差分フォーマット"""
    return _format_signed(value)


def _format_diff_pt(value: float) -> str:
    """ポイント差分フォーマット"""
    if value > 0:
        return f"+{value:.1f}pt"
    return f"{value:.1f}pt"
