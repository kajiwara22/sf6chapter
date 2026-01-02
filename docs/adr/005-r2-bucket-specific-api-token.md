# ADR-005: R2バケット専用APIトークンとS3互換アクセス

- **ステータス**: 採用
- **決定日**: 2026-01-01
- **決定者**: kajiwara22

## 適用範囲

**このADRは `packages/local/` のローカルPC処理のみに適用される。**

Cloudflare Pages Functions (`packages/web/`) では、Workers環境の R2 Bindings を使用する。

## コンテキスト

ローカルPC上で動作するPython処理では、Cloudflare R2バケットへデータをアップロードする必要がある:

- チャプター検出結果のJSONファイル
- Parquet形式の検索用データ

当初、Cloudflare Global API Key や Account ID/API Token を使った直接アクセスを想定していたが、以下の課題がある:

- **権限が広すぎる**: アカウント全体へのアクセス権限が必要
- **セキュリティリスク**: トークンが漏洩した場合の影響範囲が大きい
- **管理の複雑さ**: ローテーションやスコープ制御が困難

## 決定

**R2バケット専用のAPIトークンを作成し、S3互換アクセスキーに変換して使用する。**

### トークン作成手順

参考: [CloudflareのR2バケットに特化したAPIトークンをつくる](https://zenn.dev/hikky_co_ltd/articles/2f97318b5406bf)

#### 1. Account API Tokenの作成
- Cloudflare Dashboard → API Tokens → Create Token
- 必要な権限: `Account.Account Settings:Read`

#### 2. Bucket-Specific Tokenの生成
- Account API Token を使用してバケット専用トークンを作成
- リソースパス: `com.cloudflare.edge.r2.bucket.{account_id}_default_{bucket_name}`
- 権限グループ: `Workers R2 Storage Bucket Item Read/Write`
- 生成されたトークンには以下の2つの値がある：
  - **Token ID**: そのまま `R2_ACCESS_KEY_ID` として使用
  - **Token Value**: SHA-256ハッシュ化して `R2_SECRET_ACCESS_KEY` として使用

#### 3. S3互換キーへの変換

Cloudflare公式ドキュメント: [Get S3 API credentials from an API token](https://developers.cloudflare.com/r2/api/s3/tokens/)

- **Access Key ID**: Token ID（そのまま）
- **Secret Access Key**: Token ValueをSHA-256ハッシュ化し、小文字化したもの

**ハッシュ化方法**:

```bash
# Bash/Zshの場合
./packages/local/scripts/r2_hash_token.sh

# Pythonの場合
uv run python packages/local/scripts/r2_hash_token.py
```

**手動でハッシュ化する場合**:

```bash
# macOS/Linux
echo -n "your-token-value" | shasum -a 256 | awk '{print $1}'

# PowerShell
$TokenValue = "your-token-value"
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$bytes = [System.Text.Encoding]::UTF8.GetBytes($TokenValue)
$hash = $sha256.ComputeHash($bytes)
[System.BitConverter]::ToString($hash).Replace("-", "").ToLower()

# Python
import hashlib
hashlib.sha256("your-token-value".encode()).hexdigest()
```

### 認証情報の管理

```python
# 環境変数で管理
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")          # Token ID（そのまま）
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")  # Token ValueのSHA-256ハッシュ（小文字）
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")            # {account_id}.r2.cloudflarestorage.com
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
```

**重要**: Token Valueそのものは環境変数に保存しない。SHA-256ハッシュ化した値のみを保存する。

### boto3での使用例

```python
import boto3

s3_client = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ENDPOINT_URL}",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",  # R2では "auto" を使用
)

# アップロード
s3_client.upload_file(
    Filename="local_file.json",
    Bucket=R2_BUCKET_NAME,
    Key="remote/path/file.json",
)
```

## 結果

### メリット

- **最小権限の原則**: 特定のR2バケットのみへのアクセス権限
- **セキュリティ向上**: トークン漏洩時の影響範囲を限定
- **S3互換性**: boto3などの既存のS3クライアントライブラリを使用可能
- **ローテーション容易**: バケット専用トークンのみを再生成すればよい

### デメリット

- **非公式手法**: Cloudflare公式ドキュメントで完全にサポートされていない方法
- **トークン生成の複雑さ**: 初回セットアップ時にAccount API Tokenとバケット専用トークンの2段階生成が必要
- **SHA-256変換**: Secret Access Key生成時にハッシュ処理が必要

### トレードオフ

- **セキュリティ vs セットアップの簡便性**: 初回セットアップは複雑だが、長期的なセキュリティ向上を優先
- **公式サポート vs 柔軟性**: 非公式手法だが、最小権限を実現するために採用

## Cloudflare Pages Functionsでのアクセス

Cloudflare Pages Functions では R2 Bindings を使用:

```typescript
// wrangler.toml
[[r2_buckets]]
binding = "R2_BUCKET"
bucket_name = "sf6-chapter-data"

// Pages Functions
export async function onRequest(context) {
  const { R2_BUCKET } = context.env;
  const object = await R2_BUCKET.get("path/to/file.json");
  return new Response(await object.text());
}
```

**理由**: Pages Functions環境ではBindingsが最も安全かつ効率的なアクセス方法。

## セキュリティのベストプラクティス

1. **環境変数で管理**: `.env` ファイルに保存（`.gitignore` に追加）
2. **定期的なローテーション**: 3〜6ヶ月ごとにトークンを再生成
3. **アクセスログの監視**: 不審なアクセスがないか定期的に確認
4. **最小権限**: Read/Write権限のみ、Deleteは別途管理

## 関連

### 実装ファイル
- `packages/local/src/storage/r2_uploader.py` - R2アクセス実装
- `packages/local/.env.example` - 環境変数テンプレート
- `packages/local/scripts/r2_hash_token.sh` - Bash用ハッシュ化スクリプト
- `packages/local/scripts/r2_hash_token.py` - Python用ハッシュ化スクリプト

### 参考資料
- [CloudflareのR2バケットに特化したAPIトークンをつくる](https://zenn.dev/hikky_co_ltd/articles/2f97318b5406bf)
- [Cloudflare R2 - Get S3 API credentials from an API token](https://developers.cloudflare.com/r2/api/s3/tokens/)
- [Cloudflare R2 Documentation](https://developers.cloudflare.com/r2/)
