# チャプター処理フロー

`--mode test --test-step chapters --from-intermediate` 実行時の処理フローと、各データストアへの反映を図示したドキュメント。

## 対象コマンド

```bash
uv run python main.py --mode test --test-step chapters --video-id <VIDEO_ID> --from-intermediate
```

## 処理フロー図

```mermaid
flowchart TD
    subgraph CMD["コマンド実行"]
        A["uv run python main.py<br/>--mode test --test-step chapters<br/>--video-id QTqK4AD0ivY<br/>--from-intermediate"]
    end

    A --> B["test_chapters()<br/>from_intermediate=True"]

    subgraph CHAPTERS["test_chapters ステップ"]
        B --> C["load_recognition_results()"]
        C -->|読み込み| D[("📁 ローカルファイル<br/>./intermediate/{video_id}/<br/>chapters.json")]
        D --> E["チャプターデータ抽出<br/>startTime, title,<br/>matchId, winner_side"]
        E --> F["YouTubeChapterUpdater()"]
        F -->|OAuth2認証| G["get_video_info()<br/>YouTube Data API"]
        G --> H["generate_chapter_description()<br/>0:00 本編開始<br/>0:47 GOUKI VS JP<br/>..."]
        H --> I["update_video_description()"]
        I -->|API呼び出し| YT[("☁️ YouTube<br/>動画の説明欄に<br/>チャプター書き込み")]
    end

    I --> J["test_r2_upload()<br/>from_intermediate=True"]

    subgraph R2UPLOAD["test_r2_upload ステップ"]
        J --> K["YouTube API<br/>動画メタデータ取得<br/>title, publishedAt等"]
        J -->|読み込み| L1[("📁 ローカルファイル<br/>./intermediate/{video_id}/<br/>matches.json")]
        J -->|読み込み| L2[("📁 ローカルファイル<br/>./intermediate/{video_id}/<br/>chapters.json")]

        K --> M{"SF6_PLAYER_ID<br/>設定あり?"}
        L1 --> M
        L2 --> M

        M -->|Yes| N["Battlelog マッピング"]
        M -->|No| P["スキップ"]

        subgraph BL["Battlelog マッチング"]
            N --> N1["BattlelogSiteClient<br/>buildId取得"]
            N1 --> N2["BattlelogCollector<br/>増分取得 (キャッシュ+API)"]
            N2 -->|参照| CACHE[("📁 SQLiteキャッシュ<br/>battlelog_cache.db")]
            N2 --> N3["BattlelogMatcher<br/>チャプター↔リプレイ<br/>マッチング"]
            N3 --> N4["enriched_chapters<br/>player1_result, player2_result<br/>replay_id等を付与"]
        end

        N4 --> Q
        P --> Q["result フィールド統合"]

        Q --> Q1{"Battlelog<br/>result あり?"}
        Q1 -->|Yes| Q2["Battlelog結果を採用<br/>player1.result / player2.result"]
        Q1 -->|No| Q3{"winner_side<br/>あり?"}
        Q3 -->|Yes| Q4["RESULT検出結果から推定<br/>player1='win', player2='loss'等"]
        Q3 -->|No| Q5["result = None"]

        Q2 --> R
        Q4 --> R
        Q5 --> R

        R{"ENABLE_R2=true?"}

        R -->|Yes| S["R2Uploader"]
        R -->|No| T["スキップ<br/>ローカル処理のみ"]

        subgraph R2["Cloudflare R2 アップロード"]
            S --> S1["upload_json()<br/>videos/{video_id}.json"]
            S --> S2["upload_json()<br/>matches/{match_id}.json<br/>× N件"]
            S --> S3["update_parquet_table()<br/>videos.parquet<br/>※videoId単位で置換"]
            S --> S4["update_parquet_table()<br/>matches.parquet<br/>※videoId単位で置換"]

            S1 --> R2BUCKET[("☁️ Cloudflare R2<br/>sf6-chapter-data")]
            S2 --> R2BUCKET
            S3 --> R2BUCKET
            S4 --> R2BUCKET
        end
    end

    subgraph WEB["Cloudflare Pages (参照系)"]
        R2BUCKET -.->|"Pages Functions<br/>Presigned URL経由"| WEB1["フロントエンド<br/>DuckDB-WASMで<br/>Parquetクエリ"]
    end

    style CMD fill:#e1f5fe
    style YT fill:#ff8a80
    style R2BUCKET fill:#ffcc80
    style D fill:#c8e6c9
    style L1 fill:#c8e6c9
    style L2 fill:#c8e6c9
    style CACHE fill:#c8e6c9
    style WEB1 fill:#b3e5fc
```

