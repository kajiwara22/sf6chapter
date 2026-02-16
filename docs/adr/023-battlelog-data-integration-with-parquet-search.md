# ADR-023: Battlelog データ統合と Parquet Web検索機能の実装

## ステータス

採用（Accepted） - 2026-02-17

## 文脈

YouTube 配信動画から自動検出した対戦チャプターに Battlelog リプレイデータ（キャラクター、勝敗）を統合し、Parquet ファイルに反映させることで、Web フロントエンドで「JPが勝った動画」「リュウが負けた動画」などの検索機能を実装する必要がある。

### 現状

- [ADR-020](020-sf6-battlelog-collector-implementation.md): Battlelog 対戦ログ収集システム実装完了
- [ADR-021](021-battlelog-chapter-mapping-implementation.md): YouTube チャプターと Battlelog リプレイのマッピング仕様確定
- [ADR-022](022-battlelog-api-caching-with-sqlite.md): Battlelog API キャッシング機構実装完了

### 課題

1. **データソースの統合**: Battlelog リプレイデータを YouTube チャプターと紐付ける仕組みが必要
2. **永続化**: マッピング結果を Parquet に反映させる処理が必要
3. **Web検索対応**: フロントエンドで「特定キャラクターの勝敗」で検索できるようにする必要がある
4. **キャッシング活用**: ADR-022 で実装したキャッシングを最大限活用して効率化する

### 要件

1. ローカル処理（`main.py`）で Battlelog マッピングを自動実行
2. マッピング結果を Parquet スキーマに追加
3. Web API（Pages Functions）で Parquet をフィルター可能にする
4. フロントエンドで検索フィルターを提供

## 決定

Battlelog データを統合し、Parquet に反映させて Web 検索を実現する。以下の実装を行う。

### 1. 処理フロー概要

```
[main.py 実行]
    ↓
1. YouTube チャプター検出 (ADR-001～018)
    ↓
2. YouTube チャプター更新
    └─ シンプルなタイトルのみ（"キャラ1 VS キャラ2" 形式）
    ↓
3. Battlelog マッピング実行 (ADR-021 + キャッシング ADR-022)
    ├─ キャッシュから既存データ取得
    ├─ API から新規データ取得＆キャッシュに保存
    └─ チャプターとリプレイを時系列マッピング
    ↓
4. マッピング結果を Parquet に統合
    ├─ player1_character / player1_result
    ├─ player2_character / player2_result
    └─ matched / confidence / time_difference_seconds
    ├─ battlelogMatched / battlelogConfidence / battlelogReplayId
    └─ R2 にアップロード
    ↓
5. [Web フロントエンド]
    ├─ Pages Functions から Parquet を取得
    ├─ DuckDB-WASM で SQL クエリ（検索フィルター適用）
    └─ フロントエンドで結果表示
    ↓
6. [注] YouTube チャプタータイトルは変更しない
    └─ YouTube側は シンプル、検索機能は Web で提供
```

### 2. Parquet スキーマ拡張

**新しいカラムの追加**:

```python
# 既存スキーマ（schema/chapter.parquet.schema.json）に以下を追加

{
  "chapters": [
    {
      "title": "string",
      "startTime": "integer",
      "endTime": "integer",
      "videoId": "string",
      "publishedAt": "timestamp[ns]",

      # ========== Battlelog マッピング結果（新規） ==========
      "battlelogMatched": "boolean",          # マッピング成功フラグ
      "battlelogConfidence": "string",        # 信頼度（high/medium/low）
      "battlelogReplayId": "string",          # リプレイID
      "battlelogTimeDiff": "integer",         # 時間差（秒）

      # プレイヤー1 情報
      "player1Character": "string",           # キャラクター名（正規化済）
      "player1Result": "string",              # 結果（win/loss）

      # プレイヤー2 情報
      "player2Character": "string",           # キャラクター名（正規化済）
      "player2Result": "string"               # 結果（win/loss）
    }
  ]
}
```

### 3. ローカル処理での統合実装

#### 3.1 `main.py` での処理フロー

**基本方針**: YouTube チャプター更新と Battlelog マッピングを独立させる

