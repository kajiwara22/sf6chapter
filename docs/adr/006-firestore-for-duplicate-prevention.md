# 6. Firestoreによる処理済み動画の追跡

日付: 2025-12-31

## ステータス

採用

## コンテキスト

Cloud Functionで15分毎に新着動画をチェックする際、以下の課題がある:

1. **重複処理の防止**: 同じ動画を複数回Pub/Subに発行してしまう
2. **冪等性の保証**: Cloud Schedulerの再実行や障害リトライで重複実行される可能性
3. **処理状態の追跡**: 動画の処理状態（キューイング、処理中、完了、失敗）を管理
4. **履歴の保持**: どの動画をいつ処理したかの記録

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

## 決定

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

### コスト見積もり

#### Firestore無料枠
- ストレージ: 1 GiB
- 読み取り: 50,000回/日
- 書き込み: 20,000回/日
- 削除: 20,000回/日

#### 使用量見積もり（3チャンネル監視）
- ストレージ: 1ドキュメント約200バイト → 500万件以上保存可能
- 書き込み: 最大576回/日（3ch × 2動画 × 96回/日）→ 無料枠の2.9%
- 読み取り: 最大576回/日（重複チェック）→ 無料枠の1.2%

**結論**: 完全に無料枠内で運用可能

## 結果

### メリット

1. **無料**: 想定使用量では完全に無料枠内
2. **シンプル**: NoSQLでスキーマ不要、セットアップ簡単
3. **スケーラブル**: 動画数増加にも対応可能
4. **リアルタイム**: ドキュメント変更をリアルタイムで監視可能（将来の機能拡張）
5. **管理不要**: フルマネージドサービス
6. **セキュリティ**: IAMで細かい権限制御
7. **監視**: Cloud Loggingで完全な監査ログ

### デメリット

1. **NoSQL制約**: 複雑なクエリやJOINは不可（本プロジェクトでは不要）
2. **Firestore依存**: GCP固有サービス（他プロバイダーへの移行が困難）

### トレードオフ

- **コスト vs 機能**: RDBの機能は不要で、Firestoreで十分
- **シンプルさ vs 柔軟性**: シンプルさを優先、複雑なクエリは不要
- **ベンダーロックイン**: GCPエコシステム内で完結するため問題なし

## 実装詳細

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

```python
def update_video_status(video_id: str, status: str):
    """処理状態を更新"""
    db = firestore.Client()
    doc_ref = db.collection("processed_videos").document(video_id)
    doc_ref.update({
        "status": status,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })
```

## 監視とメンテナンス

### データ保持期間

当面は削除せず蓄積。将来的に以下の戦略を検討:
- 完了ステータスの動画は1年後に削除
- 失敗ステータスは3ヶ月後に削除
- Cloud Schedulerで定期クリーンアップ

### モニタリング

- Firestore使用量をCloud Monitoringで監視
- 無料枠の80%到達でアラート設定

## 関連

- [ADR-001: クラウドサービス選定](001-cloud-service-selection.md) - GCP選定理由
- [ADR-004: OAuth2認証](004-oauth2-authentication-for-all-gcp-apis.md) - 認証方式
- `packages/gcp-functions/check-new-video/main.py` - 実装コード
