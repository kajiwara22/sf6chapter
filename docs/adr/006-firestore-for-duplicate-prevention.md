# ADR-006: Firestoreによる処理済み動画の追跡

- **ステータス**: 採用
- **決定日**: 2025-12-31
- **決定者**: kajiwara22

## 1. 議論の背景

Cloud Functionで2時間毎に新着動画をチェックする際、以下の課題がある:

1. **重複処理の防止**: 同じ動画を複数回Pub/Subに発行してしまう
2. **冪等性の保証**: Cloud Schedulerの再実行や障害リトライで重複実行される可能性
3. **処理状態の追跡**: 動画の処理状態（キューイング、処理中、完了、失敗）を管理
4. **履歴の保持**: どの動画をいつ処理したかの記録

## 3. 各選択肢の比較

### 検討した選択肢

#### 1. Firestore（採用）
- **メリット**: 無料枠が大きい、NoSQL、リアルタイム更新、スケーラブル
- **デメリット**: SQLライクなクエリは不可

#### 2. Cloud SQL
- **メリット**: RDB、複雑なクエリ可能
- **デメリット**: 最小構成でも月$10程度、過剰スペック

#### 3. Cloud Datastore（Firestoreの旧版）
- **メリット**: Firestoreと類似
- **デメリット**: Firestoreに置き換えられている

#### 4. Memorystore（Redis）
- **メリット**: 高速
- **デメリット**: 最小構成で月$50程度、永続化が必要

#### 5. ローカルファイル（JSON）
- **メリット**: シンプル
- **デメリット**: Cloud Functionsは状態を保持しない

## 2. 選択肢と結論

### 結論

**Firestoreを使用して処理済み動画を追跡する。**

### データ構造

#### コレクション: `processed_videos`

ドキュメントID = `videoId`（YouTube動画ID）

```json
{
  "videoId": "xxxxxxxxxxx",
  "title": "動画タイトル",
  "channelId": "UCxxx",
  "channelTitle": "チャンネル名",
  "publishedAt": "2024-12-31T10:00:00Z",
  "status": "queued",
  "queuedAt": "2024-12-31T10:00:00Z",
  "updatedAt": "2024-12-31T10:00:00Z"
}
```

#### ステータス定義

- `queued`: Pub/Subキューに追加済み
- `processing`: ローカル処理中
- `completed`: 処理完了
- `failed`: 処理失敗

### 実装方針

1. **重複チェック**: 動画発見時にFirestoreで既存チェック
2. **アトミック操作**: ドキュメントが存在しない場合のみ作成
3. **ステータス更新**: ローカル処理の各段階でステータス更新
4. **エラーハンドリング**: Firestoreエラー時は処理をスキップ（重複リスク回避）


## 4. 結論を導いた重要な観点

### 4.1 コスト効率
想定使用量（書き込み72回/日、読み取り72回/日）では、Firestore無料枠の1%以下であり、完全に無料で運用可能。

### 4.2 シンプルさ
NoSQLデータベースでスキーママイグレーション不要。ドキュメントの作成・更新のみで状態管理が完結。

### 4.3 信頼性とスケーラビリティ
フルマネージドサービスで運用負荷なし。将来的な動画数増加にも対応可能。

### 4.4 GCP統合
Cloud FunctionsとFirestoreは同じGCPプロジェクト内で動作し、IAM権限管理が統一的。

## 5. 帰結

### 5.1 メリット

1. **無料**: 想定使用量では完全に無料枠内
2. **シンプル**: NoSQLでスキーマ不要、セットアップ簡単
3. **スケーラブル**: 動画数増加にも対応可能
4. **リアルタイム**: ドキュメント変更をリアルタイムで監視可能（将来の機能拡張）
5. **管理不要**: フルマネージドサービス
6. **セキュリティ**: IAMで細かい権限制御
7. **監視**: Cloud Loggingで完全な監査ログ

### 5.2 デメリット

1. **NoSQL制約**: 複雑なクエリやJOINは不可（本プロジェクトでは不要）
2. **Firestore依存**: GCP固有サービス（他プロバイダーへの移行が困難）

### 5.3 トレードオフ

- **コスト vs 機能**: RDBの機能は不要で、Firestoreで十分
- **シンプルさ vs 柔軟性**: シンプルさを優先、複雑なクエリは不要
- **ベンダーロックイン**: GCPエコシステム内で完結するため問題なし

## 6. 実装詳細

### Cloud Functions側

```python
from google.cloud import firestore

def is_video_processed(video_id: str) -> bool:
    """動画が処理済みかチェック"""
    db = firestore.Client()
    doc_ref = db.collection("processed_videos").document(video_id)
    return doc_ref.get().exists

def mark_video_as_processing(video_id: str, video_data: dict) -> bool:
    """動画を処理中としてマーク"""
    db = firestore.Client()
    doc_ref = db.collection("processed_videos").document(video_id)

    # 既存チェック
    if doc_ref.get().exists:
        return False

    # 新規作成
    doc_ref.set({
        "videoId": video_id,
        "status": "queued",
        "queuedAt": firestore.SERVER_TIMESTAMP,
        **video_data
    })
    return True
```

### ローカル処理側

**Phase 1実装（2025-01-01）**: Firestoreと統合し、Pub/Sub再配信による重複処理を防止

```python
from src.firestore import FirestoreClient

class SF6ChapterProcessor:
    def __init__(self):
        self.firestore = FirestoreClient()

    def process_video(self, message_data: dict) -> None:
        video_id = message_data.get("videoId")

        # 0. Firestoreで処理済みかチェック
        if self.firestore.is_completed(video_id):
            logger.info("Video already completed, skipping")
            return

        # 処理開始をFirestoreに記録
        self.firestore.update_status(video_id, FirestoreClient.STATUS_PROCESSING)

        try:
            # ... 動画処理 ...

            # 処理完了をFirestoreに記録
            self.firestore.update_status(video_id, FirestoreClient.STATUS_COMPLETED)

        except Exception as e:
            # 処理失敗をFirestoreに記録
            self.firestore.update_status(video_id, FirestoreClient.STATUS_FAILED, error_message=str(e))
```

これにより、Pub/Subメッセージが再配信されても、既に完了した動画は再処理されない。

## 7. 監視とメンテナンス

### データ保持期間

当面は削除せず蓄積。将来的に以下の戦略を検討:
- 完了ステータスの動画は1年後に削除
- 失敗ステータスは3ヶ月後に削除
- Cloud Schedulerで定期クリーンアップ

### モニタリング

- Firestore使用量をCloud Monitoringで監視
- 無料枠の80%到達でアラート設定

## 8. 関連ADR・参考資料

- [ADR-001: クラウドサービス選定](001-cloud-service-selection.md) - GCP選定理由
- [ADR-004: OAuth2認証](004-oauth2-authentication-for-all-gcp-apis.md) - 認証方式
- `packages/gcp-functions/check-new-video/main.py` - Cloud Functions実装
- `packages/local/src/firestore/client.py` - ローカル処理のFirestoreクライアント
- `packages/local/main.py` - ローカル処理のメインスクリプト
