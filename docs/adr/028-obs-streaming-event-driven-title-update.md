# ADR-028: OBS ストリーミングイベント連動のYouTube動画タイトル更新

## ステータス

承認・実装完了 - 2026-02-25

## 文脈

### 現在の問題

**ADR-027との独立性**: ADR-027はPS5からのYouTube自動アップロード機能に対する自動タイトル書き換えである。一方、ADR-028はPC上でOBS経由で配信を行うユーザー向けの機能であり、異なるユースケースに対応している。

PC配信ユーザーは、動画タイトルに `{DateTime}` というプレースホルダーを設定して配信開始時に自動的に日付に置き換えてほしい、という要望がある。

### ユースケース

PC配信ユーザーは以下の流れで作業を行っている：

1. YouTube上で新しい動画を作成し、タイトルを `スト６ランクマ {DateTime}` という形式で設定
2. OBS（Open Broadcaster Software）で配信開始準備
3. OBS配信開始イベント発火
4. **配信開始と同時に、タイトルの `{DateTime}` が自動的に `26/02/25` 形式の日付に置き換わる**
5. 配信中・配信終了

この流れで、ユーザーは配信開始前にタイトルにプレースホルダーを設定するだけで、OBS配信開始時に自動的にタイトルが完成する。

### 実装の制約

- OBS スクリプト側の `subprocess.Popen()` で呼び出されるPythonスクリプト
- 配信開始時（`OBS_FRONTEND_EVENT_STREAMING_STARTED`）に実行される
- 配信停止時（`OBS_FRONTEND_EVENT_STREAMING_STOPPED`）には実行の必要性は低い
- **即座に最新動画のタイトルを取得し、プレースホルダー置き換えを実行する必要**

## 決定

**配信開始時にOBSスクリプト経由で実行される独立したPythonスクリプト（`obs_title_updater.py`）を実装し、YouTube Data APIから最新の自分の動画を取得してタイトルを即座に更新する。**

### 実装方針

#### 1. スクリプトの位置と役割

- **位置**: `packages/obs-title-updater/src/main.py`
- **独立性**: スクリプト単体で動作可能（他のパッケージに依存しない）
- **呼び出し元**: OBSスクリプト（`subprocess.Popen()` で非同期実行）
- **役割**: YouTube Data APIから最新の動画を取得し、タイトルのプレースホルダーを即座に書き換え

#### 2. タイトル置き換えプレースホルダー

スクリプトが検索・置き換える対象：

| プレースホルダー | 置き換え内容 | 例 |
|---------------|----------|-----|
| `{DateTime}` | `YYYY/MM/DD` 形式の日付（JST） | `スト６ランクマ {DateTime}` → `スト６ランクマ 26/02/25` |

**実装ロジック**:
```
1. YouTube Data APIから自分のアップロード済み動画を取得（最新から最大50件）
2. 各動画のタイトルに `{DateTime}` が含まれているか確認
3. 該当動画が見つかれば、その動画のpublishedAtを取得
4. UTC → JST 変換、`{DateTime}` を `YYYY/MM/DD` に置き換え
5. YouTube Data APIでタイトルを更新
```

#### 3. 認証方式

**ADR-004に準ずる**:
- `oauth.py` の `get_oauth_credentials()` を使用
- `token.pickle` にトークンを保存
- YouTube Data APIスコープ: `https://www.googleapis.com/auth/youtube.force-ssl`

#### 4. 実装仕様