```
Step 1: 対戦シーン検出（従来通り）
  ↓
Step 2: YouTube チャプター更新（従来通り、シンプルなタイトルのみ）
  └─ "キャラ1 VS キャラ2" 形式
  ↓
Step 3: Battlelog マッピング実行（新規、オプショナル）
  └─ キャッシング機構を活用
  ↓
Step 4: Parquet に Battlelog データ統合して保存（新規）
  └─ Web 検索用
```

**理由**:
- YouTube チャプター自体はシンプルに保つ
- Battlelog 取得が失敗してもチャプター更新は成功している状態を保証
- Web での高度な検索機能は Parquet + DuckDB で実現

#### 3.2 必要なモジュール追加

```python
from sf6_battlelog import (
    BattlelogCollector,
    BattlelogCacheManager,
    BattlelogSiteClient
)
from src.battlelog_matcher import BattlelogMatcher

# キャッシュマネージャー初期化
cache_manager = BattlelogCacheManager(
    db_path=os.environ.get("BATTLELOG_CACHE_DB", "./battlelog_cache.db")
)
```

#### 3.3 Battlelog マッピング実行コード

```python
# Step 2: YouTube チャプター更新（従来通り）
logger.info("[4/6] Updating YouTube chapters...")
self.youtube_updater.update_video_description(video_id, chapters)
# ← ここまで従来通り、シンプルなタイトルのみ

# Step 3: Battlelog マッピング実行（新規、オプショナル）
chapters_with_battlelog = chapters  # デフォルト値
player_id = os.environ.get("SF6_PLAYER_ID")

if player_id:
    logger.info("[4.5/6] Matching Battlelog replays...")
    try:
        # 認証・初期化
        auth_cookie = os.environ.get("BUCKLER_ID_COOKIE")
        if not auth_cookie:
            logger.warn("BUCKLER_ID_COOKIE not set, skipping Battlelog matching")
        else:
            # buildId を取得
            site_client = BattlelogSiteClient()
            build_id = site_client.get_build_id_sync()

            # BattlelogCollector をキャッシング付きで初期化
            collector = BattlelogCollector(
                build_id=build_id,
                auth_cookie=auth_cookie,
                cache=cache_manager  # ← キャッシング利用
            )

            # 全ページ分のリプレイを取得（キャッシングで高速化）
            replays = []
            page = 1
            while True:
                page_replays = collector.get_replay_list_sync(
                    player_id=player_id,
                    page=page
                )
                replays.extend(page_replays)
                if len(page_replays) < 10:  # 最後のページ
                    break
                page += 1

            logger.info(f"Fetched {len(replays)} replays from Battlelog (cached + new)")

            # YouTube 公開日時を取得（ADR-021）
            youtube_uploader = YouTubeUploader()
            video_info = youtube_uploader.get_video_info(video_id)
            video_published_at = video_info.get("publishedAt")

            # マッピング実行
            matcher = BattlelogMatcher()
            chapters_with_battlelog = matcher.match_chapter_with_battlelog(
                chapters=chapters,
                replays=replays,
                video_published_at=video_published_at
            )

            logger.info(
                f"Matched {sum(1 for c in chapters_with_battlelog if c.get('matched'))} "
                f"out of {len(chapters_with_battlelog)} chapters"
            )

    except Exception as e:
        logger.error(f"Battlelog マッピング失敗: {e}")
        # フォールバック: Battlelog マッピングなしで続行
        # YouTube チャプターは既に更新されているため問題なし
        chapters_with_battlelog = chapters
else:
    logger.info("SF6_PLAYER_ID not set, skipping Battlelog matching")
```

#### 3.4 Parquet 更新時に Battlelog フィールドを追加

