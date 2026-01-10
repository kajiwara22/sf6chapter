# SF6 Chapter - Local Processing

ローカルPC上で動作する動画処理スクリプト。

## 機能

1. **Pub/Sub受信**: Google Cloud Pub/Subから新着動画情報を受信
2. **重複処理防止**: Firestoreで処理済み動画を追跡し、再処理を防止
3. **動画ダウンロード**: yt-dlpを使用してYouTube動画をダウンロード
4. **対戦シーン検出**: OpenCVのテンプレートマッチングで「ROUND 1」画面を検出
5. **キャラクター認識**: Gemini APIでキャラクター名を認識・正規化
6. **チャプター生成**: YouTube Data APIで動画の説明文にチャプターを追加
7. **データアップロード**: Cloudflare R2にJSON/Parquetファイルをアップロード

## セットアップ

### 1. 依存関係のインストール

```bash
uv sync
```

### 1.5. yt-dlp用JavaScriptランタイムのセットアップ（推奨）

YouTube動画のダウンロードには、yt-dlpがJavaScriptチャレンジを解決するための外部JSランタイムが必要です。

#### オプション1: Denoを使用（推奨）

Denoはyt-dlpでデフォルトで有効化されており、設定ファイルでパスを明示することで確実に動作します。

**インストール**:

```bash
# Homebrewの場合
brew install deno

# mise経由の場合（このプロジェクトで使用）
mise use deno@latest
```

**yt-dlp設定ファイルの作成**:

mise経由でインストールした場合、yt-dlpがDenoを自動検出できない可能性があるため、設定ファイルでパスを明示します：

```bash
mkdir -p ~/.config/yt-dlp
echo "--js-runtimes deno:$(mise where deno)/bin/deno" > ~/.config/yt-dlp/config
```

インストール後、yt-dlpは設定ファイルを読み込んでDenoを使用します。

#### オプション2: 既存のNode.jsまたはBunを使用

既にNode.jsまたはBunがインストールされている場合、それらを使用できます。

**Node.js使用時**（最低バージョン: 20.0.0）:

yt-dlp設定ファイル（`~/.config/yt-dlp/config`）に以下を追加：

```
--js-runtimes node
```

**Bun使用時**（最低バージョン: 1.0.31）:

```
--js-runtimes bun
```

#### EJSスクリプトの自動インストール

`yt-dlp[default]`をインストールすると、EJSスクリプトパッケージ（`yt-dlp-ejs`）が自動的に含まれます。

**確認方法**:

```bash
uv run python -c "import yt_dlp; print(yt_dlp.version.__version__)"
```

**参考**:
- [yt-dlp Wiki: EJS Setup Guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS)

### 2. OAuth2認証の設定

Google Cloud Consoleで以下のAPIを有効化し、OAuth2クライアントシークレットを取得：

1. **Google Cloud Consoleにアクセス**
   - https://console.cloud.google.com/

2. **APIを有効化**
   - YouTube Data API v3
   - Vertex AI API
   - Cloud Firestore API

3. **OAuth2クライアントを作成**
   - 認証情報 → OAuth 2.0 クライアント ID を作成
   - アプリケーションの種類: デスクトップアプリ
   - `client_secrets.json` としてダウンロード

4. **ファイル配置**
   - `client_secrets.json`: プロジェクトルートに配置
   - `token.pickle`: 初回実行時に自動生成（YouTube API、Vertex AI、Firestoreで共通）

5. **Firestoreデータベースの作成**
   - Google Cloud Console → Firestore → データベースを作成
   - モード: Nativeモード（推奨）
   - ロケーション: 任意のリージョン（us-central1推奨）
   - OAuth2認証を使用するため、サービスアカウントキーは不要

### 3. Cloudflare R2認証の設定

R2バケット専用のAPIトークンを作成し、S3互換アクセスキーに変換します。

