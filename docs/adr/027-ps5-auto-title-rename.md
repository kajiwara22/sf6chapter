# ADR-027: PS5 自動アップロード動画のタイトル自動書き換え

## ステータス

提案 - 2026-02-24

## 文脈

### 現在の問題

PS5 から YouTube に動画をアップロードする際、ユーザーが正確なタイトルを入力するのが不便。PS5 のデフォルトタイトル入力では時間をかけずに簡潔なタイトルのみ設定できるため、毎回手動で後から修正する負担がある。

### ユースケース

- 昼休みに配信した動画：「お昼休みにスト６ YYYY/MM/DD」という形式にしたい
- 就業後に配信した動画：「就業後にスト６ YYYY/MM/DD」という形式にしたい
- その他の時間帯：「PS5 からスト６ YYYY/MM/DD」という形式にしたい

### 実装の制約

- PS5 からのアップロード時、タイトルは必ず「連続した同一のひらがな 3 文字」となる（例：`あああ`、`ふふふ`、`ううう`）
- 動画の公開日時（`publishedAt`）は UTC 形式で取得され、JST に変換が必要
- YouTube Data API の `videos.update` エンドポイントを使用してタイトルを更新

### 設計の背景

ユーザーが PS5 でのタイトル入力時間を最小限にするため、以下の特性を活用：
- 同一のひらがな文字を 3 回連続で入力するだけで検出可能（入力手間が少ない）
  - 例：`あ`キーを 3 回押すだけで`あああ`となる
  - YouTube での一般的なタイトル入力より圧倒的に少ない手間
- 「同じ文字を 3 回連続」というタイトルは実務的にほぼ存在せず、他の投稿と被る可能性が極めて低い
- 正規表現による判定が簡潔で実装が軽い

## 決定

`check-new-video` Cloud Function 内で連続した同一のひらがな 3 文字のタイトルを検出し、公開日時に基づいて以下の 3 つのいずれかに自動的に書き換える：

| 時間帯（JST） | リネーム後のタイトル |
|-------------|-------------------|
| 12:00 ≤ 時刻 < 13:00 | `お昼休みにスト６ YYYY/MM/DD` |
| 18:00 ≤ 時刻 < 22:00 | `就業後にスト６ YYYY/MM/DD` |
| その他 | `PS5からスト６ YYYY/MM/DD` |

## 実装方針

### 1. タイトル検出

```python
import re

def is_ps5_auto_title(title: str) -> bool:
    """PS5のデフォルトタイトル（連続した同一のひらがな3文字）判定"""
    return bool(re.match(r'^([ぁ-ん])\1{2}$', title))
```

**判定ルール**：
- タイトルが「連続した**同一の**ひらがな 3 文字」のみで構成されている場合、PS5 自動アップロードと判定
- 全角スペース、特殊文字、数字は含まない
- ✅ OK例：`あああ`、`ふふふ`、`ううう`
- ❌ NG例：`あいう`、`えおか`、`あああい`

**設計理由**：
- PS5 でのタイトル入力の手間を最小限に（同じ文字を3回連打するだけでOK）
- 他のユーザー投稿タイトルと被る可能性が極めて低い（わざわざ同じ文字を3回入力するタイトルはほぼない）
- 正規表現が簡潔で実装が軽い

### 2. 時刻判定ロジック

```python
from datetime import datetime, timezone, timedelta
import pytz

def get_rename_title(published_at_utc: str) -> str:
    """
    公開日時（UTC）から JST を求め、時刻に応じてリネーム後のタイトルを決定

    Args:
        published_at_utc: YouTube APIから取得した公開日時（ISO 8601形式、UTC）
                         例: "2025-12-04T10:30:00Z"

    Returns:
        リネーム後のタイトル
        例: "お昼休みにスト６ 2025-12-04"
    """
    # UTC → JST 変換
    dt_utc = datetime.fromisoformat(published_at_utc.replace("Z", "+00:00"))
    jst = pytz.timezone("Asia/Tokyo")
    dt_jst = dt_utc.astimezone(jst)

    # 時刻を取得
    hour = dt_jst.hour
    date_str = dt_jst.strftime("%Y-%m-%d")

    # 時刻帯で判定
    if 12 <= hour < 13:
        prefix = "お昼休みにスト６"
    elif 18 <= hour < 22:
        prefix = "就業後にスト６"
    else:
        prefix = "PS5からスト６"

    return f"{prefix} {date_str}"
```

