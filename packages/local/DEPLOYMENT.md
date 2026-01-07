# SF6 Chapter - Docker デプロイ手順書

## 概要

このドキュメントは、SF6 Chapter ローカル処理パッケージをDocker環境で常駐させるための手順書です。

## 前提条件

### 必須環境

- Docker Engine 20.10以上
- Docker Compose 2.0以上

### インストール方法

#### macOS

```bash
# Homebrewでインストール
brew install --cask docker

# Docker Desktopを起動
open -a Docker
```

#### Linux (Ubuntu/Debian)

```bash
# Docker公式スクリプトでインストール
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 現在のユーザーをdockerグループに追加（sudoなしで実行可能）
sudo usermod -aG docker $USER
newgrp docker

# Docker Composeインストール
sudo apt-get update
sudo apt-get install docker-compose-plugin
```

#### Windows

1. [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop)をダウンロード
2. インストーラーを実行
3. WSL2バックエンドを有効化（推奨）

**確認**:
```bash
docker --version
docker compose version
```

## セットアップ手順

### 1. リポジトリのクローン

```bash
git clone https://github.com/your-repo/sf6-chapter.git
cd sf6-chapter/packages/local
```

### 2. 認証ファイルの配置

#### OAuth2認証ファイル

Google Cloud Consoleで取得した認証ファイルを配置します。

```bash
# client_secrets.jsonをコピー
cp /path/to/client_secrets.json .

# token.pickleをコピー（初回認証済みの場合）
cp /path/to/token.pickle .
```

**初回認証が必要な場合**:

開発PCで初回OAuth2認証を実行し、`token.pickle`を生成してから常駐PCにコピーしてください。

```bash
# 開発PC上で実行
uv run python -c "from src.auth.oauth import get_oauth_credentials; get_oauth_credentials()"

# 生成されたtoken.pickleを常駐PCにコピー
scp token.pickle user@deployment-pc:/path/to/sf6-chapter/packages/local/
```

#### テンプレート画像

「ROUND 1」検出用のテンプレート画像を配置します。

```bash
# templateディレクトリを作成
mkdir -p template

# テンプレート画像をコピー
cp /path/to/round1.png template/
```

### 3. 環境変数の設定

`.env.example`をコピーして`.env`を作成します。

```bash
cp .env.example .env
```

`.env`ファイルを編集し、必要な値を設定します。

```bash
vi .env  # またはお好みのエディタで編集
```

**必須項目**:

```bash
# Google Cloud プロジェクト
GOOGLE_CLOUD_PROJECT=your-project-id
PUBSUB_PROJECT_ID=your-project-id
PUBSUB_SUBSCRIPTION=projects/your-project-id/subscriptions/new-video-trigger

# YouTube チャンネル設定
YOUTUBE_CHANNEL_ID=your-channel-id

# Gemini API
GEMINI_PROJECT_ID=your-project-id
GEMINI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.0-flash-exp

# Cloudflare R2 設定
R2_ACCESS_KEY_ID=your-token-id
R2_SECRET_ACCESS_KEY=your-token-value-sha256-hash-lowercase
R2_ENDPOINT_URL=your-account-id.r2.cloudflarestorage.com
R2_BUCKET_NAME=sf6-chapter-data
```

**オプション項目**:

```bash
# ディレクトリ設定（デフォルトで問題なければ変更不要）
DOWNLOAD_DIR=./downloads
OUTPUT_DIR=./output
INTERMEDIATE_DIR=./intermediate

# ログレベル
LOG_LEVEL=INFO

# R2アップロード有効化（trueで有効）
ENABLE_R2=true
```

### 4. ファイル構成の確認

以下のファイルが揃っていることを確認してください。

```
packages/local/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── pyproject.toml
├── uv.lock
├── src/
├── config/
├── template/
│   └── round1.png
├── client_secrets.json
├── token.pickle
└── .env
```

### 5. Dockerイメージのビルド

```bash
docker compose build
```

**所要時間**: 初回は5-10分程度（依存関係のダウンロード・インストール）

### 6. コンテナの起動

```bash
docker compose up -d
```

**`-d`オプション**: バックグラウンドで実行（デタッチドモード）

### 7. 動作確認

#### ログの確認

```bash
# リアルタイムでログを表示（Ctrl+Cで終了）
docker compose logs -f sf6-processor

# 最新100行を表示
docker compose logs --tail=100 sf6-processor
```

#### コンテナのステータス確認

```bash
docker compose ps
```

正常に起動していれば、`STATE`列に`Up`と表示されます。

#### ヘルスチェックの確認

