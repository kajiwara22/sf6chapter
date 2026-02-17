# ADR-025: Battlelog API 増分取得の最適化

## ステータス

採用（Accepted） - 2026-02-17

## 文脈

Battlelog API から対戦ログを取得する際、現在のADR-022の実装では以下の問題がある：

### 現在の問題

1. **不要なページの全ページ取得**（[main.py:459-465](../../packages/local/main.py#L459-L465)）
   ```python
   for page in range(1, 21):  # 最大20ページを常に全部取得
       page_replays = await collector.get_replay_list(
           player_id=self.sf6_player_id, page=page
       )
       replays.extend(page_replays)
       if len(page_replays) < 10:  # 最後のページ（10件未満でbreak）
           break
   ```
   - 実際のBattlelogは最大でも10ページ程度
   - ページ全体がキャッシュ済みかの判定ができないため、毎回20ページを全部リクエスト

2. **重複排除後の不要なAPI呼び出し**
   - `player_id + uploaded_at` で同じ対戦ログが存在することが判明した段階で、それ以降の取得処理を中止する余地がある
   - 現在は全ページ取得後に重複排除しているため、全APIリクエストが実行される

3. **キャッシング効率の低さ**
   - ページ単位でのキャッシング判定がないため、初回以降も20ページ全部をAPIリクエスト
   - 個別リプレイの重複排除（ADR-022）だけでは不十分

### 実行ログの証拠

```
[4.5/6] Running Battlelog matching...
Fetching battlelog for player 1319673732, page 1
Successfully extracted 10 replays from API
Fetching battlelog for player 1319673732, page 2
Successfully extracted 10 replays from API
...（ページ20まで）
Fetching battlelog for player 1319673732, page 20
Successfully extracted 10 replays from API
Fetched 2200 replays from Battlelog (cached + new)
```

## 問題の分析

| 項目 | 現状 | 期待値 |
|-----|------|--------|
| **初回実行時のAPI呼び出し** | 20回 | 最大10回（実ページ数） |
| **2回目以降のAPI呼び出し** | 20回 | 0～2回（新規ページのみ） |
| **全ページ取得完了の判定** | 10件未満で判定 | 最新キャッシュ以降のページのみ取得 |

## 要件

1. **最新キャッシュベースの増分取得**
   - 最新のキャッシュ済み対戦ログの `uploaded_at` を記録
   - それより新しい対戦ログが見つかるまでページを進める
   - 同じ `uploaded_at` が複数ページにわたって見つかったら、それ以降のページは取得しない（重複の壁）

2. **ページ終端の早期検出**
   - 1ページから取得を開始
   - `len(page_replays) < 10` で終了（ページ不足 = ラストページ）
   - 最新キャッシュの `uploaded_at` と同一の対戦ログが見つかったら取得停止

3. **API呼び出し削減の目標**
   - 初回実行: 最大10回（実ページ数分）
   - 2回目以降: 0～2回（新規ページのみ）

## 決定

### 1. キャッシング戦略の改善

#### 1-1 最新キャッシュの追跡

`BattlelogCacheManager` に新メソッドを追加：

```python
def get_latest_uploaded_at(self, player_id: str) -> Optional[int]:
    """
    特定 player_id のキャッシュ済み対戦ログで最新の uploaded_at を取得

    Returns:
        最新の uploaded_at（キャッシュなしの場合は None）
    """
    conn = sqlite3.connect(str(self.db_path))
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT MAX(CAST(uploaded_at AS INTEGER))
            FROM replay_cache
            WHERE player_id = ?
            """,
            (player_id,),
        )
        result = cursor.fetchone()[0]
        return result  # None or int
    finally:
        conn.close()
```

#### 1-2 ページ終端検出の強化

```python
def has_reached_cache_boundary(
    self,
    player_id: str,
    current_page_replays: list[dict[str, Any]],
) -> bool:
    """
    現在のページが最新キャッシュに到達したかを判定

    Args:
        player_id: プレイヤーID
        current_page_replays: 現在のページから取得した対戦ログリスト

    Returns:
        キャッシュ境界に到達した場合は True
    """
    if not current_page_replays:
        return True  # 空ページ = 終了

    latest_cached_at = self.get_latest_uploaded_at(player_id)
    if latest_cached_at is None:
        return False  # キャッシュなし = まだ続行

    # 現在のページの最も古い対戦ログが、キャッシュの最新より古い
    # = キャッシュ済みの領域に到達
    oldest_in_page = min(r.get("uploaded_at", float("inf")) for r in current_page_replays)
    return oldest_in_page <= latest_cached_at
```

### 2. 増分取得ロジックの実装

#### 2-1 BattlelogCollector に新メソッドを追加

```python
async def get_replay_list_incremental(
    self,
    player_id: str,
    language: str = "ja-jp",
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """
    最新キャッシュ以降のリプレイのみを増分取得

    Args:
        player_id: プレイヤーID
        language: 言語コード
        max_pages: 最大ページ数（安全装置）

    Returns:
        キャッシュ + 新規リプレイのマージ結果

    実行フロー:
    1. キャッシュから既存データと最新 uploaded_at を取得
    2. ページ1から順に取得開始
    3. 各ページ取得時に：
       - キャッシュにないリプレイを抽出・保存
       - 最新キャッシュの uploaded_at と同じリプレイが見つかったら、以降のページは取得しない
       - ページ内のリプレイが10件未満なら（ラストページなら）取得終了
    4. キャッシュ + 新規データをマージ
    """
    # 1. キャッシュから既存データを取得
    cached_replays = self.cache.get_cached_replays(player_id)
    cached_uploaded_at_set = self.cache.get_cached_uploaded_at_set(player_id)
    latest_cached_at = self.cache.get_latest_uploaded_at(player_id)

    logger.info(
        f"Starting incremental fetch for {player_id}: "
        f"latest_cached_at={latest_cached_at}, cached_count={len(cached_replays)}"
    )

    all_new_replays = []

    # 2. ページ1から順に取得
    for page in range(1, max_pages + 1):
        # ページを取得
        html = await self.get_battlelog_html(
            player_id=player_id,
            page=page,
            language=language,
        )

        try:
            next_data = BattlelogParser.extract_next_data(html)
            page_replays = BattlelogParser.get_replay_list(next_data)
            logger.info(
                f"Fetching battlelog for player {player_id}, page {page}: "
                f"got {len(page_replays)} replays"
            )
        except (ValueError, KeyError, Exception) as e:
            logger.error(f"Failed to parse page {page}: {e}")
            break

        # 3. キャッシュにない対戦ログを抽出
        new_page_replays = [
            r for r in page_replays
            if str(r.get("uploaded_at")) not in cached_uploaded_at_set
        ]

        if new_page_replays:
            all_new_replays.extend(new_page_replays)
            self.cache.cache_replays(player_id, new_page_replays)
            logger.info(f"Cached {len(new_page_replays)} new replays from page {page}")

        # 4. キャッシュ境界に到達したか確認
        if self.cache.has_reached_cache_boundary(player_id, page_replays):
            logger.info(
                f"Reached cache boundary at page {page}. "
                f"Stopping incremental fetch."
            )
            break

        # 5. ラストページの判定（10件未満）
        if len(page_replays) < 10:
            logger.info(
                f"Page {page} has only {len(page_replays)} replays. "
                f"This is likely the last page. Stopping fetch."
            )
            break

    logger.info(
        f"Incremental fetch completed: "
        f"fetched {len(all_new_replays)} new replays"
    )

    # 6. キャッシュ + 新規データをマージして返却
    return cached_replays + all_new_replays
```

#### 2-2 既存の `get_replay_list()` から新メソッドへの移行

```python
async def get_replay_list(
    self,
    player_id: str,
    page: int = 1,
    language: str = "ja-jp",
) -> list[dict[str, Any]]:
    """
    後方互換性のため、ページ単位の取得もサポート

    注: 新しい処理では get_replay_list_incremental() の使用を推奨
    """
    # ... 既存実装（ページ単位の取得）...
    pass
```

### 3. main.py での使用方法の変更

#### 修正前（ADR-022）
```python
# 全ページを順番に取得（20ページ常に全部）
async def get_all_replays():
    replays = []
    for page in range(1, 21):
        page_replays = await collector.get_replay_list(
            player_id=self.sf6_player_id, page=page
        )
        replays.extend(page_replays)
        if len(page_replays) < 10:
            break
    return replays
```

#### 修正後（本ADR）
```python
# 増分取得で最新キャッシュ以降のみ取得
async def get_all_replays():
    replays = await collector.get_replay_list_incremental(
        player_id=self.sf6_player_id
    )
    return replays
```

### 4. キャッシュ設計の改善

#### キャッシュ状態遷移図

```
初回実行
  ↓
キャッシュなし (latest_cached_at = None)
  → ページ1 (10件) → ページ2 (10件) → ... → ページN (< 10件) で終了
  → N ページ分をAPI呼び出し

2回目実行
  ↓
キャッシュあり (latest_cached_at = timestamp_X)
  → ページ1取得
    - 新規: キャッシュに保存
    - 既存: スキップ（重複排除）
  → ページ1内のリプレイの最小 uploaded_at ≤ latest_cached_at
    → キャッシュ境界に到達 → 取得終了
  → 0～2 ページ分のAPI呼び出しのみ
```

### 5. パフォーマンス改善の期待値

| メトリクス | 修正前（ADR-022） | 修正後（本ADR） |
|-----------|------------------|----------------|
| **初回実行** | 20回 | 最大10回 |
| **2回目実行** | 20回 | 0～2回 |
| **キャッシュヒット率** | 0%（ページ単位判定なし） | 90%+ |
| **平均レスポンス時間** | ~10秒 | 初回: ~5秒、以降: ~0.1秒 |

### 6. 実装の詳細

#### SQLiteスキーマ（既存のADR-022から拡張）

```sql
-- ADR-022 既存
CREATE TABLE replay_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    replay_data TEXT NOT NULL,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(player_id, uploaded_at)
);
```

追加の最適化（将来実装）：
```sql
-- ページ単位のキャッシング状態を追跡（オプション）
CREATE TABLE fetch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    fetch_date DATE NOT NULL,
    latest_page_fetched INT,
    latest_uploaded_at INT,
    total_fetched INT,
    UNIQUE(player_id, fetch_date)
);
```

## トレードオフと帰結

### メリット

- ✅ **API呼び出し大幅削減**: 初回最大50%削減、2回目以降90%削減
- ✅ **早期終了の実装**: キャッシュ境界で取得を中断
- ✅ **ページ遅延の回避**: 不要なページへのアクセスを防止
- ✅ **Battlelog仕様への準拠**: 実際のページ数（最大10）に基づいた実装

### デメリット

- ⚠️ **実装の複雑性増加**: キャッシュ境界判定のロジック
- ⚠️ **テストケース増加**: エッジケース（キャッシュなし、キャッシュあり、ラストページなど）

### 互換性

- ✅ ADR-022のキャッシュスキーマは変更なし（拡張のみ）
- ✅ 既存の `get_replay_list(page=N)` メソッドは互換性維持

## 将来の改善

1. **ページング情報の活用**
   - Battlelog API から `total_page` を取得して、最大ページ数を動的に決定

2. **fetch_history テーブルの導入**
   - 1日1回の全体再取得戦略の実装

3. **キャッシュ有効期限の設定**
   - ADR-022「TTL導入」との組み合わせ

## 参考資料

- [ADR-022: Battlelog API キャッシング機構（SQLite）](022-battlelog-api-caching-with-sqlite.md)
- [現在のAPI呼び出し実行ログ](../../packages/local/logs/sf6-chapter_20260217_114959.log)

## 実装チェックリスト

- [ ] `BattlelogCacheManager.get_latest_uploaded_at()` を実装
- [ ] `BattlelogCacheManager.has_reached_cache_boundary()` を実装
- [ ] `BattlelogCollector.get_replay_list_incremental()` を実装
- [ ] `main.py` の `_run_battlelog_matching()` を修正
- [ ] 単体テスト: キャッシュ境界判定
- [ ] 統合テスト: 初回実行と2回目実行の比較
- [ ] ログ出力を確認（API呼び出し回数の削減を検証）

## 次のステップ

1. **実装**: `BattlelogCacheManager` の新メソッドを追加
2. **実装**: `BattlelogCollector.get_replay_list_incremental()` を実装
3. **統合**: `main.py` で新メソッドを呼び出すよう修正
4. **テスト**: 初回実行と2回目実行のログで API 呼び出し回数を検証
5. **検証**: 「API呼び出し削減」の期待値が達成されたことを確認