```python
# Step 5-6: R2 アップロード時に Parquet を更新
if self.enable_r2 and self.r2_uploader:
    logger.info("[5/6] Uploading JSON data to R2...")

    # video_data に Battlelog マッピング結果を含める
    video_data = {
        "videoId": video_id,
        "title": message_data.get("title", ""),
        "channelId": message_data.get("channelId", ""),
        "channelTitle": message_data.get("channelTitle", ""),
        "publishedAt": message_data.get("publishedAt", ""),
        "processedAt": datetime.utcnow().isoformat() + "Z",
        "chapters": chapters_with_battlelog,  # ← Battlelog データ含む
        "detectionStats": {
            "totalFrames": 0,
            "matchedFrames": len(chapters),
            "battlelogMatchedFrames": sum(1 for c in chapters_with_battlelog if c.get("matched")),
        },
    }

    # JSON データをアップロード
    self.r2_uploader.upload_json(video_data, f"videos/{video_id}.json")

    # 6. Parquet ファイルを更新
    logger.info("[6/6] Updating Parquet files...")
    self.r2_uploader.update_parquet_table(
        [video_data], "chapters.parquet", video_id=video_id
    )
```

#### 3.5 Parquet スキーマ（対応するフィールド定義）

```python
# Parquet 出力時のスキーマ（パイソンコード例）
parquet_schema = [
    # YouTube チャプター情報（従来）
    pa.field("videoId", pa.string()),
    pa.field("title", pa.string()),
    pa.field("startTime", pa.int32()),

    # Battlelog マッピング結果（新規）
    pa.field("battlelogMatched", pa.bool_()),
    pa.field("battlelogConfidence", pa.string()),  # "high" / "medium" / "low"
    pa.field("battlelogReplayId", pa.string(), nullable=True),
    pa.field("battlelogTimeDiff", pa.int32(), nullable=True),

    # プレイヤー1 情報
    pa.field("player1Character", pa.string(), nullable=True),
    pa.field("player1Result", pa.string(), nullable=True),  # "win" / "loss"

    # プレイヤー2 情報
    pa.field("player2Character", pa.string(), nullable=True),
    pa.field("player2Result", pa.string(), nullable=True),  # "win" / "loss"
]

schema = pa.schema(parquet_schema)
```

### 4. Web API（Pages Functions）での検索対応

#### 4.1 `/api/search` エンドポイント

**ファイル**: `packages/web/functions/api/search.ts`

```typescript
import { Handle } from 'hono/cloudflare-pages';
import { DuckDBWasm } from '@duckdb/wasm';

export const onRequest: Handle = async (context) => {
  const { searchParams } = new URL(context.request.url);

  // クエリパラメータから検索条件を取得
  const playerCharacter = searchParams.get('player_character'); // 例: "JP"
  const playerResult = searchParams.get('player_result');       // 例: "win"
  const minConfidence = searchParams.get('min_confidence');     // 例: "high"
  const videoId = searchParams.get('video_id');                 // 例: "dQwqkOG2SQo"

  try {
    // 1. Presigned URL から Parquet 取得
    const parquetData = await getParquetFromR2(context);

    // 2. DuckDB で SQL クエリ
    const db = new DuckDBWasm();
    const table = db.open(parquetData);

    // 3. 動的に WHERE 句を組み立て
    let where_clauses = [];
    if (playerCharacter) {
      where_clauses.push(
        `(player1Character = '${playerCharacter}' OR player2Character = '${playerCharacter}')`
      );
    }
    if (playerResult) {
      where_clauses.push(
        `((player1Character = '${playerCharacter}' AND player1Result = '${playerResult}') ` +
        `OR (player2Character = '${playerCharacter}' AND player2Result = '${playerResult}'))`
      );
    }
    if (minConfidence) {
      where_clauses.push(
        `battlelogConfidence IN ('${minConfidence}', 'high')`
      );
    }
    if (videoId) {
      where_clauses.push(`videoId = '${videoId}'`);
    }

    const where = where_clauses.length > 0 ? `WHERE ${where_clauses.join(' AND ')}` : '';
    const query = `
      SELECT
        videoId,
        title,
        startTime,
        endTime,
        player1Character,
        player1Result,
        player2Character,
        player2Result,
        battlelogConfidence,
        battlelogTimeDiff
      FROM parquet_scan('${parquetPath}')
      ${where}
      ORDER BY publishedAt DESC
    `;

    // 4. 結果を JSON で返却
    const result = await db.query(query);
    return new Response(JSON.stringify(result.toJSON()), {
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    logger.error('Search failed:', error);
    return new Response('Internal server error', { status: 500 });
  }
};
```

#### 4.2 クエリ例

