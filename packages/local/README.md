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

### 2. OAuth2認証の設定

Google Cloud Consoleで以下のAPIを有効化し、OAuth2クライアントシークレットを取得：

1. **Google Cloud Consoleにアクセス**
   - https://console.cloud.google.com/

2. **APIを有効化**
   - YouTube Data API v3
   - Vertex AI API

3. **OAuth2クライアントを作成**
   - 認証情報 → OAuth 2.0 クライアント ID を作成
   - アプリケーションの種類: デスクトップアプリ
   - `client_secrets.json` としてダウンロード

4. **ファイル配置**
   - `client_secrets.json`: プロジェクトルートに配置
   - `token.pickle`: 初回実行時に自動生成（YouTube API と Vertex AI で共通）

### 3. 環境変数の設定

`.env` ファイルを作成：

```bash
# Google Cloud
GCP_PROJECT_ID=your-project-id
PUBSUB_SUBSCRIPTION=sf6-video-process-sub

# Cloudflare R2
CLOUDFLARE_ACCOUNT_ID=your-account-id
R2_ACCESS_KEY_ID=your-access-key-id
R2_SECRET_ACCESS_KEY=your-secret-access-key

# Optional
TEMPLATE_PATH=./template/round1.png
DOWNLOAD_DIR=./download
```

**注**: Gemini APIはVertex AI経由でOAuth2認証を使用するため、`GEMINI_API_KEY`は不要です。

### 4. テンプレート画像

`template/round1.png` に「ROUND 1」画面のスクリーンショットを配置。

### 5. 初回認証フロー

初回実行時、ブラウザが自動的に開き、Googleアカウントでの認証が求められます：

1. Googleアカウントでログイン
2. アプリケーションへのアクセスを許可
3. 認証完了後、`token.pickle` が自動生成されます

**認証スコープ**:
- `https://www.googleapis.com/auth/youtube.force-ssl` - YouTube Data API
- `https://www.googleapis.com/auth/cloud-platform` - Vertex AI (Gemini API)

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

各処理ステップを個別に実行してテスト可能。`--video-id` を指定すれば、既存ファイルがある場合は自動的に再利用し、ない場合はダウンロードします。

#### 1. 動画ダウンロードのみ

```bash
uv run python main.py --mode test --test-step download --video-id YFQU_kkhZtg
```

**動作**: 既存ファイルがあれば「既存ファイルを使用」と表示して再利用、なければダウンロード。

#### 2. 対戦シーン検出のみ

```bash
# video-idを指定（既存ファイル自動検索、なければダウンロード）
uv run python main.py --mode test --test-step detect --video-id YFQU_kkhZtg

# または、video-pathを直接指定
uv run python main.py --mode test --test-step detect --video-path ./download/20250513[YFQU_kkhZtg].mkv
```

#### 3. キャラクター認識のみ

```bash
# video-idを指定（既存ファイル自動検索、なければダウンロード）
uv run python main.py --mode test --test-step recognize --video-id YFQU_kkhZtg

# または、video-pathを直接指定
uv run python main.py --mode test --test-step recognize --video-path ./download/20250513[YFQU_kkhZtg].mkv
```

#### 4. YouTubeチャプター更新のみ

```bash
# 通常: 検出・認識を実行してチャプター更新
uv run python main.py --mode test --test-step chapters --video-id YFQU_kkhZtg

# 保存済みチャプターファイルを使用（Gemini API課金を避ける）
uv run python main.py --mode test --test-step chapters --video-id YFQU_kkhZtg --use-saved-chapters
```

**動作**:
1. 通常モード: 既存ファイルを検索 → 検出 → 認識 → チャプター生成 → **中間ファイル保存** → YouTube更新
2. `--use-saved-chapters`: 保存済み中間ファイル（`chapters/[video_id]_chapters.json`）を読み込んでYouTube更新のみ実行

**中間ファイルの利点**:
- Gemini APIの課金を避けてチャプターのテスト・調整が可能
- 認識結果を保存して後から再利用
- チャプタータイトルの手動編集が可能

#### 5. 全ステップを順次実行

```bash
uv run python main.py --mode test --test-step all --video-id YFQU_kkhZtg
```

**動作**: ダウンロード → 検出 → 認識 → チャプター更新を一括実行。既存ファイルがあれば再利用。

### オプションパラメータ

- `--video-id`: YouTube動画ID（推奨）
- `--video-path`: ダウンロード済みファイルのパス（省略可、上級者向け）
- `--use-saved-chapters`: 保存済みチャプターファイルを使用（`--test-step chapters`のみ）

**推奨**: 基本的には `--video-id` のみを指定すれば、既存ファイルの再利用とダウンロードを自動判断します。

### チャプター中間ファイル

チャプター情報は `chapters/[video_id]_chapters.json` に自動保存されます。

**ファイル形式**:
```json
{
  "videoId": "YFQU_kkhZtg",
  "chapters": [
    {
      "startTime": 47,
      "title": "第01戦 Ryu VS Ken",
      "normalized": {"1p": "Ryu", "2p": "Ken"},
      "raw": {"1p": "リュウ", "2p": "ケン"}
    }
  ]
}
```

**使用例**:
1. 初回実行: `uv run python main.py --mode test --test-step chapters --video-id XXX`
   - チャプターファイルが自動保存される
2. タイトル調整: `chapters/XXX_chapters.json` を手動編集
3. 再実行: `uv run python main.py --mode test --test-step chapters --video-id XXX --use-saved-chapters`
   - Gemini APIを呼ばずに、編集済みチャプターでYouTube更新

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

### OAuth2認証エラー

**症状**: `FileNotFoundError: OAuth2クライアントシークレットファイルが見つかりません`

**解決方法**:
1. Google Cloud Consoleから `client_secrets.json` をダウンロード
2. プロジェクトルートに配置
3. 両方のAPIが有効化されているか確認

**症状**: `google.auth.exceptions.RefreshError`

**解決方法**:
1. `token.pickle` を削除
2. 再度実行して認証フローをやり直す

### yt-dlpでのダウンロード失敗

- Cookie認証が必要な場合は `cookie_path` を設定
- `VideoDownloader(cookie_path="./cookies.txt")`

### Gemini APIのレート制限

- OAuth2認証使用時も無料枠の制限あり: 15 RPM (Requests Per Minute)
- エラー時は自動でスキップし、次の対戦シーンへ

### R2アップロードエラー

- 認証情報を確認
- バケット名が正しいか確認

## 認証方式の変更履歴

### v2.0以降（推奨）
- **YouTube API**: OAuth2認証
- **Gemini API**: Vertex AI経由でOAuth2認証（共通トークン）
- トークンファイル: `token.pickle`（pickle形式）
- 環境変数 `GEMINI_API_KEY` は不要
- 環境変数 `GCP_PROJECT_ID` が必須

### v1.x（非推奨）
- **YouTube API**: OAuth2認証
- **Gemini API**: API Key認証
- トークンファイル: `token.pickle`（pickle形式）
- 環境変数 `GEMINI_API_KEY` が必要

**後方互換性**: `CharacterRecognizer(use_oauth=False, api_key="...")` で旧方式も使用可能