```bash
docker inspect --format='{{.State.Health.Status}}' sf6-chapter-processor
```

`healthy`と表示されればOKです。

## 運用

### コンテナの停止

```bash
docker compose down
```

### コンテナの再起動

```bash
docker compose restart
```

### コンテナの完全削除（ボリュームも削除）

```bash
docker compose down -v
```

**注意**: `-v`オプションを使用すると、ダウンロードした動画やチャプターデータも削除されます。

### コードの更新

リポジトリが更新された場合、以下の手順で最新版に更新します。

```bash
# 最新コードを取得
git pull

# イメージを再ビルドして再起動
docker compose up -d --build
```

### 環境変数の変更

`.env`ファイルを編集後、コンテナを再起動します。

```bash
vi .env
docker compose restart
```

### データのバックアップ

#### 認証ファイルのバックアップ

```bash
cp client_secrets.json /path/to/backup/
cp token.pickle /path/to/backup/
```

#### Dockerボリュームのバックアップ

```bash
# ボリュームの一覧確認
docker volume ls | grep sf6-chapter

# ボリュームのバックアップ（例: downloadsボリューム）
docker run --rm -v sf6-chapter-downloads:/source -v $(pwd)/backup:/backup alpine tar -czf /backup/downloads.tar.gz -C /source .
```

## トラブルシューティング

### コンテナが起動しない

#### 原因1: 認証ファイルが見つからない

**症状**:
```
Error: FileNotFoundError: client_secrets.json not found
```

**解決方法**:
```bash
# ファイルの存在確認
ls -la client_secrets.json token.pickle

# ファイルが存在しない場合は配置
cp /path/to/client_secrets.json .
cp /path/to/token.pickle .
```

#### 原因2: 環境変数が設定されていない

**症状**:
```
Error: GOOGLE_CLOUD_PROJECT is not set
```

**解決方法**:
```bash
# .envファイルを確認
cat .env

# 必要な環境変数が設定されているか確認
grep GOOGLE_CLOUD_PROJECT .env
```

#### 原因3: ポート競合

**症状**:
```
Error: port is already allocated
```

**解決方法**:

このアプリケーションは外部ポートを使用しないため、通常この問題は発生しません。

### ログにエラーが表示される

#### Pub/Sub接続エラー

**症状**:
```
google.api_core.exceptions.PermissionDenied: 403 Permission denied
```

**解決方法**:

1. OAuth2トークンが有効か確認
2. Google Cloud ProjectでPub/Sub APIが有効化されているか確認
3. サービスアカウントに適切な権限があるか確認

#### yt-dlpダウンロードエラー

**症状**:
```
ERROR: Unable to download webpage
```

**解決方法**:

1. Denoが正しくインストールされているか確認:
   ```bash
   docker compose exec sf6-processor deno --version
   ```

2. yt-dlpの設定ファイルを確認:
   ```bash
   docker compose exec sf6-processor cat /root/.config/yt-dlp/config
   ```

3. 必要に応じてyt-dlpを最新版に更新（Dockerfileを修正して再ビルド）

#### Gemini APIレート制限

**症状**:
```
google.api_core.exceptions.ResourceExhausted: 429 Quota exceeded
```

**解決方法**:

Gemini APIの無料枠は15 RPM（Requests Per Minute）です。処理は自動的にスキップされ、次の動画で継続します。

### リソース使用量が高い

#### メモリ使用量の確認

```bash
docker stats sf6-chapter-processor
```

#### リソース制限の設定

`docker-compose.yml`のコメントアウトされた`deploy.resources`セクションを有効化します。

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 4G
    reservations:
      cpus: '0.5'
      memory: 1G
```

編集後、コンテナを再起動:
```bash
docker compose up -d --force-recreate
```

## セキュリティ

### 認証ファイルの保護

```bash
# 認証ファイルのパーミッションを制限
chmod 600 client_secrets.json token.pickle

# .envファイルのパーミッションを制限
chmod 600 .env
```

### Dockerソケットのアクセス制限

Dockerソケット（`/var/run/docker.sock`）へのアクセスを制限することで、コンテナからのDocker操作を防ぎます。

このアプリケーションではDockerソケットをマウントしていないため、デフォルトで安全です。

## 参考資料

- [Docker公式ドキュメント](https://docs.docker.com/)
- [Docker Compose公式ドキュメント](https://docs.docker.com/compose/)
- [ADR-013: ローカル処理パッケージのDocker化](../../docs/adr/013-local-package-dockerization.md)
- [SF6 Chapter README](./README.md)
