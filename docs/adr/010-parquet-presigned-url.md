# ADR-010: Parquetデータ取得方式 - Presigned URL

- **ステータス**: 採用
- **決定日**: 2026-01-03
- **決定者**: kajiwara22
- **関連ADR**: [ADR-002: データストレージ・検索方式](./002-data-storage-search.md), [ADR-005: R2バケット専用APIトークン](./005-r2-bucket-specific-api-token.md)

## 1. 議論の背景

ブラウザ上のDuckDB-WASMでParquetファイルを読み込んで検索機能を実現する際、R2バケットからのデータ取得方式を検討する必要がある。

### 現状の構成

```
ブラウザ (DuckDB-WASM)
    ↓ fetch
Pages Functions (Hono)
    ↓ R2 Binding
R2バケット (matches.parquet)
```

### 課題

1. **ファイルサイズ制限**: Pages Functionsには128MBのメモリ制限があり、大きなParquetファイルをバッファリングするとメモリを圧迫する
2. **レスポンスタイム**: R2 → Pages Functions → ブラウザの2段階転送は、直接取得と比較してオーバーヘッドが発生
3. **将来的なスケーラビリティ**: データ量が増加した場合、Pages Functionsをプロキシとして使用する構成は非効率

### 要件

- R2バケットは非公開を維持する（ADR-002で決定済み）
- ブラウザから直接R2のデータにアクセスできること
- セキュリティを担保した上で、パフォーマンスを最適化すること

## 2. 選択肢と結論

### 結論

**Presigned URL方式**を採用する。APIがR2のPresigned URLを発行し、ブラウザはそのURLから直接Parquetファイルをダウンロードする。

### 検討した選択肢

| ID | 選択肢 |
|----|--------|
| A | Pages Functionsでプロキシ（現状維持） |
| B | Presigned URL方式（採用） |
| C | R2バケットの公開設定 |
| D | Cloudflare Access + R2 Public Bucket |

## 3. 各選択肢の比較表

| 観点 | A: プロキシ | B: Presigned URL（採用） | C: R2公開 | D: Access + Public |
|------|------------|-------------------------|----------|-------------------|
| セキュリティ | ◎ R2非公開 | ◎ 時限付きURL | × 完全公開 | ○ 認証必須 |
| パフォーマンス | △ 2段階転送 | ◎ 直接ダウンロード | ◎ 直接ダウンロード | ◎ 直接ダウンロード |
| メモリ効率 | × Functions内でバッファ | ◎ Functions負荷なし | ◎ Functions負荷なし | ◎ Functions負荷なし |
| 実装の複雑さ | ◎ シンプル | ○ AWS SDK必要 | ◎ シンプル | △ Access設定必要 |
| スケーラビリティ | △ 128MB制限 | ◎ 制限なし | ◎ 制限なし | ◎ 制限なし |
| コスト | ○ | ○ | ○ | △ Access課金 |

## 4. 結論を導いた重要な観点

### 4.1 セキュリティとパフォーマンスの両立

Presigned URLは以下のセキュリティ特性を持つ：

- **時限付き**: URLに有効期限を設定（本実装では1時間）
- **署名検証**: URLが改ざんされると無効化
- **オブジェクト単位**: 指定したオブジェクトのみアクセス可能

これにより、R2バケット自体は非公開を維持しつつ、必要なファイルのみ一時的にアクセスを許可できる。

### 4.2 Pages Functionsのメモリ制限回避

Pages Functionsの128MBメモリ制限を考慮すると、大きなファイルをバッファリングする現状の方式は将来的にリスクとなる。Presigned URL方式では、Functions はURLを生成するだけでデータ転送に関与しないため、メモリ効率が大幅に向上する。

### 4.3 レスポンスタイムの改善

```
【変更前】
ブラウザ → Pages Functions → R2 → Pages Functions → ブラウザ
           (約50ms)        (約20ms)  (約50ms)
           合計: 約120ms + データ転送時間

【変更後】
ブラウザ → Pages Functions (URL発行のみ) → ブラウザ → R2
           (約50ms)                                   (約30ms)
           合計: 約80ms + データ転送時間
```

小さなファイルでは差は軽微だが、データ量が増加するにつれて効果が顕著になる。

### 4.4 AWS SDK互換性

CloudflareのR2はAWS S3互換APIを提供しており、`@aws-sdk/s3-request-presigner`をそのまま使用できる。これにより、将来的にS3への移行も容易になる。

## 5. 帰結

### 5.1 アーキテクチャ

```
【新しいデータフロー】

1. ブラウザ
    │
    ├─→ GET /api/data/index/matches.parquet
    │
2. Pages Functions (Hono)
    │
    ├─→ AWS SDK でPresigned URL生成
    │   (R2のS3互換APIを使用)
    │
    └─→ { url: "https://...", expiresIn: 3600 } を返却
    │
3. ブラウザ
    │
    ├─→ Presigned URLからParquetを直接ダウンロード
    │
    └─→ DuckDB-WASMにロード
```

