# ADR-022: Battlelog API キャッシング機構（SQLite）

## ステータス

採用（Accepted） - 2026-02-17

## 文脈

Battlelog API から対戦ログを取得する際、毎回 API を呼び出しするとサーバー負荷が増加し、レスポンス時間が低下する。一方、対戦ログデータは基本的に不変（新しいログが追加されるが、既存ログは修正されない）であるため、キャッシング機構の導入が効果的。

### 問題

- **API呼び出しの重複**: 同じ `player_id` に対する複数回の API リクエスト
- **サーバー負荷**: Battlelog API 側への過負荷につながる可能性
- **レスポンス遅延**: ネットワークレイテンシを毎回発生させている

### 要件

1. **キャッシュキー**: `player_id` + `uploaded_at` の組み合わせで一意性を保証
2. **キャッシュ対象**: 対戦ログリスト（`get_replay_list()` メソッド）
3. **キャッシュ有効期限**: 無制限（新規ログ追加時にアクティブに新データを取得）
4. **既存ログの修正**: 考慮しない（追加のみ対応）

## 決定

Battlelog API のレスポンスを SQLite でキャッシングする機構を導入する。以下の仕様で実装する。

### 1. SQLite スキーマ

```sql
CREATE TABLE replay_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,

    -- キャッシュデータ（JSON形式で保存）
    replay_data TEXT NOT NULL,  -- 対戦ログ1件のJSON

    -- メタデータ
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(player_id, uploaded_at)
);

CREATE INDEX idx_player_id ON replay_cache(player_id);
CREATE INDEX idx_uploaded_at ON replay_cache(uploaded_at);
```

**カラム説明**:

- `id`: 自動採番ID
- `player_id`: プレイヤーID（例: `"1319673732"`）
- `uploaded_at`: リプレイのアップロード日時（対戦ログオブジェクト内のフィールド）
- `replay_data`: 対戦ログ1件の JSON 文字列化データ
- `cached_at`: キャッシュ追加日時（自動タイムスタンプ）
- `UNIQUE(player_id, uploaded_at)`: 重複防止制約

### 2. キャッシュ管理クラス：BattlelogCacheManager

**ファイル**: `packages/local/src/sf6_battlelog/cache.py` (新規作成)

#### 主要メソッド

##### `__init__(db_path: str = "./battlelog_cache.db")`
- SQLite データベースを初期化
- テーブルが存在しなければ自動作成

##### `get_cached_replays(player_id: str) -> list[dict[str, Any]]`
- キャッシュから `player_id` に一致するすべての対戦ログを取得
- 返り値: 対戦ログの配列

##### `cache_replay(player_id: str, replay: dict[str, Any]) -> bool`
- 単一の対戦ログをキャッシュに保存
- `UNIQUE` 制約違反時は無視（べき等性）
- 返り値: 新規追加時は `True`、既存時は `False`

##### `cache_replays(player_id: str, replays: list[dict[str, Any]]) -> int`
- 複数の対戦ログを一括キャッシュ
- 返り値: 新規追加されたレコード数

##### `get_cached_uploaded_at_set(player_id: str) -> set[str]`
- 特定 `player_id` のキャッシュ済み `uploaded_at` 値の集合を取得
- キャッシュの有無判定に利用

##### `get_all_cached_replays() -> list[dict[str, Any]]`
- キャッシュ全体のすべての対戦ログを取得

##### `clear_cache(player_id: Optional[str] = None) -> int`
- キャッシュをクリア
- `player_id` 指定時: その プレイヤーのキャッシュのみ削除
- `player_id` 未指定時: 全キャッシュ削除
- 返り値: 削除されたレコード数

##### `get_cache_stats() -> dict[str, Any]`
- キャッシュ統計情報を取得
- 返り値:
  ```json
  {
    "total_records": 1234,
    "unique_players": 45,
    "unique_replays_by_player": { "1319673732": 89, ... },
    "db_size_bytes": 5242880
  }
  ```

### 3. BattlelogCollector への統合

**ファイル**: `packages/local/src/sf6_battlelog/api_client.py` (修正)

#### 修正内容

##### `__init__()` に キャッシュマネージャーを追加

```python
def __init__(
    self,
    build_id: str,
    auth_cookie: str,
    user_agent: Optional[str] = None,
    timeout: int = 30,
    cache: Optional[BattlelogCacheManager] = None,
):
    # ... 既存のコード ...
    self.cache = cache or BattlelogCacheManager()
```

##### `get_replay_list()` メソッドを修正

**フロー**:
1. キャッシュから `player_id` の既存データを取得
2. API から新規データを取得
3. キャッシュにない対戦ログのみをフィルタリング
4. 新規データをキャッシュに保存
5. 既存キャッシュ + 新規データをマージして返却

**実装例**:
```python
async def get_replay_list(
    self,
    player_id: str,
    page: int = 1,
    language: str = "ja-jp",
) -> list[dict[str, Any]]:
    # 1. キャッシュから既存データを取得
    cached_replays = self.cache.get_cached_replays(player_id)
    cached_uploaded_at_set = set(r.get("uploaded_at") for r in cached_replays)

    # 2. API から新規データを取得
    api_replays = await self._fetch_replay_list(player_id, page, language)

    # 3. キャッシュにない対戦ログを抽出
    new_replays = [
        r for r in api_replays
        if r.get("uploaded_at") not in cached_uploaded_at_set
    ]

    # 4. 新規データをキャッシュに保存
    if new_replays:
        self.cache.cache_replays(player_id, new_replays)
        logger.info(f"Cached {len(new_replays)} new replays for {player_id}")

    # 5. マージして返却
    return cached_replays + api_replays
```