**参考ドキュメント**:
- [CloudflareのR2バケットに特化したAPIトークンをつくる](https://zenn.dev/hikky_co_ltd/articles/2f97318b5406bf)
- [Cloudflare公式: Get S3 API credentials from an API token](https://developers.cloudflare.com/r2/api/s3/tokens/)

#### 手順1: Account API Tokenの作成
- Cloudflare Dashboard → API Tokens → Create Token
- 権限: `Account.Account Settings:Read`

#### 手順2: Bucket-Specific Tokenの生成
- Account API Tokenを使用してバケット専用トークンを生成
- リソースパス: `com.cloudflare.edge.r2.bucket.{account_id}_default_{bucket_name}`
- 権限: `Workers R2 Storage Bucket Item Read/Write`
- 生成されたトークンには以下の2つの値がある：
  - **Token ID**: そのまま `R2_ACCESS_KEY_ID` として使用
  - **Token Value**: SHA-256ハッシュ化して `R2_SECRET_ACCESS_KEY` として使用

#### 手順3: Token ValueのSHA-256ハッシュ化

**ヘルパースクリプトを使用**（推奨）:

```bash
# Bash/Zshの場合
cd packages/local
./scripts/r2_hash_token.sh

# Pythonの場合
cd packages/local
uv run python scripts/r2_hash_token.py
```

スクリプトを実行すると、Token Valueを入力するプロンプトが表示され、SHA-256ハッシュ化された値が出力されます。

**手動でハッシュ化する場合**:

```bash
# macOS/Linux
echo -n "your-token-value" | shasum -a 256 | awk '{print $1}'

# Python
python -c "import hashlib; print(hashlib.sha256('your-token-value'.encode()).hexdigest())"
```

#### 手順4: 環境変数の設定

`.env` ファイルを作成（`.env.example` を参考）：

```bash
# Google Cloud
GOOGLE_CLOUD_PROJECT=your-project-id
PUBSUB_PROJECT_ID=your-project-id
PUBSUB_SUBSCRIPTION=projects/your-project-id/subscriptions/new-video-trigger

# Gemini API
GEMINI_PROJECT_ID=your-project-id

# Cloudflare R2（バケット専用APIトークン）
R2_ACCESS_KEY_ID=your-token-id                              # Token ID（そのまま）
R2_SECRET_ACCESS_KEY=your-token-value-sha256-hash-lowercase # Token ValueのSHA-256ハッシュ（小文字）
R2_ENDPOINT_URL=your-account-id.r2.cloudflarestorage.com    # {account_id}.r2.cloudflarestorage.com
R2_BUCKET_NAME=sf6-chapter-data                             # バケット名

# Optional
DOWNLOAD_DIR=./downloads
OUTPUT_DIR=./output
LOG_LEVEL=INFO
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
- `https://www.googleapis.com/auth/cloud-platform` - Vertex AI (Gemini API)、Cloud Firestore

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

#### 5. R2アップロードとParquet更新のみ

```bash
# R2アップロードを有効化
ENABLE_R2=true uv run python main.py --mode test --test-step r2 --video-id YFQU_kkhZtg
```

**動作**:
- 保存済みチャプターファイル（`chapters/[video_id]_chapters.json`）があれば、それを使用してR2アップロード・Parquet更新を実行
- 保存済みファイルがない場合は、自動的に検出・認識を実行してからアップロード
- `ENABLE_R2=false` の場合は警告を表示してスキップ

**用途**:
- R2アップロードのみをテストしたい場合
- チャプターデータは確定済みで、R2への再アップロードのみ必要な場合
- Gemini API課金を避けてR2処理をテストしたい場合

#### 6. 全ステップを順次実行

```bash
# R2アップロード無効（デフォルト）
uv run python main.py --mode test --test-step all --video-id YFQU_kkhZtg

# R2アップロード有効
ENABLE_R2=true uv run python main.py --mode test --test-step all --video-id YFQU_kkhZtg
```

**動作**: ダウンロード → 検出 → 認識 → チャプター更新 → **R2アップロード（有効な場合）** を一括実行。既存ファイルがあれば再利用。

**`ENABLE_R2` 環境変数**:
- `true`/`1`/`yes`: R2アップロードとParquet更新を実行
- `false`/`0`/`no`（デフォルト）: R2処理をスキップし、ローカルの `./output/` に保存

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

**パターン1: YouTubeチャプターの調整**
1. 初回実行: `uv run python main.py --mode test --test-step chapters --video-id XXX`
   - チャプターファイルが自動保存される
2. タイトル調整: `chapters/XXX_chapters.json` を手動編集
3. 再実行: `uv run python main.py --mode test --test-step chapters --video-id XXX --use-saved-chapters`
   - Gemini APIを呼ばずに、編集済みチャプターでYouTube更新

**パターン2: R2アップロードのテスト**
1. 初回実行: `ENABLE_R2=true uv run python main.py --mode test --test-step all --video-id XXX`
   - チャプターファイルが自動保存され、R2にもアップロード
2. 再テスト: `ENABLE_R2=true uv run python main.py --mode test --test-step r2 --video-id XXX`
   - **保存済みチャプターファイルを自動的に再利用**
   - 検出・認識をスキップし、R2アップロードのみ実行
   - Gemini API課金を避けてR2処理のみテスト可能

## モジュール構成

```
src/
├── pubsub/          # Pub/Sub受信
│   └── subscriber.py
├── firestore/       # 処理済み動画の追跡
│   └── client.py
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
Firestoreで処理済みチェック
    ↓ (未処理の場合)
Firestoreステータス更新（processing）
    ↓
動画ダウンロード (yt-dlp)
    ↓
テンプレートマッチング (OpenCV)
    ↓
キャラクター認識 (Gemini API)
    ↓
チャプターデータ保存 (./chapters/*.json) ← 中間ファイル（テスト時再利用可能）
    ↓
YouTubeチャプター更新 (YouTube Data API)
    ↓
R2アップロード（ENABLE_R2=trueの場合）
    ├→ JSONファイル: videos/*.json, matches/*.json
    └→ Parquetファイル: videos.parquet, matches.parquet
    ↓
Firestoreステータス更新（completed / failed）
```

**注**:
- `ENABLE_R2=false`（デフォルト）の場合、R2処理はスキップされ、ローカルの `./output/` ディレクトリにJSONファイルが保存されます
- テストモード（`--mode test`）では、チャプターデータが `./chapters/` に保存され、後続のテストで再利用可能
- Firestoreでの処理済みチェックにより、Pub/Subメッセージが再配信されても重複処理を防止します

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

**症状**: `ValueError: R2 credentials must be set`

**解決方法**:
1. `.env` ファイルで以下の環境変数が設定されているか確認：
   - `R2_ACCESS_KEY_ID`: バケット専用APIトークンの**Token ID**（そのまま）
   - `R2_SECRET_ACCESS_KEY`: **Token Value**のSHA-256ハッシュ（小文字）
   - `R2_ENDPOINT_URL`: `{account_id}.r2.cloudflarestorage.com`
   - `R2_BUCKET_NAME`: バケット名（デフォルト: `sf6-chapter-data`）
2. ハッシュ化スクリプトで正しい値を生成：
   ```bash
   ./scripts/r2_hash_token.sh
   # または
   uv run python scripts/r2_hash_token.py
   ```

**症状**: `botocore.exceptions.ClientError: Access Denied`

**解決方法**:
1. トークンの権限を確認（`Workers R2 Storage Bucket Item Read/Write`が必要）
2. `R2_SECRET_ACCESS_KEY`が**Token Value**（生の値ではない）のSHA-256ハッシュ（小文字）になっているか確認
3. エンドポイントURLが正しいか確認（`https://`プレフィックスは不要、自動で追加される）
4. バケット名が正しいか確認

**トークンのテスト方法**:
```bash
# boto3で接続テスト
cd packages/local
uv run python -c "
import boto3
import os

s3 = boto3.client(
    's3',
    endpoint_url=f'https://{os.getenv(\"R2_ENDPOINT_URL\")}',
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
    region_name='auto'
)
print('Connection successful!')
print(s3.list_objects_v2(Bucket=os.getenv('R2_BUCKET_NAME')))
"
```

**注**:
- 環境変数は `.mise.toml` で管理されているため、`dotenv` は不要です
- バケット専用トークンでは `list_buckets()` は権限不足でエラーになります
- `list_objects_v2()` でバケット内のオブジェクト一覧を取得して接続を確認してください

## 認証方式の変更履歴

### v2.0以降（推奨）
- **YouTube API**: OAuth2認証
- **Gemini API**: Vertex AI経由でOAuth2認証（共通トークン）
- **Firestore**: OAuth2認証（共通トークン）
- トークンファイル: `token.pickle`（pickle形式）
- 環境変数 `GEMINI_API_KEY` は不要
- 環境変数 `GOOGLE_CLOUD_PROJECT` が必須

### v1.x（非推奨）
- **YouTube API**: OAuth2認証
- **Gemini API**: API Key認証
- トークンファイル: `token.pickle`（pickle形式）
- 環境変数 `GEMINI_API_KEY` が必要

**後方互換性**: `CharacterRecognizer(use_oauth=False, api_key="...")` で旧方式も使用可能