### 5.2 必要な設定

#### 環境変数（シークレット）

| 変数名 | 説明 |
|--------|------|
| `R2_ENDPOINT_URL` | R2 エンドポイント |
| `R2_ACCESS_KEY_ID` | R2 APIトークンのアクセスキーID |
| `R2_SECRET_ACCESS_KEY` | R2 APIトークンのシークレットアクセスキー |
| `R2_BUCKET_NAME` | バケット名 |

#### R2 APIトークンの権限

- **Object Read**: 必須
- **Object Write**: 不要（読み取り専用）

### 5.3 実装

#### サーバーサイド（API）

```typescript
import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

// S3Client生成（R2のS3互換エンドポイント）
const s3Client = new S3Client({
  region: 'auto',
  endpoint: `https://${env.R2_ENDPOINT_URL}`
  credentials: {
    accessKeyId: env.R2_ACCESS_KEY_ID,
    secretAccessKey: env.R2_SECRET_ACCESS_KEY,
  },
});

// Presigned URL生成
const command = new GetObjectCommand({
  Bucket: env.R2_BUCKET_NAME,
  Key: 'index/matches.parquet',
});
const url = await getSignedUrl(s3Client, command, { expiresIn: 3600 });

return c.json({ url, expiresIn: 3600 });
```

#### クライアントサイド

```typescript
// 1. APIからPresigned URLを取得
const response = await fetch('/api/data/index/matches.parquet');
const { url } = await response.json();

// 2. Presigned URLからParquetをダウンロード
const parquetResponse = await fetch(url);
const parquetData = await parquetResponse.arrayBuffer();

// 3. DuckDBに登録
await db.registerFileBuffer('matches.parquet', new Uint8Array(parquetData));
```

### 5.4 トレードオフ

| メリット | デメリット |
|---------|-----------|
| R2バケット非公開を維持 | AWS SDKの依存追加 |
| Pages Functionsのメモリ効率向上 | R2 APIトークンの管理が必要 |
| 直接ダウンロードによるレスポンス改善 | URL有効期限の考慮が必要 |
| 将来のスケーラビリティ確保 | 初期実装の複雑さ増加 |

### 5.5 将来の見直し条件

以下の場合、方式の見直しを検討する：

1. **Cloudflareの機能追加**
   - R2 BindingでPresigned URL生成がネイティブサポートされた場合
   - より効率的なデータ配信方式が提供された場合

2. **セキュリティ要件の変更**
   - より厳密なアクセス制御が必要になった場合
   - ユーザー認証との連携が必要になった場合

3. **パフォーマンス要件の変化**
   - リアルタイム性が求められる場合
   - CDNキャッシュの活用が必要になった場合

## 6. 各選択肢の詳細説明

### 選択肢A: Pages Functionsでプロキシ（現状維持）

```typescript
// R2 Bindingから直接取得してそのまま返却
const object = await bucket.get('index/matches.parquet');
const data = await object.arrayBuffer();
return c.body(data);
```

**不採用理由**:
- Pages Functionsの128MBメモリ制限
- データ転送の二重化によるオーバーヘッド
- 将来的なスケーラビリティの懸念

### 選択肢B: Presigned URL方式（採用）

**採用理由**:
- セキュリティとパフォーマンスの最適なバランス
- Pages Functionsのリソース効率化
- AWS SDK互換による可搬性

### 選択肢C: R2バケットの公開設定

```toml
# wrangler.toml
[[r2_buckets]]
bucket_name = "sf6-chapter-data"
public_read = true  # 公開設定
```

**不採用理由**:
- ADR-002でR2非公開を決定済み
- 誰でもデータにアクセス可能になる
- セキュリティポリシーに反する

### 選択肢D: Cloudflare Access + R2 Public Bucket

```
Cloudflare Access (認証)
    ↓
R2 Public Bucket
    ↓
ブラウザ
```

**不採用理由**:
- Cloudflare Accessの追加コスト（無料枠超過時）
- DuckDB-WASMからのfetchがAccess認証を通過できない可能性
- 設定の複雑さ

## 7. 参考資料

- [Cloudflare R2 - S3 API Compatibility](https://developers.cloudflare.com/r2/api/s3/api/)
- [AWS SDK for JavaScript v3 - S3 Request Presigner](https://docs.aws.amazon.com/AWSJavaScriptSDK/v3/latest/Package/-aws-sdk-s3-request-presigner/)
- [Cloudflare R2 - Presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)
- [ADR-002: データストレージ・検索方式](./002-data-storage-search.md)
- [ADR-005: R2バケット専用APIトークン](./005-r2-bucket-specific-api-token.md)

---

**変更履歴**:
- 2026-01-03: 初版作成、Presigned URL方式を採用
