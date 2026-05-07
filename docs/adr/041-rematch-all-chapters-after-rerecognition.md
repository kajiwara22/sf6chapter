# ADR-041: 再認識後のBattlelogマッチング全体再実行

## ステータス

提案（Proposed） - 2026-05-07

## 文脈

### 問題の概要

ADR-033で実装した「Battlelog未マッチ時の画像前処理+再認識」において、再認識が成功した場合でも正しいreplay_idにマッチングされない問題が確認された。

### 具体的な事例

**Video ID `BW1dz5S_J6g`** での発生ログ:

```
# 初回マッチング
  ✗ 1131s: JAMIE VS JP - マッチなし         ← JAMIEは誤認識（正しくはMAI）
  ✓ 1298s: MAI VS JP - replay_id=4EAJY346R, mai(win) vs jp(loss), confidence=high, time_diff=4.0s

# 再認識フェーズ（ADR-033）
  再認識 1131s: JAMIE VS JP → MAI VS JP      ← 正しく再認識
  ✓ 1131s: MAI VS JP - replay_id=XU64G8Q5S, mai(win) vs jp(loss), confidence=medium, time_diff=337.0s
  再マッチ成功 1131s: MAI VS JP (replay_id=XU64G8Q5S)

# 期待される正しい結果（--from-intermediate で確認）
  ✓ 1131s: MAI VS JP - replay_id=4EAJY346R, mai(win) vs jp(loss), confidence=high, time_diff=171.0s
  ✓ 1298s: MAI VS JP - replay_id=XU64G8Q5S, mai(win) vs jp(loss), confidence=high, time_diff=170.0s
```

### 根本原因の分析

問題は初回マッチングの処理順序から生じる。

```
初回マッチング（startTime昇順に処理）:
  Step1: 1131s JAMIE VS JP → キャラクター不一致でマッチなし
                               ↑ 誤認識のためMAI VS JPのreplayがスキップされる
  Step2: 1298s MAI VS JP  → replay_id=4EAJY346R にマッチ（time_diff=4s）
                               ↑ 本来は1131sに対応するreplayを獲得してしまう

再認識フェーズ:
  1131s が MAI VS JP に再認識されたとき:
    - 4EAJY346R はすでに used_replay_ids に登録済み → スキップされる
    - 次候補の XU64G8Q5S にマッチ（time_diff=337s, confidence=medium）
      ↑ 本来は1298sに対応するreplayが割り当てられてしまう
```

つまり、**初回マッチングが誤認識という誤った前提で確定させた割り当てが、再認識後も固定されたまま残る**ことが問題である。

### 現状の処理フロー

```
検出 → 認識 → Battlelogマッチング（初回）
                        │
                        ▼
               未マッチ有り → 再認識（ADR-033）
                        │
                        ▼
               再認識成功 → 未マッチチャプターのみ再マッチ ← 問題箇所
```

## 決定

再認識でタイトルが変更されたチャプターが1件以上存在する場合、**全チャプターを対象にBattlelogマッチングを最初からやり直す**。

### 処理フロー

```
[既存フロー]
検出 → 認識 → Battlelogマッチング（初回）
                        │
                   未マッチ有り？
                   │         │
                  Yes        No → 完了
                   │
                   ▼
               再認識（ADR-033）
                        │
               タイトル変更あり？
               │             │
              Yes             No → 完了（個別再マッチのまま）
               │
               ▼
    [新規] Battlelogマッチング全体再実行
    ・used_replay_ids をリセット
    ・再認識済みタイトルを含む全チャプターで照合
               │
               ▼
             完了
```

### 実装方針

`_rerecognize_unmatched_chapters` 内で、タイトルが変更されたチャプターを追跡し、1件以上あった場合に `_match_chapters_with_battlelog_replays` を全チャプターに対して再実行する。