### 4. キャッシュ戦略

#### キャッシュ更新タイミング

| 場面 | 動作 | 理由 |
|------|------|------|
| 初回実行 | すべて API から取得 → キャッシュ保存 | 初期化 |
| 2回目以降 | キャッシュ + API（新規のみ）を統合 | 差分更新効率化 |
| ローカルPC再起動 | キャッシュが永続化されているため使用継続 | 前回のデータを再利用 |

#### ページネーション対応

- 各ページからキャッシュにない対戦ログのみを抽出
- 全ページ分の新規データが蓄積されていく

#### 無効化戦略

```bash
# テスト時など、キャッシュをクリア（手動）
uv run -c "
from sf6_battlelog import BattlelogCacheManager
cache = BattlelogCacheManager()
cache.clear_cache(player_id='1319673732')
"
```

### 5. パフォーマンス効果

#### 期待される改善

| メトリクス | 改善前 | 改善後 |
|-----------|--------|--------|
| API呼び出し回数 | n (全ページ) | 1～n（差分のみ） |
| 平均レスポンス時間 | ~2-5秒 | ~0.1秒（キャッシュヒット時） |
| サーバー負荷 | 高 | 低 |
| ストレージ | 0 | ~10-50MB（対戦ログ数依存） |

**例**: 1000件の対戦ログを持つプレイヤーの場合、2回目以降のアクセスは 100倍高速化。

### 6. テストスクリプト

**ファイル**: `packages/local/scripts/test_battlelog_cache.py` (新規作成)

#### 動作確認項目

1. **キャッシュの基本操作**
   - 対戦ログを保存
   - キャッシュから取得
   - 重複回避（UNIQUE 制約）

2. **API 統合テスト**
   - 初回実行（キャッシュなし）
   - 2回目実行（キャッシュあり）
   - 新規データのみ API から取得される

3. **統計情報**
   - キャッシュサイズ確認
   - レコード数確認

#### 実行方法

```bash
# テスト実行
uv run scripts/test_battlelog_cache.py \
  --player-id 1319673732 \
  --output-format pretty
```

### 7. ファイル構成

```
packages/local/
├── src/sf6_battlelog/
│   ├── __init__.py
│   ├── api_client.py          # 修正：キャッシュ統合
│   ├── cache.py               # 新規：キャッシュマネージャー
│   ├── authenticator.py
│   ├── site_client.py
│   └── battlelog_parser.py
├── scripts/
│   └── test_battlelog_cache.py  # 新規：テストスクリプト
├── battlelog_cache.db          # SQLite DB（自動生成）
└── pyproject.toml
```

## トレードオフと帰結

### メリット

- ✅ **API 呼び出し削減**: 差分更新により大幅に削減
- ✅ **レスポンス高速化**: キャッシュヒット時は 100倍以上高速
- ✅ **サーバー負荷軽減**: Battlelog API 側への負荷を削減
- ✅ **ローカル永続化**: ローカル PC 再起動後も継続利用可能
- ✅ **実装の簡潔性**: SQLite で標準的なキャッシング機構

### デメリット

- ⚠️ **ストレージ消費**: SQLite DB が増加（対戦ログ数に依存）
- ⚠️ **手動無効化が必要**: TTL がないため、古いデータを明示的に削除する必要がある
- ⚠️ **同期メソッドのみ対応**: 初期実装は同期版 `get_replay_list_sync()` のみ

### 将来の改善

1. **TTL (Time-To-Live) の導入**
   - キャッシュの自動失効機構を追加
   - 設定可能な有効期限（例: 7日間）

2. **非同期対応**
   - 非同期版 `get_replay_list()` への統合

3. **キャッシュ戦略の最適化**
   - LRU (Least Recently Used) キャッシュに移行
   - 容量制限の導入

4. **統計・監視**
   - キャッシュヒット率の記録
   - パフォーマンス改善の可視化

## 参考資料

- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [Python sqlite3 Module](https://docs.python.org/3/library/sqlite3.html)
- [ADR-006: Firestore による重複防止](006-firestore-for-duplicate-prevention.md)

## 実装チェックリスト

- [ ] `packages/local/src/sf6_battlelog/cache.py` を作成
- [ ] `BattlelogCacheManager` クラスを実装
- [ ] `BattlelogCollector.get_replay_list()` にキャッシュ統合
- [ ] テストスクリプト `test_battlelog_cache.py` を作成
- [ ] キャッシュの動作を検証
- [ ] `pyproject.toml` に必要な依存関係を追加（必要に応じて）
- [ ] ドキュメント更新（本 ADR）

## 次のステップ

1. **実装**: `cache.py` と `test_battlelog_cache.py` を作成
2. **統合テスト**: 実際の API を使用してキャッシング動作を検証
3. **本流統合**: `main.py` で BattlelogCollector を使用する際にキャッシングを有効化
