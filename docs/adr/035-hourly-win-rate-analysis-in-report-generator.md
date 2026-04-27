# ADR-035: レポートジェネレーターへの時間帯別勝率分析の追加

## ステータス

採用 - 2026-04-21

## 文脈

### 現状

`packages/report-generator/` は `--from` / `--to` で指定した期間のマッチアップ結果・LP推移をMarkdown形式で出力し、LLMへの分析連携に活用している（ADR-032）。

現状のレポートでは「誰と戦って何勝何敗か」は分かるが、**試合した時間帯によって勝率に差があるか**は把握できない。以下のような仮説を検証・分析する手段がない：

- 深夜帯は疲労で判断力が落ちて勝率が下がるのではないか
- 夕方の特定の時間帯にランクマッチの対戦相手の強さが変わるのではないか

### 要件

1. 1時間単位（0時台、1時台、…、23時台）で勝率を集計し、Markdownテーブルとして出力する
2. `uploaded_at` はDuckDB上ではUTC格納のため、出力時にJST（UTC+9）へ変換する
3. 既存セクション（マッチアップ・LP推移）とは独立したセクションとして追加する
4. `--hourly-analysis` フラグで有効化する（デフォルトはオフ）
5. 既存の `--from` / `--to` / `--battle-type` / `--player-id` と組み合わせて動作する

### 利用シナリオ

```bash
# 時間帯別分析を含むレポートを生成
uv run python src/main.py --from 2026-04-01 --to 2026-05-01 --hourly-analysis

# 既存フラグとの組み合わせ
uv run python src/main.py --from 2026-04-01 --to 2026-05-01 --hourly-analysis --compare-prev
```

生成されるセクションのイメージ：

```markdown
## 時間帯別勝率（JST）

| 時間帯 | 試合数 | 勝利 | 敗北 | 勝率 |
|--------|--------|------|------|------|
| 0時台  | 12     | 7    | 5    | 58.3% |
| 1時台  | 8      | 3    | 5    | 37.5% |
| ...    |        |      |      |       |
| 22時台 | 25     | 15   | 10   | 60.0% |
| 23時台 | 18     | 9    | 9    | 50.0% |
| **合計** | **150** | **85** | **65** | **56.7%** |
```

## 選択肢

### 選択肢A: `--hourly-analysis` フラグで有効化（デフォルトオフ）

`main.py` に `--hourly-analysis` フラグを追加し、指定時のみ時間帯別集計クエリを実行してセクションを追加する。

**変更ファイル**:
- `src/query.py` — `query_hourly_win_rate()` 関数を追加
- `src/formatter.py` — `_format_hourly_win_rate()` 関数を追加
- `src/main.py` — `--hourly-analysis` 引数追加、`format_report()` への受け渡し

### 選択肢B: 常時出力（フラグなし）

時間帯別勝率を常にレポートに含める。

### 選択肢C: 専用サブコマンドとして分離

`main.py` に `--mode hourly` などのサブコマンドを追加し、時間帯分析専用のレポートとして出力する。

## 各選択肢の比較表

| 観点 | A: フラグで有効化 | B: 常時出力 | C: サブコマンド |
|------|-----------------|------------|----------------|
| YAGNI | ◎ 必要な時だけ生成 | △ 不要な場合も出力 | △ 過剰な設計 |
| LLMへの入力効率 | ◎ 必要なセクションのみ | △ 常にトークンを消費 | ○ 分離できる |
| 実装コスト | ◎ 最小限 | ◎ 最小限 | △ 引数設計が増える |
| 既存CLIとの一貫性 | ◎ `--compare-prev` と同じパターン | △ オプトアウトが必要になる | △ 他の引数と体系が異なる |
| 将来の拡張性 | ○ 他の分析フラグと並立しやすい | △ 全部出すと肥大化する | ○ モード分離で整理できる |

## 結論

**選択肢A: `--hourly-analysis` フラグで有効化** を採用。

## 結論を導いた重要な観点

1. **既存CLIとの一貫性**: `--compare-prev` フラグと同じオプトイン方式であり、使い方の一貫性を維持できる
2. **LLMへの入力効率**: 時間帯分析が不要な月次レポートではトークンを増やさずに済む
3. **YAGNI**: 将来的に曜日別・週別などの分析を追加する場合も同じパターンで並立できる

## 詳細設計

### クエリ（`query.py`）

