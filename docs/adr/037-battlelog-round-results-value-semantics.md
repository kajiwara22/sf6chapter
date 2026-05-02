# ADR-037: Battlelog round_results の値の意味と match_result 判定ロジックの修正

## ステータス

提案 - 2026-05-02

## 文脈

### 発見した不具合

対戦履歴ページと対戦検索ページで同一の対戦について結果が異なるケースが発覚した。

**具体例（replay_id: XVPRSQYKF、2026-05-02 01:00:01 JST）**

| 項目 | 対戦履歴ページ | 対戦検索ページ |
|------|--------------|--------------|
| データソース | `battlelog_replays.parquet` | `matches.parquet` |
| 表示結果 | Draw | Win（C.ヴァイパー勝利） |

実際の対戦結果は C.ヴァイパーの2-1勝利であり、対戦検索側（RESULT 画面テンプレートマッチング）が正しい。

### round_results の値の意味

Battlelog API が返す `round_results` の各要素は、ラウンドの勝利方法を表すIDである（体力残量ではない）。

| 値 | 略称 | 勝敗 | 意味 |
|----|------|------|------|
| 0 | L  | LOSS | 負け |
| 1 | V  | WIN  | 通常勝利（Vanilla KO） |
| 2 | C  | WIN  | Chip KO |
| 3 | T  | WIN  | Time Up |
| 4 | D  | DRAW | 引き分け |
| 5 | OD | WIN  | Overdrive KO |
| 6 | SA | WIN  | Super Art KO |
| 7 | CA | WIN  | Critical Art KO |
| 8 | P  | WIN  | Perfect |

### 誤判定の発生メカニズム

`scripts/convert_battlelog_to_parquet.py` の `determine_match_result()` は、`round_results` の値を**単純合計**してP1/P2の大小を比較していた。

```python
# 誤った実装
def determine_match_result(p1_round_results, p2_round_results):
    p1_wins = sum(p1_round_results)  # 値の意味を無視して合計
    p2_wins = sum(p2_round_results)
    ...
```

上記の具体例でこのロジックを適用すると：

```
P1 (C.ヴァイパー): round_results = [1, 0, 1]
  → R1: 1 (WIN), R2: 0 (LOSS), R3: 1 (WIN) → 2勝1敗
  → 合計: 1 + 0 + 1 = 2

P2 (JP): round_results = [0, 2, 0]
  → R1: 0 (LOSS), R2: 2 (WIN / Chip KO), R3: 0 (LOSS) → 1勝2敗
  → 合計: 0 + 2 + 0 = 2

2 == 2 → "draw" と誤判定 ❌
```

P1が2ラウンド勝利しているにもかかわらず、Chip KO の値（2）が通常勝利（1）より大きいため、
合計値が偶然一致し "draw" と判定されてしまう。

### 正しい判定ロジック

各ラウンドで `value > 0` なら「そのラウンドを勝利した」として勝利ラウンド数を集計する。

```python
# 正しい実装
def determine_match_result(p1_round_results, p2_round_results):
    p1_wins = sum(1 for v in p1_round_results if v > 0)
    p2_wins = sum(1 for v in p2_round_results if v > 0)

    if p1_wins > p2_wins:
        return "win"
    elif p1_wins < p2_wins:
        return "loss"
    else:
        return "draw"
```

上記の具体例に適用すると：

```
P1: [1>0, 0>0, 1>0] → 2勝
P2: [0>0, 2>0, 0>0] → 1勝
2 > 1 → "win" ✅
```

真の引き分け（値が 4: DRAW）も正しく扱われる。R1の結果が `[4]` vs `[4]` であれば両者ともに1勝扱いとなり "draw" となるが、SF6 ではラウンドが同時終了した場合に 4 がセットされると考えられる。

## 決定

`scripts/convert_battlelog_to_parquet.py` の `determine_match_result()` を、`round_results` の値を勝敗IDとして正しく解釈するよう修正する。

具体的には、各ラウンドの値が `0`（LOSS）かどうかを判定基準とし、`0 より大きい = 勝利ラウンド` として勝利ラウンド数を集計する。

## 選択肢の比較

### 選択肢A: `v > 0` で勝利ラウンドをカウント（採用）

```python
p1_wins = sum(1 for v in p1_round_results if v > 0)
```

| 観点 | 評価 |
|------|------|
| 正確性 | ◎ 値の意味に忠実 |
| 実装コスト | ◎ 1行の変更 |
| 将来の値追加への耐性 | ◎ 新しいWIN種別が追加されても 0 以外であれば正しく扱われる |

### 選択肢B: WIN に該当する値のセット（`{1,2,3,5,6,7,8}`）で判定

```python
WIN_VALUES = {1, 2, 3, 5, 6, 7, 8}
p1_wins = sum(1 for v in p1_round_results if v in WIN_VALUES)
```

| 観点 | 評価 |
|------|------|
| 正確性 | ◎ 明示的で意図が明確 |
| 実装コスト | ○ 定数定義が必要 |
| 将来の値追加への耐性 | △ 新しいWIN種別が追加された場合にセットの更新が必要 |

### 結論

選択肢A を採用。値 `0` が LOSS を表すという単純な規則に基づき、`v > 0` で勝利ラウンドを判定する。Battlelog API の仕様上、0 が唯一の「負け」を表す値であることが確認されており、新しい勝利種別が追加されても自動的に対応できる。

## トレードオフと帰結

### メリット

- `battlelog_replays.parquet` の `match_result` が正確な値になる
- 対戦履歴ページと対戦検索ページの結果不一致が解消される

### 対応が必要な作業

修正後は既存の Parquet を再生成する必要がある。誤判定が "draw" として記録されているレコードは、再変換によって "win" または "loss" に修正される。

- [ ] `scripts/convert_battlelog_to_parquet.py` の `determine_match_result()` を修正
- [ ] `battlelog_replays.parquet` を再生成して R2 にアップロード
- [ ] 修正後の replay_id `XVPRSQYKF` が "win" になることを確認

### 将来の見直し条件

- Battlelog API が `round_results` に新たな値（負け種別など、`0` 以外で LOSS を表す値）を追加した場合は本判定ロジックの見直しが必要

## 関連 ADR

- [ADR-023: Battlelog データ統合と Parquet Web 検索機能の実装](023-battlelog-data-integration-with-parquet-search.md)
- [ADR-026: 対戦動画からの勝敗検出（RESULT 画面テンプレートマッチング）](026-result-screen-match-outcome-detection.md)
- [ADR-034: 対戦結果一覧ページの実装](034-match-history-page-with-youtube-links.md)
