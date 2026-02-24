# OBS Title Updater

OBS (Open Broadcaster Software) 配信開始イベント連動で、YouTube動画タイトルのプレースホルダーを自動置き換えするPythonスクリプトです。

## 機能

配信開始時にOBSスクリプト経由で実行され、以下の処理を行います：

1. YouTube Data APIから自分の最新動画を取得
2. タイトルに `{DateTime}` プレースホルダーを含む動画を検索
3. 動画の公開日時（UTC）をJST準拠の `YYYY/MM/DD` 形式に変換
4. タイトル内の `{DateTime}` を日付に置き換え
5. YouTube Data APIでタイトルを更新

### 置き換え例

| 置き換え前 | 置き換え後 |
|----------|---------|
| `スト６ランクマ {DateTime}` | `スト６ランクマ 26/02/25` |

## セットアップ

### 1. 環境構築

```bash
cd packages/obs-title-updater
uv sync
```

または、依存関係をインストール：

```bash
pip install -e .
```

### 2. Google Cloud認証の設定

OBS Title Updaterはgoogle-auth-oauthlibを使用して、ブラウザベースのOAuth2認証を行います。

#### 手順

1. [Google Cloud Console](https://console.cloud.google.com/)にアクセス
2. 認証情報ページ（API & Services → Credentials）に移動
3. 「Create OAuth 2.0 Client ID」から**デスクトップアプリ**を選択
4. ダウンロードしたJSONファイルを `client_secrets.json` として保存：

```bash
mv ~/Downloads/client_secrets.json packages/obs-title-updater/client_secrets.json
```

5. YouTube Data APIをプロジェクトで有効化

**詳細**: [ADR-004: OAuth2認証の統一](../../docs/adr/004-oauth2-authentication-for-all-gcp-apis.md)

## 使用方法

### スタンドアロン実行

```bash
cd packages/obs-title-updater
uv run python src/main.py
```

### OBSスクリプトからの呼び出し

OBS Pythonスクリプトから `subprocess.Popen()` で非同期実行：

```python
import subprocess
import os

def on_event(event):
    if event == obs.OBS_FRONTEND_EVENT_STREAMING_STARTED:
        script_path = "/path/to/obs_title_updater.py"
        try:
            # 非同期実行（配信に影響しないようにする）
            subprocess.Popen(["/usr/bin/python3", script_path])
            print("OBS配信開始: obs_title_updater.py を実行しました")
        except Exception as e:
            print(f"OBS配信開始スクリプト実行エラー: {e}")
    elif event == obs.OBS_FRONTEND_EVENT_STREAMING_STOPPED:
        print("OBS配信停止")
```

### カスタムパス指定

```bash
uv run python src/main.py --token-path /path/to/token.pickle --client-secrets-path /path/to/client_secrets.json
```

### コマンドラインオプション

スクリプト内で `main()` 関数のパラメータで指定：

```python
from src.main import main

exit_code = main(
    token_path="/custom/path/token.pickle",
    client_secrets_path="/custom/path/client_secrets.json",
    search_limit=50
)
```

## 動作の流れ

```
配信開始イベント（OBS_FRONTEND_EVENT_STREAMING_STARTED）
    ↓
subprocess.Popen() で obs_title_updater.py を非同期実行
    ↓
OAuth2認証（token.pickle または browser-based flow）
    ↓
YouTube API search.list() で最新50件の動画を検索
    ↓
{DateTime} プレースホルダーを含む最初の動画を検出
    ↓
publishedAt (UTC) → JST YY/MM/DD 形式に変換
    ↓
YouTube API videos.update() でタイトルを更新
    ↓
ログに記録して終了（exit code 0: 成功、1: 失敗）
```

## ログ出力

スクリプト実行時にログが標準出力に出力されます：

```
2026-02-25 10:30:00,123 - __main__ - INFO - YouTube API client initialized
2026-02-25 10:30:01,456 - __main__ - INFO - Found video with placeholder: dQw4w9WgXcQ - 'スト６ランクマ {DateTime}'
2026-02-25 10:30:01,789 - __main__ - INFO - Replacing title: 'スト６ランクマ {DateTime}' → 'スト６ランクマ 26/02/25'
2026-02-25 10:30:02,123 - __main__ - INFO - Successfully updated video dQw4w9WgXcQ title to 'スト６ランクマ 26/02/25'
2026-02-25 10:30:02,456 - __main__ - INFO - Title update completed successfully
```

## エラーハンドリング

### YouTubeAPI エラー

- `HttpError` → ログに記録、exit code 1で終了
- 認証情報がない場合 → browser-based OAuth2 flowを起動

### 一般的なエラー

| エラー | 対応 |
|-------|------|
| `FileNotFoundError: client_secrets.json` | client_secrets.jsonをセットアップ手順に従い配置 |
| `No videos found in account` | YouTubeにアップロード済み動画がない、またはAPI quota超過 |
| `No video with {DateTime} placeholder found` | 「タイトルに `{DateTime}` を含む新しい動画を作成してください |
| API quota error | 24時間で YouTube Data API の quota に達した |

## 認証情報の永続化

初回実行時にブラウザが開きOAuth2認証を求められます。認証成功後、トークンは `token.pickle` に保存されます。

- **トークン保存先**: `token.pickle` （同じディレクトリ）
- **有効期限**: Google OAuth2の仕様に依存（通常は1時間、リフレッシュトークンで自動更新）
- **トークンリセット**: `token.pickle` を削除して再実行

## 実装仕様

### 関数一覧

| 関数 | 説明 |
|------|------|
| `get_latest_video_with_placeholder()` | 最新動画から {DateTime} プレースホルダー含むものを検索 |
| `convert_published_at_to_jst_date()` | UTC → JST YYYY/MM/DD 形式に変換 |
| `replace_placeholder_in_title()` | タイトル内のプレースホルダーを置き換え |
| `update_video_title()` | YouTube API でタイトルを更新 |
| `main()` | メイン処理 |

### 検索範囲

デフォルトでは最新50件の動画を検索します。より多くを検索する場合は `search_limit` パラメータを増やしてください。

## 関連ADR

- [ADR-028: OBS ストリーミングイベント連動のYouTube動画タイトル更新](../../docs/adr/028-obs-streaming-event-driven-title-update.md)
- [ADR-004: OAuth2認証の統一](../../docs/adr/004-oauth2-authentication-for-all-gcp-apis.md)
- [ADR-027: PS5 自動アップロード動画のタイトル自動書き換え](../../docs/adr/027-ps5-auto-title-rename.md)

## トラブルシューティング

### Q: 何度実行しても認証画面が出る

**A**: `token.pickle` が正しく保存されていない可能性があります。

1. ディレクトリの書き込み権限を確認
2. `token.pickle` が存在するか確認
3. 必要に応じて削除して再実行

### Q: YouTube API エラーが出る

**A**: API quota を超過している可能性があります。

- 24時間のクォータは無料アカウントで10,000ユニット/日
- `search.list()` は100ユニット、`videos.update()` は50ユニット消費
- 翌日を待つか、quotaを増やしてください

### Q: OBSから実行されない

**A**: Pythonインタプリタのパスを確認してください。

```python
subprocess.Popen(["/usr/bin/python3", "/full/path/to/obs_title_updater.py"])
```

Windows環境の場合：

```python
subprocess.Popen(["python.exe", "C:\\full\\path\\to\\obs_title_updater.py"])
```

## 将来の改善

1. **複数プレースホルダー対応**: `{DateTime}`、`{Time}`、`{DayOfWeek}` など
2. **スクリプト統合化**: `packages/local` の共通モジュール化
3. **キャッシング機構**: 重複実行防止
4. **配信停止時の処理**: `OBS_FRONTEND_EVENT_STREAMING_STOPPED` での拡張

## ライセンス

このプロジェクトの一部です。詳細はプロジェクトルートの LICENSE を参照してください。
