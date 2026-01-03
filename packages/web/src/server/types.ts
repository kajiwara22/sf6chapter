/**
 * SF6 Chapter - サーバー型定義
 */

/** Cloudflare Bindings */
export type Bindings = {
  /** R2バケット */
  SF6_DATA: R2Bucket;
  /** 環境名 */
  ENVIRONMENT: string;
  /** R2 S3 API用 - エンドポイント */
  R2_ENDPOINT_URL: string;
  /** R2 S3 API用 - アクセスキーID */
  R2_ACCESS_KEY_ID: string;
  /** R2 S3 API用 - シークレットアクセスキー */
  R2_SECRET_ACCESS_KEY: string;
  /** R2 S3 API用 - バケット名 */
  R2_BUCKET_NAME: string;
}