**時刻判定の詳細**：
- `12:00 ≤ 時刻 < 13:00`：「お昼休みにスト６」
- `18:00 ≤ 時刻 < 22:00`：「就業後にスト６」
- それ以外：「PS5からスト６」

### 3. YouTube Data API でのタイトル更新

```python
def rename_video_title(youtube_service, video_id: str, new_title: str) -> bool:
    """
    YouTube Data APIでビデオタイトルを更新

    Args:
        youtube_service: YouTube API クライアント
        video_id: 更新対象の動画 ID
        new_title: 新しいタイトル

    Returns:
        成功時 True、失敗時 False
    """
    try:
        # 現在のビデオ情報を取得
        get_response = youtube_service.videos().list(
            part="snippet",
            id=video_id
        ).execute()

        if not get_response.get("items"):
            logger.error(f"Video not found: {video_id}")
            return False

        # タイトルを更新
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

        logger.info(f"Successfully renamed video {video_id} to '{new_title}'")
        return True

    except HttpError as e:
        logger.error(f"YouTube API error while renaming {video_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error renaming {video_id}: {e}")
        return False
```

### 4. check-new-video への統合

`check_new_video` 関数内のメインループで以下の処理を追加：

```python
def check_new_video(request):
    # ... 既存の初期化処理 ...

    for video in videos:
        video_id = video["videoId"]
        title = video["title"]
        published_at = video["publishedAt"]

        # PS5自動タイトル検出
        if is_ps5_auto_title(title):
            logger.info(f"Detected PS5 auto-title: '{title}' for {video_id}")

            # 新しいタイトルを決定
            new_title = get_rename_title(published_at)

            # YouTube APIでタイトルを更新（エラーは処理継続）
            if rename_video_title(youtube, video_id, new_title):
                logger.info(f"Renamed {video_id}: '{title}' → '{new_title}'")
                # Firestore記録時に新しいタイトルを使用
                video["title"] = new_title
            else:
                logger.warning(f"Failed to rename {video_id}, proceeding with original title")
                # エラーでも処理は継続（元のタイトルで記録）

        # 重複チェック、Pub/Sub発行など既存処理は継続...
        if is_video_processed(video_id):
            logger.info(f"Video {video_id} already processed, skipping")
            stats["skippedVideos"] += 1
            continue

        # ... 既存処理 ...
```

### 5. エラーハンドリング方針

**タイトル更新失敗時の動作**：
- YouTube API の呼び出しエラーは **ログに記録されるが処理は継続**
- 元のタイトル（またはひらがな 3 文字）でも Pub/Sub に発行
- 統計情報に失敗カウントを追加可能
- ユーザーは手動で後から修正可能

**実装理由**：
- check-new-video は複数動画を処理するため、1 つの失敗で全体が停止するのは避けるべき
- タイトル更新失敗は「致命的エラー」ではなく「部分的な失敗」
- 動画処理自体（Pub/Sub 発行）は継続できる

## 実装の選択肢と比較

### 選択肢 1: Cloud Functions 内で更新（採用）

| 観点 | 評価 |
|------|------|
| 実装複雑度 | 低（YouTube API 呼び出し追加のみ） |
| 処理の早さ | 高（即座に更新） |
| 信頼性 | 中（API エラーの影響限定） |
| 保守性 | 高（既存フローに統合） |
| API quota | 50 単位/リクエスト（2 時間毎で影響少） |