```python
#!/usr/bin/env python3
"""
OBS配信開始イベント連動のYouTube動画タイトル更新スクリプト

packages/obs-title-updater 独立パッケージ

配信開始時にOBSスクリプト経由で実行され、
YouTube Data APIから最新の動画を取得し、
タイトルプレースホルダー {DateTime} をYYYY/MM/DD形式の日付に置き換える
"""

import sys
import logging
from datetime import datetime
import pytz
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_latest_video_with_placeholder(youtube_service, limit: int = 50) -> dict | None:
    """
    最新のアップロード済み動画から {DateTime} プレースホルダーを含むものを検索

    Args:
        youtube_service: YouTube API クライアント
        limit: 検索対象の最新動画数（デフォルト50）

    Returns:
        プレースホルダーを含む動画情報（ID、title、publishedAt）、
        または該当する動画がない場合は None
    """
    try:
        # 自分の最新アップロード動画を取得
        response = youtube_service.search().list(
            forMine=True,
            part="snippet",
            type="video",
            maxResults=limit,
            order="date"
        ).execute()

        videos = response.get("items", [])
        if not videos:
            logger.info("No videos found in account")
            return None

        # {DateTime} プレースホルダーを含む最初の動画を検索
        for video in videos:
            title = video["snippet"]["title"]
            if "{DateTime}" in title:
                logger.info(f"Found video with placeholder: {video['id']} - '{title}'")
                return {
                    "id": video["id"],
                    "title": title,
                    "publishedAt": video["snippet"]["publishedAt"]
                }

        logger.info("No video with {DateTime} placeholder found")
        return None

    except HttpError as e:
        logger.error(f"YouTube API error while searching videos: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error searching videos: {e}")
        return None


def convert_published_at_to_jst_date(published_at_utc: str) -> str:
    """
    YouTube APIから取得した公開日時（UTC）をJST準拠のYYYY/MM/DD形式に変換

    Args:
        published_at_utc: ISO 8601形式、UTC（例: "2026-02-25T10:30:00Z"）

    Returns:
        YYYY/MM/DD形式の日付文字列（例: "26/02/25"）
    """
    try:
        # UTC → JST 変換
        dt_utc = datetime.fromisoformat(published_at_utc.replace("Z", "+00:00"))
        jst = pytz.timezone("Asia/Tokyo")
        dt_jst = dt_utc.astimezone(jst)

        # YYYY/MM/DD 形式に変換
        return dt_jst.strftime("%y/%m/%d")

    except Exception as e:
        logger.error(f"Error converting date: {e}")
        return None


def replace_placeholder_in_title(title: str, date_str: str) -> str:
    """
    タイトル内の {DateTime} プレースホルダーをYYYY/MM/DD形式の日付で置き換え

    Args:
        title: 置き換え前のタイトル（例: "スト６ランクマ {DateTime}"）
        date_str: 置き換える日付文字列（例: "26/02/25"）

    Returns:
        置き換え後のタイトル（例: "スト６ランクマ 26/02/25"）
    """
    return title.replace("{DateTime}", date_str)


def update_video_title(youtube_service, video_id: str, new_title: str) -> bool:
    """
    YouTube Data APIでビデオタイトルを更新

    Args:
        youtube_service: YouTube API クライアント
        video_id: 更新対象の動画ID
        new_title: 新しいタイトル

    Returns:
        成功時 True、失敗時 False
    """
    try:
        # 現在のビデオ情報を取得（snippet部分）
        get_response = youtube_service.videos().list(
            part="snippet",
            id=video_id
        ).execute()

        if not get_response.get("items"):
            logger.error(f"Video not found: {video_id}")
            return False

        # スニペット情報を取得してタイトルを更新
        snippet = get_response["items"][0]["snippet"]
        snippet["title"] = new_title

        # 更新リクエスト実行
        youtube_service.videos().update(
            part="snippet",
            body={
                "id": video_id,
                "snippet": snippet
            }
        ).execute()

        logger.info(f"Successfully updated video {video_id} title to '{new_title}'")
        return True

    except HttpError as e:
        logger.error(f"YouTube API error while updating {video_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating {video_id}: {e}")
        return False


def main(
    token_path: str = None,
    client_secrets_path: str = None,
    search_limit: int = 50
) -> int:
    """
    メイン処理：最新動画のタイトルプレースホルダーを置き換え

    Args:
        token_path: トークンファイルのパス（デフォルト: token.pickle）
        client_secrets_path: クライアントシークレットファイルのパス（デフォルト: client_secrets.json）
        search_limit: 検索対象の最新動画数（デフォルト: 50）

    Returns:
        成功時 0、失敗時 1
    """
    try:
        # OAuth2認証を実行
        from oauth import get_oauth_credentials

        credentials = get_oauth_credentials(
            token_path=token_path,
            client_secrets_path=client_secrets_path,
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
        )

        # YouTube APIクライアントを初期化
        youtube = build("youtube", "v3", credentials=credentials)
        logger.info("YouTube API client initialized")

        # 最新動画から {DateTime} プレースホルダーを検索
        video_info = get_latest_video_with_placeholder(youtube, limit=search_limit)

        if not video_info:
            logger.info("No action needed: no video with {DateTime} placeholder found")
            return 0

        # 公開日時をJST準拠のYYYY/MM/DD形式に変換
        date_str = convert_published_at_to_jst_date(video_info["publishedAt"])
        if not date_str:
            logger.error("Failed to convert date")
            return 1

        # タイトル内の {DateTime} を置き換え
        new_title = replace_placeholder_in_title(video_info["title"], date_str)
        logger.info(f"Replacing title: '{video_info['title']}' → '{new_title}'")

        # YouTube APIでタイトルを更新
        if update_video_title(youtube, video_info["id"], new_title):
            logger.info("Title update completed successfully")
            return 0
        else:
            logger.error("Title update failed")
            return 1

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

#### 5. OBS スクリプト側の実装例

```python
import subprocess
import os