```bash
# JPが勝った動画を検索
curl "https://sf6.example.com/api/search?player_character=JP&player_result=win&min_confidence=high"

# リュウが負けた動画を検索
curl "https://sf6.example.com/api/search?player_character=RYU&player_result=loss&min_confidence=medium"

# GOUKIとJPの対戦シーンを検索
curl "https://sf6.example.com/api/search?player_character=GOUKI&video_id=dQwqkOG2SQo"
```

### 5. フロントエンド（HTML/TypeScript）での検索UI

**ファイル**: `packages/web/src/search-page.ts` (サーバーサイド HTML生成) または `packages/web/src/client/search.ts` (クライアント側)

#### 5.1 HTML マークアップ例

```html
<div class="search-filter">
  <div class="filter-group">
    <label for="character-select">キャラクター選択:</label>
    <select id="character-select" name="character">
      <option value="">すべて</option>
      <option value="RYU">リュウ</option>
      <option value="JP">JP</option>
      <option value="GOUKI">ゴウキ</option>
      <!-- ... その他キャラクター ... -->
    </select>
  </div>

  <div class="filter-group">
    <label for="result-select">結果選択:</label>
    <select id="result-select" name="result">
      <option value="">すべて</option>
      <option value="win">勝利</option>
      <option value="loss">敗北</option>
    </select>
  </div>

  <div class="filter-group">
    <label for="confidence-select">信頼度:</label>
    <select id="confidence-select" name="confidence">
      <option value="">すべて</option>
      <option value="high">高</option>
      <option value="medium">中</option>
    </select>
  </div>

  <button id="search-button">検索</button>
</div>

<div id="results-container">
  <!-- 検索結果がここに表示される -->
</div>
```

#### 5.2 TypeScript（クライアント側ロジック）

```typescript
// packages/web/src/client/search.ts
interface SearchParams {
  playerCharacter?: string;
  playerResult?: string;
  minConfidence?: string;
}

interface ChapterResult {
  videoId: string;
  title: string;
  startTime: number;
  player1Character?: string;
  player1Result?: string;
  player2Character?: string;
  player2Result?: string;
  battlelogConfidence?: string;
}

class ChapterSearchUI {
  private characterSelect: HTMLSelectElement;
  private resultSelect: HTMLSelectElement;
  private confidenceSelect: HTMLSelectElement;
  private searchButton: HTMLButtonElement;
  private resultsContainer: HTMLDivElement;

  constructor() {
    this.characterSelect = document.getElementById('character-select') as HTMLSelectElement;
    this.resultSelect = document.getElementById('result-select') as HTMLSelectElement;
    this.confidenceSelect = document.getElementById('confidence-select') as HTMLSelectElement;
    this.searchButton = document.getElementById('search-button') as HTMLButtonElement;
    this.resultsContainer = document.getElementById('results-container') as HTMLDivElement;

    this.searchButton.addEventListener('click', () => this.handleSearch());
    // Enter キーでも検索実行
    [this.characterSelect, this.resultSelect, this.confidenceSelect].forEach(el => {
      el.addEventListener('change', () => this.handleSearch());
    });
  }

  private async handleSearch(): Promise<void> {
    const params: SearchParams = {};

    if (this.characterSelect.value) {
      params.playerCharacter = this.characterSelect.value;
    }
    if (this.resultSelect.value) {
      params.playerResult = this.resultSelect.value;
    }
    if (this.confidenceSelect.value) {
      params.minConfidence = this.confidenceSelect.value;
    }

    try {
      const queryString = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v) as [string, string][]
      ).toString();

      const response = await fetch(`/api/search?${queryString}`);
      const results: ChapterResult[] = await response.json();

      this.renderResults(results);
    } catch (error) {
      console.error('Search failed:', error);
      this.resultsContainer.innerHTML = '<p>検索中にエラーが発生しました</p>';
    }
  }

  private renderResults(chapters: ChapterResult[]): void {
    if (chapters.length === 0) {
      this.resultsContainer.innerHTML = '<p class="no-results">マッチする動画がありません</p>';
      return;
    }

    const html = chapters
      .map(chapter => `
        <div class="result-item">
          <div class="title">${this.escapeHtml(chapter.title)}</div>
          <div class="info">
            ${this.escapeHtml(chapter.player1Character || 'Unknown')} (${chapter.player1Result || 'N/A'})
            vs
            ${this.escapeHtml(chapter.player2Character || 'Unknown')} (${chapter.player2Result || 'N/A'})
          </div>
          <div class="confidence">
            信頼度: ${chapter.battlelogConfidence || 'N/A'}
          </div>
          <a href="https://youtu.be/${chapter.videoId}?t=${chapter.startTime}" target="_blank">
            動画を見る
          </a>
        </div>
      `)
      .join('');

    this.resultsContainer.innerHTML = html;
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

// ページ読み込み後に初期化
document.addEventListener('DOMContentLoaded', () => {
  new ChapterSearchUI();
});
```

