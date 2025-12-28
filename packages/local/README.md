# SF6 Chapter - Local Processing

ローカルPC上で動作する動画処理スクリプト。

## 機能

1. **Pub/Sub受信**: Google Cloud Pub/Subから新着動画情報を受信
2. **動画ダウンロード**: yt-dlpを使用してYouTube動画をダウンロード
3. **対戦シーン検出**: OpenCVのテンプレートマッチングで「ROUND 1」画面を検出
4. **キャラクター認識**: Gemini APIでキャラクター名を認識・正規化
5. **チャプター生成**: YouTube Data APIで動画の説明文にチャプターを追加
6. **データアップロード**: Cloudflare R2にJSON/Parquetファイルをアップロード

## セットアップ

### 1. 依存関係のインストール

```bash
uv sync
```

### 2. 環境変数の設定

`.env` ファイルを作成：

```bash
# Google Cloud
GCP_PROJECT_ID=your-project-id
PUBSUB_SUBSCRIPTION=sf6-video-process-sub

# Gemini API
GEMINI_API_KEY=your-gemini-api-key

# Cloudflare R2
CLOUDFLARE_ACCOUNT_ID=your-account-id
R2_ACCESS_KEY_ID=your-access-key-id
R2_SECRET_ACCESS_KEY=your-secret-access-key

# Optional
TEMPLATE_PATH=./template/round1.png
DOWNLOAD_DIR=./download
```

### 3. 認証ファイルの配置

- `client_secrets.json`: YouTube Data API のOAuth2クライアントシークレット
- `token.pickle`: 認証トークン（初回実行時に自動生成）

### 4. テンプレート画像

`template/round1.png` に「ROUND 1」画面のスクリーンショットを配置。

## 実行方法

### ワンショットモード（1回だけPub/SubからPull）

```bash
uv run python main.py --mode once
```

### 常駐モード（ストリーミング受信）

```bash
uv run python main.py --mode daemon
```

### テストモード（個別処理の動作確認）

各処理ステップを個別に実行してテスト可能：

#### 1. 動画ダウンロードのみ

```bash
uv run python main.py --mode test --test-step download --video-id ZHA10O69Eew
```

#### 2. 対戦シーン検出のみ

```bash
uv run python main.py --mode test --test-step detect --video-path ./download/20250513[ZHA10O69Eew].mkv
```

#### 3. キャラクター認識のみ

```bash
uv run python main.py --mode test --test-step recognize --video-path ./download/20250513[ZHA10O69Eew].mkv
```

#### 4. YouTubeチャプター更新のみ

```bash
uv run python main.py --mode test --test-step chapters --video-id ZHA10O69Eew --video-path ./download/20250513[ZHA10O69Eew].mkv
```

#### 5. 全ステップを順次実行

```bash
uv run python main.py --mode test --test-step all --video-id ZHA10O69Eew
```

## モジュール構成

```
src/
├── pubsub/          # Pub/Sub受信
│   └── subscriber.py
├── video/           # 動画ダウンロード
│   └── downloader.py
├── detection/       # 対戦シーン検出
│   └── matcher.py
├── character/       # キャラクター認識
│   └── recognizer.py
├── youtube/         # YouTube チャプター更新
│   └── chapters.py
└── storage/         # R2アップロード
    └── r2_uploader.py
```

## データフロー

```
Pub/Sub受信
    ↓
動画ダウンロード (yt-dlp)
    ↓
テンプレートマッチング (OpenCV)
    ↓
キャラクター認識 (Gemini API)
    ↓
YouTubeチャプター更新 (YouTube Data API)
    ↓
R2アップロード (JSON + Parquet)
```

## トラブルシューティング

### yt-dlpでのダウンロード失敗

- Cookie認証が必要な場合は `cookie_path` を設定
- `VideoDownloader(cookie_path="./cookies.txt")`

### Gemini APIのレート制限

- 無料枠: 15 RPM (Requests Per Minute)
- エラー時は自動でスキップし、次の対戦シーンへ

### R2アップロードエラー

- 認証情報を確認
- バケット名が正しいか確認