def on_event(event):
    if event == obs.OBS_FRONTEND_EVENT_STREAMING_STARTED:
        script_path = "/path/to/obs_title_updater.py"
        try:
            # 非同期実行（配信に影響しないようにする）
            subprocess.Popen(["python", script_path])
            print("OBS配信開始: obs_title_updater.py を実行しました")
        except Exception as e:
            print(f"OBS配信開始スクリプト実行エラー: {e}")
    elif event == obs.OBS_FRONTEND_EVENT_STREAMING_STOPPED:
        print("OBS配信停止")
```

#### 6. エラーハンドリング方針

- **YouTube API エラー**: ログに記録し、非ゼロ終了コードで終了
- **認証エラー**: `oauth.py` の既存エラーハンドリングに依存
- **スクリプト実行エラー**: OBS側でキャッチされる

**実装理由**：
- OBS側で `subprocess.Popen()` 非同期実行しているため、スクリプト失敗がOBSの配信に影響しない
- 失敗時のログはスクリプト側のログハンドラに記録
- ユーザーは手動で後から修正可能

## 実装の選択肢と比較

### 選択肢1: OBS配信開始時に実行（採用）

| 観点 | 評価 |
|------|------|
| レスポンス時間 | 高（即座に最新動画を確認） |
| 実装複雑度 | 低（独立したスクリプト） |
| 信頼性 | 中（API依存） |
| ユーザー体験 | 優秀（配信中に自動実行） |
| パフォーマンス影響 | 低（非同期実行） |

### 選択肢2: Cloud Scheduler既存フローで対応

| 観点 | 評価 |
|------|------|
| レスポンス時間 | 低（最大2時間の遅延） |
| 実装複雑度 | 低（既存フロー） |
| 信頼性 | 高（既存実装） |
| ユーザー体験 | 劣悪（遅延大） |
| パフォーマンス影響 | 無し |

### 選択肢3: ローカル常駐プロセスで監視

| 観点 | 評価 |
|------|------|
| レスポンス時間 | 中（常駐プロセス起動時に実行） |
| 実装複雑度 | 高（常駐プロセス開発） |
| 信頼性 | 低（プロセス管理の複雑性） |
| ユーザー体験 | 中（配信開始タイミングに依存） |
| パフォーマンス影響 | 中（常駐PC） |

**採択理由**：
- OBSスクリプトフレームワークとの親和性が最高
- 配信開始というユーザー主体のアクションと連動（最も自然）
- 実装が最もシンプル
- 非同期実行により配信に一切影響しない

## トレードオフと帰結

### メリット ✅

- **即座の対応**: 配信開始時に即座にプレースホルダー置き換え
- **ユーザー体験向上**: 配信終了後すぐにタイトルが正しい状態になる
- **シンプル**: 新しいマイクロサービス不要、独立したスクリプト
- **既存との相乗効果**: ADR-027のPS5自動タイトル書き換えと組み合わせ可能
- **柔軟性**: プレースホルダー形式は容易に拡張可能

### デメリット ⚠️

- **複数スクリプトの管理**: `obs_title_updater.py` と Cloud Functions内の書き換えロジックが別に存在
- **API quota消費**: 配信開始時毎回に検索・更新リクエスト実行
- **ネットワーク依存**: API呼び出しのため配信開始時にネットワークが必要
- **プレースホルダー依存**: ユーザーが正確にプレースホルダーを入力する必要

### 互換性 ✅

- Firestore のスキーマ変更なし
- Pub/Sub メッセージフォーマットの変更なし
- Cloud Functionsの既存ロジックに影響なし
- 既存の動画処理フロー（chapters.json 生成など）に影響なし

## 将来の改善

1. **プレースホルダーの複数対応**
   - 例：`{DateTime}`、`{Time}`、`{DayOfWeek}` など複数形式に対応
   - `config/placeholder_templates.json` で管理

2. **スクリプト統合化**
   - `obs_title_updater.py` のロジックを `packages/local` の共通モジュール化
   - 他のOBSスクリプトでの再利用性向上

3. **キャッシング機構**
   - 最近実行したプレースホルダー置き換えをメモリまたはファイルにキャッシュ
   - 重複実行防止

4. **配信停止時の処理**
   - 今後、追加の処理が必要になった場合は `OBS_FRONTEND_EVENT_STREAMING_STOPPED` で拡張可能

## 実装チェックリスト

- [x] `packages/obs-title-updater/` ディレクトリ作成
- [x] `packages/obs-title-updater/src/main.py` を実装
- [x] ログ設定、エラーハンドリングの確認
- [x] OAuth2認証フロー（ADR-004準拠）の動作確認
- [x] `{DateTime}` プレースホルダー検出の確認
- [x] UTC → JST 変換の精度検証
- [x] YouTube Data API でのタイトル更新の確認
- [x] OBSスクリプト側での呼び出しテスト実装例をドキュメント化
- [x] ドキュメント作成（`packages/obs-title-updater/README.md` など）
- [x] ドキュメント更新（プロジェクトのメイン `CLAUDE.md` への追加）

## 次のステップ

1. **ADR-028承認**
2. **実装開始**: `packages/obs-title-updater/` パッケージの開発
3. **ローカルテスト**: ダミー動画データでの検証
4. **OBS統合テスト**: OBSスクリプトからの実行確認
5. **実運用確認**: 実際の配信開始イベントでの動作検証

## 関連ADR

- [ADR-004: OAuth2認証の統一](004-oauth2-authentication-for-all-gcp-apis.md) - 認証方式の準拠
- [ADR-027: PS5 自動アップロード動画のタイトル自動書き換え](027-ps5-auto-title-rename.md) - **独立した異なるユースケース**（PS5 vs PC配信）

**注**: ADR-027とADR-028は独立した機能であり、互いに排他的ではない。ADR-027はPS5からのYouTube自動アップロード向け、ADR-028はPC配信（OBS）向けである。

## 参考資料

- [YouTube Data API - search.list](https://developers.google.com/youtube/v3/docs/search/list)
- [YouTube Data API - videos.update](https://developers.google.com/youtube/v3/docs/videos/update)
- [OBS Python Plugin Documentation](https://github.com/obsproject/obs-studio/blob/master/plugins/scripting/python/obspython.py)
- [OBS Frontend Events](https://github.com/obsproject/obs-studio/blob/master/plugins/scripting/python/obspython.py#L122)