```python
@dataclass
class HourlyRow:
    hour: int        # 0〜23（JST）
    total: int
    wins: int
    losses: int

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total * 100) if self.total > 0 else 0.0


def query_hourly_win_rate(
    con: duckdb.DuckDBPyConnection,
    player_id: str,
    date_from: str,
    date_to: str,
    battle_type: str = "ranked",
) -> list[HourlyRow]:
    bt_filter = _battle_type_filter(battle_type)
    pid = int(player_id)

    rows = con.execute(
        f"""
        SELECT
            (DATE_PART('hour', uploaded_at) + 9) % 24 AS hour_jst,
            COUNT(*) AS total,
            SUM(CASE
                WHEN (p1_short_id = ? AND match_result = 'win')
                  OR (p2_short_id = ? AND match_result = 'loss')
                THEN 1 ELSE 0 END) AS wins
        FROM battlelog_replays
        WHERE (p1_short_id = ? OR p2_short_id = ?)
          AND uploaded_at >= ?::TIMESTAMP
          AND uploaded_at < ?::TIMESTAMP
          {bt_filter}
        GROUP BY hour_jst
        ORDER BY hour_jst
        """,
        [pid] * 4 + [date_from, date_to],
    ).fetchall()

    return [
        HourlyRow(hour=r[0], total=r[1], wins=r[2], losses=r[1] - r[2])
        for r in rows
    ]
```

**UTC→JST変換の考え方**: `DATE_PART('hour', uploaded_at)` でUTC時刻の時を取得し、`+9) % 24` でJSTの時刻に変換する。日付をまたぐケース（UTC 15時以降 → JST翌日0時以降）も `% 24` で正しく処理される。

### フォーマッタ（`formatter.py`）

```python
def _format_hourly_win_rate(hourly: list[HourlyRow]) -> str:
    lines = ["## 時間帯別勝率（JST）", ""]

    if not hourly:
        lines.append("データなし")
        return "\n".join(lines)

    lines.append("| 時間帯 | 試合数 | 勝利 | 敗北 | 勝率 |")
    lines.append("|--------|--------|------|------|------|")

    total_all, wins_all = 0, 0
    for row in hourly:
        lines.append(
            f"| {row.hour}時台 | {row.total} | {row.wins} | {row.losses} | {row.win_rate:.1f}% |"
        )
        total_all += row.total
        wins_all += row.wins

    total_wr = wins_all / total_all * 100 if total_all > 0 else 0
    lines.append(
        f"| **合計** | **{total_all}** | **{wins_all}** | **{total_all - wins_all}** | **{total_wr:.1f}%** |"
    )
    return "\n".join(lines)
```

### CLIの変更（`main.py`）

```python
parser.add_argument(
    "--hourly-analysis",
    action="store_true",
    help="時間帯別勝率分析を含める（JST換算、1時間単位）",
)
```

`main()` 内でフラグが立っている場合のみクエリを実行してレポートに追記する。

### 出力の挿入位置

既存のセクション順を維持し、末尾に追加する：

```
## サマリー
## マッチアップ結果
## LP推移
## 時間帯別勝率（JST）   ← 新規追加（--hourly-analysis 時のみ）
## 前期間比較             ← --compare-prev 時のみ（既存）
```

## 帰結

### メリット

- LLMへの入力として「この時間帯は勝率が低い」などの傾向を定量的に渡せる
- 既存のレポート生成フローへの影響がほぼゼロ（フラグなし時は変化なし）
- 実装コストが小さい（クエリ1本 + フォーマッタ関数1本 + フラグ追加のみ）

### 制約・注意点

- `uploaded_at` はBattlelogリプレイのアップロード日時であり、実際の試合終了時刻とは数分〜数十分のずれがある。1時間単位の分析では許容範囲とする
- 試合数が少ない時間帯（例：早朝）は勝率のブレが大きいため、LLMへの分析指示時にサンプル数を考慮するよう促すことを推奨する

### 将来の拡張可能性

- 曜日別勝率（`--day-of-week-analysis`）も同じパターンで追加可能
- 時間帯 × キャラ別のクロス集計（`--hourly-matchup`）への発展も、同じ `HourlyRow` の構造を拡張すれば対応可能

## 実装チェックリスト

- [ ] `src/query.py` に `HourlyRow` データクラスと `query_hourly_win_rate()` を追加
- [ ] `src/formatter.py` に `_format_hourly_win_rate()` を追加し、`format_report()` の引数に `hourly` を追加
- [ ] `src/main.py` に `--hourly-analysis` フラグを追加し、フラグ有効時にクエリ実行・レポート追記
- [ ] ローカルParquetファイルを使った動作確認（`--local` + `--hourly-analysis`）
