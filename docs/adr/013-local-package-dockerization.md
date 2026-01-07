# ADR-013: ローカル処理パッケージのDocker化

## ステータス

採用 (2026-01-07)

## コンテキスト

`packages/local`は現在、開発PCでuvを使用して実行されています。しかし、常駐用の別PCに展開する際、以下の課題がありました：

### 現在の環境構築の手間

1. **複雑な依存関係**
   - Python 3.11+とuv
   - システムレベルのライブラリ（OpenCV、ffmpeg）
   - JavaScriptランタイム（Deno/Node.js/Bun）
   - yt-dlpの設定ファイル
   - テンプレート画像ファイル

2. **認証ファイルの管理**
   - OAuth2クライアントシークレット（`client_secrets.json`）
   - 認証トークン（`token.pickle`）
   - 環境変数（15+個）

3. **OS依存性**
   - macOS/Linux/Windowsで手順が異なる
   - システムパッケージマネージャーの違い（Homebrew、apt、choco）
   - パスの違い（`~/.config`、`%APPDATA%`等）

4. **運用上の懸念**
   - 自動起動の設定（systemd、launchd、タスクスケジューラー）
   - ログ管理の統一
   - プロセス監視とヘルスチェック
   - リソース制限の設定

### 検討した代替案

#### 1. uv + セットアップスクリプト

**メリット**:
- ネイティブ実行で軽量
- デバッグが容易
- Dockerのオーバーヘッドなし

**デメリット**:
- OS依存性が高い（Windows対応が困難）
- 環境構築が手動で煩雑
- バージョン管理が困難
- systemd等の自動起動設定が必要

#### 2. Google Cloud Run Jobs

**メリット**:
- フルマネージド
- スケーラブル
- サーバー管理不要

**デメリット**:
- クラウド費用が発生（動画DL・処理が重い）
- Pub/Subからのプル処理が非効率
- ローカルPCで処理するコスト$0のメリットを失う
- デバッグが困難

#### 3. Docker + Docker Compose（採用案）

**メリット**:
- 環境再現性が完璧
- `docker-compose up -d`だけで起動
- OS非依存（Windows/macOS/Linux対応）
- 開発環境でも同じDockerfileを使用可能（volumesマウント）
- ログ管理・自動再起動・ヘルスチェックが標準装備
- リソース制限が容易
- 本番運用実績が豊富

**デメリット**:
- Dockerのインストールが必要
- イメージサイズ: 1-2GB程度
- 初回ビルドで時間がかかる（5-10分程度）

## 決定事項

**Docker + Docker Composeを採用**します。

### 構成

#### 1. Dockerfile

**ベースイメージ**: `python:3.11-slim`

**システム依存のインストール**:
- OpenCV依存: `libgl1-mesa-glx`, `libglib2.0-0`
- yt-dlp依存: `ffmpeg`
- Deno（JSランタイム）: 公式インストールスクリプト

**Python依存のインストール**:
- uvを使用（`ghcr.io/astral-sh/uv:latest`からコピー）
- `uv sync --frozen --no-dev`で高速インストール

**設定ファイル**:
- yt-dlp設定（`~/.config/yt-dlp/config`）でDenoパスを指定

**実行コマンド**:
```bash
uv run python -m src.main --mode daemon
```

#### 2. Docker Compose

**サービス定義**: `sf6-processor`

**ボリュームマウント**:
- 認証ファイル: `client_secrets.json`, `token.pickle`
- テンプレート画像: `template/`
- データ永続化: `downloads/`, `output/`, `intermediate/`, `chapters/`

**環境変数**: `.env`ファイルから読み込み

**ヘルスチェック**: Pythonプロセスの存在確認（60秒間隔）

**再起動ポリシー**: `unless-stopped`（手動停止以外は自動再起動）

#### 3. .dockerignore

不要なファイルをイメージから除外:
- `downloads/`, `output/`, `chapters/`, `intermediate/`（データディレクトリ）
- `*.pickle`, `*.json`（認証ファイル、volumesでマウント）
- `__pycache__/`, `.pytest_cache/`（Pythonキャッシュ）
- `.venv/`, `.uv/`（ローカル開発用）

### デプロイフロー

#### 開発PC

```bash
# 開発時は通常通りuvで実行
uv run python main.py --mode daemon

# またはDockerで実行（volumesマウントで開発ファイルを使用）
docker-compose up
```

#### 常駐PC（初回セットアップ）

```bash
# 1. リポジトリをクローン
git clone https://github.com/your-repo/sf6-chapter.git
cd sf6-chapter

# 2. 認証ファイルを配置
cp /path/to/client_secrets.json packages/local/
cp /path/to/token.pickle packages/local/

# 3. 環境変数を設定
cp packages/local/.env.example packages/local/.env
vi packages/local/.env  # 必要な値を編集

# 4. 起動
docker-compose up -d

# 5. ログ確認
docker-compose logs -f sf6-processor
```

#### 更新時

```bash
# Gitで最新コードを取得
git pull

# イメージを再ビルドして再起動
docker-compose up -d --build
```

### セキュリティ考慮事項

1. **認証ファイルの保護**
   - `client_secrets.json`: `:ro`（読み取り専用）でマウント
   - `token.pickle`: 書き込み可能だが、ホスト側で適切なパーミッション設定（600）

2. **環境変数の管理**
   - `.env`ファイルに機密情報を集約
   - `.env`は`.gitignore`に追加済み
   - `.env.example`でテンプレートを提供

3. **ネットワーク分離**
   - デフォルトのbridgeネットワークを使用
   - 外部からのアクセスは不要（Pub/Subからプル）

4. **リソース制限**（オプション）
   - `deploy.resources.limits`でメモリ・CPU制限可能
   - 暴走時の影響を最小化

## 結果

### メリット

1. **環境構築の簡素化**: `docker-compose up -d`だけで起動
2. **ポータビリティ**: どのPCでも同じ動作を保証（Windows/macOS/Linux）
3. **運用の容易さ**: ログ管理、自動再起動、ヘルスチェックが標準装備
4. **開発との両立**: volumesマウントで開発時も同じDockerfileを使用可能
5. **リソース管理**: メモリ・CPU制限が容易
6. **再現性**: Dockerfileでバージョン固定、環境の一貫性を保証

### デメリットと対策

1. **イメージサイズ（1-2GB）**
   - 対策: Multi-stage buildは不要（実行時にソースコードが必要なため）
   - 許容範囲: ディスク容量は現代のPCでは問題にならない

2. **初回ビルド時間（5-10分）**
   - 対策: 初回のみの手間、更新時はキャッシュが効く
   - 許容範囲: セットアップは1度だけ

3. **Dockerのインストールが必要**
   - 対策: Docker Desktopは無料で簡単にインストール可能
   - 許容範囲: 業界標準ツールであり、学習コストは低い

## 参考資料

- [Docker公式ドキュメント](https://docs.docker.com/)
- [Docker Compose公式ドキュメント](https://docs.docker.com/compose/)
- [uv公式ドキュメント](https://docs.astral.sh/uv/)
- [yt-dlp EJS Setup Guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
