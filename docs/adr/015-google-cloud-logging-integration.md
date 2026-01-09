# ADR-015: Cloud Functionsでのgoogle-cloud-logging統合

## ステータス

採用

## コンテキスト

Cloud Functions Gen2（Cloud Run環境）でアプリケーションログを出力する際、以下の課題がありました：

1. **標準loggingライブラリの制限**: Python標準の`logging.basicConfig()`ではCloud Loggingにログが送信されない
2. **print()による回避策の問題**:
   - Severityレベルが手動でテキストに含める必要がある
   - 構造化ログ（JSON形式）に対応していない
   - Cloud Loggingのメタデータ（trace、span、labels）を活用できない
   - コードが複雑化（ヘルパー関数が必要）

### 初期実装（print()回避策）

```python
def log_info(message):
    """INFOレベルのログを出力"""
    logger.info(message)
    print(f"INFO: {message}", flush=True)

def log_error(message):
    """ERRORレベルのログを出力"""
    logger.error(message)
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
```

この実装では、ログは出力されるものの、以下の問題がありました：
- Severityレベルがテキストに埋め込まれるだけで、Cloud Loggingのフィールドとして扱われない
- 構造化ログやメタデータの活用ができない
- ヘルパー関数の保守が必要

## 決定

**google-cloud-loggingライブラリを使用してCloud Loggingとネイティブに統合する**

### 実装方法

```python
import google.cloud.logging

# Cloud Loggingクライアントをセットアップ
logging_client = google.cloud.logging.Client()
logging_client.setup_logging()

# 標準的なPythonロギングを使用（Cloud Loggingに自動統合される）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 通常のログ出力
logger.info("YouTube API client initialized")
logger.error("Failed to initialize credentials")
logger.warning("Video already processed")
```

### 依存関係

`requirements.txt`に追加：
```
google-cloud-logging==3.10.*
```

## 理由

### google-cloud-loggingの利点

1. **適切なSeverityレベル**:
   - `logger.info()` → Cloud LoggingでINFOレベル
   - `logger.error()` → Cloud LoggingでERRORレベル
   - `logger.warning()` → Cloud LoggingでWARNINGレベル

2. **構造化ログのサポート**:
   ```python
   logger.info("Video processed", extra={
       "video_id": video_id,
       "duration": duration,
       "channel": channel_name
   })
   ```

3. **Cloud Loggingメタデータの活用**:
   - Trace ID: 分散トレーシングとの統合
   - Span ID: リクエストスパンの追跡
   - Labels: カスタムラベルの追加
   - Source Location: ソースコードの位置情報

4. **コードの簡素化**:
   - ヘルパー関数が不要
   - 標準的なPythonロギングパターンをそのまま使用
   - 保守性の向上

5. **Cloud Functions Gen2との互換性**:
   - Cloud Run環境でネイティブにサポート
   - 自動的にリクエストコンテキストを統合

### 実装の簡潔さ

| 項目 | print()回避策 | google-cloud-logging |
|------|--------------|---------------------|
| 初期化コード行数 | 20行（ヘルパー関数含む） | 5行 |
| ログ出力コード | `log_info()` | `logger.info()` |
| Severityレベル | テキストに埋め込み | 自動設定 |
| 構造化ログ | 未対応 | 対応 |
| メタデータ | 未対応 | 対応 |

## 結果

### 期待される成果

1. **ログの可視性向上**: Cloud Loggingコンソールでの検索とフィルタリングが容易
2. **デバッグの効率化**: Severityレベルによる絞り込み、構造化データでの検索
3. **運用性の向上**: トレーシング、モニタリング、アラートとの統合
4. **コード品質の向上**: 標準パターンの使用、保守性の向上

### 動作確認

デプロイ後のテストで以下を確認：
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=check-new-video" \
  --limit=20 --format="table(timestamp,severity,textPayload)"
```

出力例：
```
TIMESTAMP                    SEVERITY  TEXT_PAYLOAD
2026-01-09T06:36:20.680050Z  INFO      Check completed: {'foundVideos': 0, ...}
2026-01-09T06:36:19.356075Z  INFO      OAuth2 credentials initialized successfully
2026-01-09T06:36:19.192606Z  INFO      Successfully retrieved secret: youtube-client-secret
```

✅ すべてのログでSeverityレベルが正しく設定されていることを確認

## トレードオフ

### メリット
- Cloud Loggingのネイティブ機能を完全活用
- 標準的なPythonロギングパターン
- コードの簡潔性と保守性
- 構造化ログとメタデータのサポート

### デメリット
- 依存関係が1つ増加（`google-cloud-logging`）
- 初期化コストがわずかに増加（実行時のオーバーヘッドは無視できるレベル）

### 代替案との比較

#### 代替案1: print()回避策（採用しない）
- **利点**: 依存関係なし、シンプル
- **欠点**: Severityレベル未対応、構造化ログ未対応、保守性低い

#### 代替案2: 標準loggingのみ（採用しない）
- **利点**: 依存関係なし
- **欠点**: Cloud Functions Gen2ではログが表示されない

#### 代替案3: 構造化ログをJSONで標準出力（採用しない）
- **利点**: 依存関係なし、構造化ログ対応
- **欠点**: 手動でJSON構築が必要、エラーハンドリングが複雑

## 参考資料

- [Cloud Logging Python クライアントライブラリ](https://cloud.google.com/logging/docs/setup/python)
- [Cloud Functions Gen2 でのロギング](https://cloud.google.com/functions/docs/monitoring/logging)
- [Cloud Run でのロギング](https://cloud.google.com/run/docs/logging)
- [Pythonロギングのベストプラクティス](https://cloud.google.com/logging/docs/best-practices)

## 関連するADR

- [ADR-014: Cloud FunctionのOIDC認証による保護](./014-cloud-function-oidc-authentication.md) - セキュリティ強化との統合
- [ADR-012: check-new-video専用サービスアカウントの採用](./012-check-new-video-dedicated-service-account.md) - サービスアカウント権限設定

## 実装日

2026-01-09

## 実装者

Claude Code + ユーザー