```python
def _rerecognize_unmatched_chapters(self, chapters_with_result, replays, video_published_at, video_id):
    # ...既存の再認識ロジック（個別再マッチは廃止）...

    # タイトルが変更されたチャプターのインデックスを追跡
    updated_titles = {}  # index -> new_title

    for i, chapter in enumerate(chapters_with_result):
        if chapter.get("matched"):
            continue
        # ...再認識...
        if new_title != title:
            updated_titles[i] = new_title

    # タイトル変更なし → そのまま返す
    if not updated_titles:
        return chapters_with_result

    # タイトル変更あり → 全チャプターで再マッチング
    logger.info("  %d件のタイトル変更 → Battlelogマッチング全体を再実行", len(updated_titles))

    # 再認識済みタイトルを反映したチャプターリストを構築（Battlelog結果フィールドをリセット）
    base_chapters = []
    for i, chapter in enumerate(chapters_with_result):
        base = {
            "startTime": chapter["startTime"],
            "title": updated_titles.get(i, chapter["title"]),
            "matchId": chapter.get("matchId"),
            "winner_side": chapter.get("winner_side"),
        }
        if i in updated_titles:
            base["rerecognized"] = True
            base["original_title"] = chapter["title"]
            base["rerecognition_method"] = rerecognition_method
        base_chapters.append(base)

    return self._match_chapters_with_battlelog_replays(base_chapters, replays, video_published_at)
```

### 重要な設計上の判断

**個別再マッチ（現行）を廃止し、全体再実行に一本化する**

現行の「未マッチチャプターのみ再マッチ」は、マッチ済みチャプターの割り当てが正しいという前提を置く。しかし誤認識があった場合、マッチ済みの割り当て自体が誤っている可能性があるため、この前提は成立しない。

全体再実行は以下の点で優れている:

- **割り当ての一貫性**: 誤った初回割り当ての影響を完全に排除する
- **実装のシンプルさ**: 複雑な競合解決ロジックが不要
- **コスト**: Battlelogマッチングは純粋な計算処理（API呼び出しなし）のため、再実行のコストは無視できる

## 検討した代替案

### 代替案1: 現行の個別再マッチ（ADR-033の実装）を継続

再認識後、未マッチチャプターのみを対象に再マッチを実行する。

**却下理由**: 本ADRの根本原因の通り、初回マッチング時の誤割り当てが解消されない。今回の事例（`BW1dz5S_J6g`）で実際に誤マッチングが発生した。

### 代替案2: マッチ済みチャプターの競合検出と再割り当て

再認識後、同一キャラクター組み合わせの競合（複数チャプターが同一replay_idを狙う状況）を検出し、時間差が最小のチャプターに優先的に割り当てる。

**却下理由**:

- 競合検出ロジックが複雑になる
- 全体再実行に対してコストメリットがなく、実装コストは高い
- エッジケース（3つ以上の同一対戦組み合わせ等）への対応が困難

### 代替案3: ソート順の変更

初回マッチング時に、startTimeではなくtolerance内の最小time_diffでチャプターをソートして処理する。

**却下理由**:

- 誤認識チャプターのキャラクター名がそもそも誤っているため、ソート順の変更は根本解決にならない
- 誤認識が存在しない正常ケースには影響しないが、誤認識ケースでは同様の問題が発生する

## 成功基準

| 指標 | 変更前 | 目標 |
|------|--------|------|
| 再認識成功 + 正しいreplay_idマッチング率 | 不定（誤割り当てが発生） | 100%（再認識成功 = 正しいマッチング） |
| 既存の正常ケースへの影響 | N/A | 劣化なし |
| 処理時間増加 | N/A | 無視できる（API呼び出しなし）|

## リスクと対策

| リスク | 影響度 | 対策 |
|-------|--------|------|
| 全体再実行でマッチ済みチャプターの割り当てが変わる | 低 | 全体再実行により最適な割り当てになるため、変わった場合は改善 |
| 再認識なしの正常ケースに影響する | なし | タイトル変更が0件の場合は全体再実行をスキップ（既存動作を維持） |

## 実装ファイル

### 変更するファイル

- `packages/local/main.py` - `_rerecognize_unmatched_chapters` メソッドの修正

## 関連ADR

- [ADR-033: Battlelog未マッチ時の画像前処理による再認識](033-rerecognition-with-image-preprocessing.md) - 本ADRが修正対象とする再認識フロー
- [ADR-021: YouTubeチャプターとBattlelogリプレイのマッピング実装](021-battlelog-chapter-mapping-implementation.md) - Battlelogマッチングの基本設計