## データの流れまとめ

### 入力（ローカルファイル）

| ファイル | 内容 |
|----------|------|
| `./intermediate/{video_id}/chapters.json` | 検出済みチャプター（startTime, title, winner_side等） |
| `./intermediate/{video_id}/matches.json` | 対戦データ（player1/player2のキャラ情報等） |

### 出力先 1: YouTube（説明欄チャプター）

`chapters.json` のデータが `YouTubeChapterUpdater.update_video_description()` を通じて **YouTube動画の説明欄** に反映される。

形式:
```
0:00 本編開始
0:47 GOUKI VS JP
2:15 CHUNLI VS GUILE
...
```

### 出力先 2: Cloudflare R2（`ENABLE_R2=true` の場合のみ）

| R2キー | 元データ | 内容 |
|--------|----------|------|
| `videos/{video_id}.json` | `matches.json` + YouTube API | 動画メタデータ + チャプター一覧 |
| `matches/{match_id}.json` | `matches.json` + Battlelog | 個別対戦データ（result含む） |
| `videos.parquet` | 上記JSONの集約 | 検索用（videoId単位で置換） |
| `matches.parquet` | 上記JSONの集約 | 検索用（videoId単位で置換） |

R2にアップロードされたParquetファイルは、Cloudflare Pages FunctionsのPresigned URL経由でフロントエンドに配信され、DuckDB-WASMでクエリされる。

### result フィールドの決定優先順位

1. **Battlelog API** の対戦結果（`SF6_PLAYER_ID` + `BUCKLER_ID_COOKIE` 設定時）
2. **RESULT画面テンプレートマッチング** の `winner_side`（フォールバック）
3. `None`（どちらも利用不可の場合）

## 関連する環境変数

| 変数名 | 用途 | デフォルト |
|--------|------|-----------|
| `INTERMEDIATE_DIR` | 中間ファイルの保存先 | `./intermediate` |
| `ENABLE_R2` | R2アップロードの有効化 | `false` |
| `R2_ACCESS_KEY_ID` | R2 APIキー | （`ENABLE_R2=true` 時に必須） |
| `R2_SECRET_ACCESS_KEY` | R2 APIシークレット | （`ENABLE_R2=true` 時に必須） |
| `R2_ENDPOINT_URL` | R2エンドポイント | （`ENABLE_R2=true` 時に必須） |
| `R2_BUCKET_NAME` | R2バケット名 | `sf6-chapter-data` |
| `SF6_PLAYER_ID` | Battlelogプレイヤー ID | （任意、設定時にBattlelogマッチング実行） |
| `BUCKLER_ID_COOKIE` | Battlelog認証Cookie | （任意、`SF6_PLAYER_ID` と併用） |
| `BATTLELOG_CACHE_DB` | SQLiteキャッシュファイルパス | `./battlelog_cache.db` |

## 関連ドキュメント

- [TEST_MODE_GUIDE.md](TEST_MODE_GUIDE.md) - テストモード全体のガイド
- [ADR-011](adr/011-intermediate-file-preservation.md) - 中間ファイル保存
- [ADR-018](adr/018-intermediate-file-format-improvement.md) - 中間ファイル形式改善
- [ADR-021](adr/021-battlelog-chapter-mapping-implementation.md) - Battlelogマッピング
- [ADR-026](adr/026-result-screen-match-outcome-detection.md) - RESULT画面勝敗検出
