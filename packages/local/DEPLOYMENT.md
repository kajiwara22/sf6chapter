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
3. WSL2バックエンドを有効化（必須）

**確認**:
```bash
docker --version
docker compose version
```

> **重要**: Windows環境では、WSL2バックエンドを使用してください。詳細は「[Windows環境での運用（WSL2）](#windows環境での運用wsl2)」セクションを参照してください。

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
PUBSUB_SUBSCRIPTION=projects/your-project-id/subscriptions/new-video-trigger

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

## Windows環境での運用（WSL2）

Windows環境でこのプロジェクトを動かす場合は、**WSL2の使用を強く推奨**します。

### なぜWSL2が必要か

#### 1. 依存関係の互換性

DockerfileではLinux向けに`deno`（yt-dlpのJavaScriptランタイム）をインストールしています。Windows版Docker DesktopはWSL2バックエンドを使用するため、WSL2が必須となります。

#### 2. ボリュームマウントのパフォーマンス

このプロジェクトでは動画ファイル（数GB）を扱うため、I/O性能が重要です。

| マウント元 | パフォーマンス |
|-----------|---------------|
| Windowsファイルシステム（`/mnt/c/...`） | ❌ 遅い |
| WSL2内のファイルシステム（`/home/user/...`） | ✅ 高速 |

WSL2内にリポジトリをクローンすることで、ネイティブに近いI/O性能を得られます。

#### 3. パス形式の互換性

`docker-compose.yml`はUnixパス形式（`./cookie:/app/cookie:ro`）で記述されています。WSL2内で実行すれば、パス変換の問題を回避できます。

### 推奨構成

```
Windows 11
└── WSL2 (Ubuntu)
    ├── リポジトリ: /home/user/sf6-chapter/
    ├── Docker Desktop (WSL2バックエンド)
    └── 認証ファイル・Cookieを配置
        ├── client_secrets.json
        ├── token.pickle
        └── cookie/cookie.txt
```

### セットアップ手順

#### 1. WSL2のインストール

PowerShell（管理者権限）で実行:

```powershell
wsl --install
```

再起動後、Ubuntuが自動的にインストールされます。

#### 2. Docker Desktopの設定

1. Docker Desktopをインストール
2. Settings → General → 「Use the WSL 2 based engine」にチェック
3. Settings → Resources → WSL Integration → Ubuntuを有効化

#### 3. WSL2内でリポジトリをセットアップ

```bash
# WSL2ターミナル（Ubuntu）で実行
cd ~
git clone https://github.com/your-repo/sf6-chapter.git
cd sf6-chapter/packages/local

# 認証ファイルをWindowsからコピー
cp /mnt/c/Users/<username>/Downloads/client_secrets.json ./
mkdir -p cookie
cp /mnt/c/Users/<username>/Downloads/cookie.txt ./cookie/

# .envファイルを設定
cp .env.example .env
nano .env  # 環境変数を編集
```

#### 4. OAuth2認証（token.pickle）

OAuth2認証にはブラウザ操作が必要です。以下の2つの方法があります。

**方法A: 開発PCで認証してからコピー（推奨）**

開発PC（macOS/Linux）で`token.pickle`を生成し、Windows常駐PCにコピーします。

```bash
# 開発PCで実行
cd sf6-chapter/packages/local
uv run python -c "from src.auth.oauth import get_oauth_credentials; get_oauth_credentials()"

# 生成されたtoken.pickleをWindows PCにコピー
scp token.pickle user@windows-pc:/path/to/wsl-home/sf6-chapter/packages/local/
```

**方法B: WSL2からWindowsブラウザを開く**

WSL2から認証URLをWindowsブラウザで開くことも可能です。

```bash
# WSL2内で実行
uv run python -c "from src.auth.oauth import get_oauth_credentials; get_oauth_credentials()"

# 表示された認証URLをコピーし、Windowsブラウザで開く
# または、以下のコマンドでブラウザを直接開く
explorer.exe "https://accounts.google.com/o/oauth2/..."
```

#### 5. Dockerコンテナの起動

```bash
# WSL2内で実行
cd ~/sf6-chapter/packages/local
docker compose build
docker compose up -d

# ログを確認
docker compose logs -f sf6-processor
```

### 注意点

#### ファイル配置場所

| ファイル | 配置場所 | 理由 |
|---------|---------|------|
| リポジトリ | `/home/user/sf6-chapter/` | I/O性能のため |
| 認証ファイル | WSL2内にコピー | パス互換性のため |
| ダウンロード動画 | Dockerボリューム | 永続化・パフォーマンス |

> **注意**: `/mnt/c/...`（Windowsドライブ）にリポジトリを置くと、ファイルI/Oが遅くなります。必ずWSL2内のファイルシステム（`/home/user/...`）を使用してください。

#### WSL2のメモリ制限

WSL2はデフォルトでホストメモリの50%または8GBまで使用します。動画処理には十分ですが、必要に応じて制限を調整できます。

`%USERPROFILE%\.wslconfig`を作成:

```ini
[wsl2]
memory=4GB
processors=2
```

設定後、WSL2を再起動:

```powershell
wsl --shutdown
```

#### PC起動時の自動起動

Windows起動時にDockerコンテナを自動起動するには:

1. Docker Desktopの設定で「Start Docker Desktop when you log in」を有効化
2. `docker-compose.yml`の`restart: unless-stopped`により、Docker起動時にコンテナも自動起動

## 参考資料

- [Docker公式ドキュメント](https://docs.docker.com/)
- [Docker Compose公式ドキュメント](https://docs.docker.com/compose/)
- [WSL公式ドキュメント](https://docs.microsoft.com/ja-jp/windows/wsl/)
- [ADR-013: ローカル処理パッケージのDocker化](../../docs/adr/013-local-package-dockerization.md)
- [SF6 Chapter README](./README.md)