#### 5.3 CSS スタイル

```css
.search-filter {
  padding: 20px;
  background: #f5f5f5;
  border-radius: 8px;
  margin-bottom: 20px;
}

.filter-group {
  margin-bottom: 15px;
}

.filter-group label {
  display: block;
  margin-bottom: 5px;
  font-weight: bold;
}

.filter-group select {
  width: 100%;
  padding: 8px;
  border-radius: 4px;
  border: 1px solid #ccc;
}

#search-button {
  padding: 10px 20px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
}

#search-button:hover {
  background: #45a049;
}

#results-container {
  margin-top: 20px;
}

.result-item {
  background: white;
  padding: 15px;
  margin-bottom: 10px;
  border-radius: 4px;
  border-left: 4px solid #4CAF50;
}

.result-item .title {
  font-weight: bold;
  margin-bottom: 5px;
}

.result-item .info {
  color: #666;
  margin-bottom: 5px;
}

.result-item .confidence {
  font-size: 0.9em;
  color: #999;
  margin-bottom: 10px;
}

.result-item a {
  color: #4CAF50;
  text-decoration: none;
}

.result-item a:hover {
  text-decoration: underline;
}

.no-results {
  text-align: center;
  color: #999;
  padding: 20px;
}
```

### 6. キャッシング戦略

ADR-022 で実装したキャッシング機構を最大限活用：

| タイミング | 処理内容 | キャッシュ利用 |
|-----------|---------|--------------|
| **初回実行** | 全 Battlelog リプレイを API から取得 | 初期化、キャッシュに保存 |
| **2回目以降** | 新規リプレイのみ API から取得 | キャッシュ + 差分API |
| **キャッシュヒット率** | 繰り返し実行時は 95%+ | 高速化、API 呼び出し削減 |
| **ストレージ** | SQLite DB 永続化 | PC 再起動後も継続利用 |

### 7. エラーハンドリング

```python
# Battlelog マッピング失敗時の対応
try:
    chapters = battlelog_matcher.match_chapter_with_battlelog(...)
except BattlelogCollector.Unauthorized:
    logger.warn("Battlelog 認証失敗、チャプターのみ出力")
    # マッピングなしで処理継続
except BattlelogCollector.PageNotFound:
    logger.warn(f"プレイヤー {player_id} が見つかりません")
except Exception as e:
    logger.error(f"予期しないエラー: {e}")

# Web API でのエラーハンドリング
try {
  const result = await db.query(query);
} catch (error) {
  if (error.message.includes('Invalid SQL')) {
    return new Response('Invalid query parameters', { status: 400 });
  }
  logger.error('Query failed:', error);
  return new Response('Internal server error', { status: 500 });
}
```

### 8. パフォーマンス考慮

#### 8.1 ローカル処理

- **キャッシング効果**: 2回目以降の実行は 50～100 倍高速化
- **ページネーション**: 対戦ログが多い場合は非同期で段階的に取得
- **並列処理**: 複数プレイヤーのマッピングは並列実行（リソース許可範囲内）

#### 8.2 Web API

- **Presigned URL キャッシング**: 1 時間有効、API 呼び出し削減
- **DuckDB クエリ最適化**: インデックス活用、WHERE 句最適化
- **結果キャッシング**: ブラウザキャッシュ + Service Worker 活用

### 9. 実装スケジュール