### 選択肢 2: ローカル PC 処理で更新

| 観点 | 評価 |
|------|------|
| 実装複雑度 | 中（Pub/Sub → ローカル処理の統合） |
| 処理の早さ | 低（Pub/Sub → ローカル PC の遅延） |
| 信頼性 | 高（既存のローカル処理フロー統合） |
| 保守性 | 中（複数の処理フロー管理） |
| API quota | 同上 |

**採択理由**：
- PS5 自動タイトルの検出は `check-new-video` で行う必要がある（YouTube API データ）
- YouTube API の呼び出しはすでに `check-new-video` で実施中（認証、クライアント初期化済み）
- ローカル PC を経由すると更新のレイテンシが増加（不要な複雑化）
- エラーハンドリングを丁寧に実装することで信頼性を確保可能

## トレードオフと帰結

### メリット ✅

- **自動化**: ユーザーがタイトル修正する手間を削減
- **シンプル**: 既存の `check-new-video` フロー内に統合、新しいマイクロサービス不要
- **迅速**: 動画アップロード直後にタイトルが自動修正される
- **柔軟性**: 時刻判定ロジックは容易に変更可能
- **エラー耐性**: YouTube API エラーでも他の処理は継続

### デメリット ⚠️

- **時刻判定の固定化**: 時刻帯（12:00、18:00、22:00）が定数化され、後から変更には要コード修正
- **API quota 消費**: YouTube API の `videos.update` が 2 時間毎に実行（ただし quota は十分）
- **PS5 フォーマット依存**: PS5 がデフォルトで「ひらがな 3 文字」を使用し続けることを前提
- **手動修正不可回避**: 万が一 API エラー時、ユーザーが手動修正する必要あり

### 互換性 ✅

- Firestore のスキーマ変更なし（`title` フィールドに新しい値が格納されるだけ）
- Pub/Sub メッセージフォーマットの変更なし
- 既存の動画処理フロー（chapters.json 生成など）に影響なし

## 将来の改善

1. **時刻帯の動的設定**
   - `detection_params.json` に時刻帯を追加管理
   - ユーザーがコード修正なく時刻帯を変更可能

2. **タイトルテンプレートのカスタマイズ**
   - 固定文字列（「お昼休み」「就業後」など）を環境変数化
   - 複数のテンプレートパターンに対応

3. **連続したひらがな 3 文字の厳密な検証**
   - 実装後、実際の PS5 アップロード動画でフォーマット検証
   - PS5 の仕様変更時の対応（例：タイトル形式が変わった場合）

## 実装チェックリスト

- [ ] `is_ps5_auto_title()` 関数実装
- [ ] `get_rename_title()` 関数実装（UTC → JST 変換含む）
- [ ] `rename_video_title()` 関数実装
- [ ] `check-new-video/main.py` への統合
- [ ] エラーハンドリング（YouTube API エラーで処理継続）の確認
- [ ] Cloud Functions へのデプロイ
- [ ] 実運用での動作確認（PS5 アップロード動画で検証）
- [ ] ログ出力の確認（Cloud Logging で自動書き換え履歴を確認可能）

## 次のステップ

1. **ADR-027 承認**
2. **実装開始**：`check-new-video/main.py` へのコード追加
3. **ローカルテスト**：ダミー動画データでの検証
4. **デプロイ**：`gcloud functions deploy` で本番環境へ
5. **運用確認**：実際の PS5 アップロード動画で自動書き換えが動作することを確認

## 参考資料

- [YouTube Data API - videos.update](https://developers.google.com/youtube/v3/docs/videos/update)
- [check-new-video Cloud Function](../../packages/gcp-functions/check-new-video/main.py)
- [ADR-008: Cloud FunctionsでのOAuth2ユーザー認証実装](008-oauth2-user-authentication-in-cloud-functions.md)