| フェーズ | タスク | 期間 |
|---------|-------|------|
| **Phase 1** | `main.py` に Battlelog マッピング統合 | 2-3日 |
| **Phase 2** | Parquet スキーマ拡張 & R2 アップロード | 1-2日 |
| **Phase 3** | Web API（Pages Functions）実装 | 2-3日 |
| **Phase 4** | フロントエンド UI 実装 & E2E テスト | 2-3日 |

## 設計上の重要な決定

### YouTube チャプター vs Web 検索機能の分離（案3）

**採択理由**: YouTube チャプター自体はシンプルに、高度な検索機能は Web で提供

| 項目 | YouTube チャプター | Web（Parquet） |
|------|------|------|
| **タイトル** | "キャラ1 VS キャラ2"（シンプル） | フルデータ搭載 |
| **Battlelog 情報** | 含めない | 含める |
| **更新タイミング** | 対戦検出直後 | Battlelog マッピング後 |
| **失敗時の影響** | チャプターは更新済み | Parquet は Battlelog 補完なし |
| **検索機能** | YouTube の検索機能のみ | DuckDB-WASM + 高度なフィルター |

**メリット**:
- ✅ **責任分離**: YouTube（シンプル）と Web（高機能）を独立させる
- ✅ **堅牢性**: Battlelog 失敗時も YouTube チャプター更新は成功
- ✅ **ユーザー体験**: YouTube は見やすい、Web は検索性重視
- ✅ **保守性**: 各システムの責務が明確
- ✅ **拡張性**: Web 検索機能の強化が YouTube に影響しない

**デメリット**:
- ⚠️ **2系統の管理**: YouTube と Parquet の2つを管理する必要
- ⚠️ **データ一貫性**: 異なるデータ構造を同期させる必要（ただし通常は影響なし）

---

## トレードオフと帰結

### メリット

- ✅ **独立した処理フロー**: YouTube チャプター更新と Battlelog マッピングを分離
- ✅ **高速な Web 検索**: DuckDB-WASM + キャッシング で高速検索
- ✅ **キャッシング活用**: ADR-022 の効果を最大化（2回目以降 50～100 倍高速化）
- ✅ **堅牢性**: Battlelog 失敗時も YouTube チャプターは更新済み
- ✅ **スケーラビリティ**: 複数プレイヤー・動画に対応
- ✅ **シンプルな YouTube**: チャプタータイトルは読みやすく、動画を見る際の邪魔にならない

### デメリット

- ⚠️ **API 依存**: Battlelog・YouTube API の安定性に依存
- ⚠️ **スキーマ変更**: Parquet スキーマを拡張するため既存ツールとの互換性確認必要
- ⚠️ **マッピング精度**: 時間差による照合のため 100% 正確性は保証されない（信頼度レベルで区別）
- ⚠️ **2系統管理**: YouTube と Parquet を並列管理する手間

### 将来の改善

1. **機械学習ベースの照合**
   - 複数特徴量（時間差、キャラ、ラウンド情報）を使用した照合精度向上

2. **キャッシングの自動更新**
   - TTL ベースの自動無効化
   - 増分更新の最適化

3. **複数プレイヤー対応**
   - 複数プレイヤーの Battlelog データを統合
   - グループマッチング機能

4. **Web UI の高度化**
   - ファセット検索（複数フィルターの組み合わせ）
   - 検索結果の可視化（グラフ表示）
   - キャラクター別統計（勝率、出場頻度など）

5. **YouTube との連携強化（将来）**
   - YouTube カスタム URL スキーム対応（動画の特定シーンへジャンプ）
   - 検索結果から YouTube チャプターへのリンク生成

## 実装ファイル一覧

### 新規作成ファイル

| ファイル | 説明 |
|----------|------|
| `packages/web/functions/api/search.ts` | Web API（/api/search、DuckDB-WASM 対応） |
| `packages/web/src/client/search.ts` | フロントエンド検索ロジック（TypeScript） |
| `packages/web/src/search-page.ts` | 検索ページの HTML 生成（Hono） |
| `packages/local/src/battlelog_matcher.py` | BattlelogMatcher クラス（ADR-021 参照） |

### 修正ファイル

| ファイル | 変更内容 |
|----------|---------|
| `packages/local/main.py` | Step 3「Battlelog マッピング実行」を追加（Step 2 の YouTube チャプター更新とは独立） |
| `schema/chapter.parquet.schema.json` | Parquet スキーマ拡張（battlelogMatched, player1Character 等） |
| `packages/web/functions/api/chapters.ts` | Parquet レスポンスに新フィールド追加 |
| `packages/local/pyproject.toml` | 依存関係追加（既存: playwright, aiohttp） |

### 既存で対応するファイル

| ファイル | 役割 |
|----------|------|
| `packages/local/src/sf6_battlelog/cache.py` | キャッシング機構（ADR-022） |
| `packages/local/scripts/test_battlelog_mapping.py` | マッピング実装（ADR-021） |
| `packages/local/src/sf6_battlelog/` | Battlelog 収集（ADR-020） |
| `packages/local/src/youtube.py` | YouTube チャプター更新（従来通り、シンプルなタイトルのみ） |

## 関連する ADR

- [ADR-010: Parquet データ取得方式（Presigned URL）](010-parquet-presigned-url.md)
- [ADR-020: SF6 Battlelog 対戦ログ収集システムの実装](020-sf6-battlelog-collector-implementation.md)
- [ADR-021: YouTube チャプターと Battlelog リプレイのマッピング実装](021-battlelog-chapter-mapping-implementation.md)
- [ADR-022: Battlelog API キャッシング機構（SQLite）](022-battlelog-api-caching-with-sqlite.md)

## 検証方法

### 1. ローカル処理検証

```bash
# Battlelog マッピング付きで main.py を実行
cd packages/local
BUCKLER_ID_COOKIE="..." \
GOOGLE_APPLICATION_CREDENTIALS="..." \
uv run python main.py \
  --mode oneshot \
  --video-id dQwqkOG2SQo \
  --player-id 1319673732

# intermediate ファイルで battlelog マッピング結果を確認
cat ./intermediate/dQwqkOG2SQo/chapters.json | jq '.[] | {title, player1_character, player1_result, player2_character, player2_result}'
```

### 2. Parquet スキーマ検証

```python
import pyarrow.parquet as pq

# Parquet ファイルを読み込み
parquet_file = pq.read_table("chapters.parquet")

# 新しいカラムが存在することを確認
assert 'battlelogMatched' in parquet_file.column_names
assert 'player1Character' in parquet_file.column_names
assert 'player1Result' in parquet_file.column_names
print("✓ スキーマ検証成功")

# データを表示
print(parquet_file.to_pandas())
```

### 3. Web API 検証

```bash
# 検索 API をテスト
curl "http://localhost:8787/api/search?player_character=JP&player_result=win"

# 期待される出力: JSON 配列
# [
#   {
#     "videoId": "dQwqkOG2SQo",
#     "title": "JP VS GOUKI",
#     "player1Character": "GOUKI",
#     "player1Result": "loss",
#     "player2Character": "JP",
#     "player2Result": "win",
#     ...
#   }
# ]
```

### 4. フロントエンド統合テスト

```bash
# Web サーバーを起動
cd packages/web
npm run dev

# ブラウザで http://localhost:5173 を開く
# 検索フィルターで試すして動画が表示されることを確認
```

## 成功基準

1. ✅ `main.py` で Battlelog マッピング後の章が中間ファイルに出力される
2. ✅ Parquet ファイルに新フィールド（`battlelogMatched`, `player1Character` など）が含まれる
3. ✅ `/api/search` エンドポイントで検索パラメータに応じたフィルタリングが可能
4. ✅ フロントエンド UI で「JPが勝った」などの検索ができる
5. ✅ キャッシング効果により 2 回目以降の実行が高速化

## 参考資料

- [DuckDB WASM Documentation](https://duckdb.org/docs/api/wasm/)
- [Parquet Format Specification](https://parquet.apache.org/)
- [Vue.js 3 Composition API](https://vuejs.org/guide/extras/composition-api-faq.html)
- [Hono Web Framework](https://hono.dev/)

## 次のステップ

1. Phase 1: `main.py` への Battlelog マッピング統合
2. Phase 2: Parquet スキーマ拡張＆テストデータ作成
3. Phase 3: Web API（Pages Functions）実装＆検証
4. Phase 4: フロントエンド UI 実装＆E2E テスト
