/**
 * SF6 Chapter - APIルート
 * R2バケットからPresigned URLを生成
 */

import { Hono } from 'hono';
import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import type { Bindings } from '../types';
import type { HealthResponse, PresignedUrlResponse } from '@shared/types';
import { env } from 'hono/adapter'

const api = new Hono<{Bindings:Bindings}>();

/**
 * S3Clientを生成
 */
function createS3Client(endpointUrl:string, accessKeyId:string, secretAccessKey:string): S3Client {
  console.log(`https://${endpointUrl}`)
  return new S3Client({
    region: 'auto',
    endpoint: `https://${endpointUrl}`,
    credentials: {
      accessKeyId: accessKeyId,
      secretAccessKey: secretAccessKey,
    },
  });
}

/**
 * GET /api/health
 * ヘルスチェック
 */
api.get('/health', (c) => {
  const { ENVIRONMENT } = env(c)
  const response: HealthResponse = {
    status: 'ok',
    environment: ENVIRONMENT || 'unknown',
    timestamp: new Date().toISOString(),
  };
  return c.json(response);
});

/**
 * GET /api/data/index/matches.parquet
 * Parquetファイルの Presigned URL を返却
 */
api.get('/data/index/matches.parquet', async (context) => {
  try {
    const { R2_ENDPOINT_URL,R2_ACCESS_KEY_ID,R2_BUCKET_NAME,R2_SECRET_ACCESS_KEY } = env(context)
    const s3Client = createS3Client(R2_ENDPOINT_URL,R2_ACCESS_KEY_ID,R2_SECRET_ACCESS_KEY);
    const command = new GetObjectCommand({
      Bucket: R2_BUCKET_NAME,
      Key: 'matches.parquet',
    });

    const expiresIn = 3600; // 1時間
    const url = await getSignedUrl(s3Client, command, { expiresIn });

    const response: PresignedUrlResponse = {
      url,
      expiresIn,
    };

    return context.json(response);
  } catch (error) {
    console.error('Failed to generate presigned URL for matches.parquet:', error);
    return context.json({ error: 'Failed to generate presigned URL' }, 500);
  }
});

/**
 * GET /api/data/index/videos.parquet
 * 動画Parquetファイルの Presigned URL を返却
 */
api.get('/data/index/videos.parquet', async (context) => {
  try {
    const { R2_ENDPOINT_URL,R2_ACCESS_KEY_ID,R2_BUCKET_NAME,R2_SECRET_ACCESS_KEY } = env(context)
    const s3Client = createS3Client(R2_ENDPOINT_URL,R2_ACCESS_KEY_ID,R2_SECRET_ACCESS_KEY);
    const command = new GetObjectCommand({
      Bucket: R2_BUCKET_NAME,
      Key: 'index/videos.parquet',
    });

    const expiresIn = 3600; // 1時間
    const url = await getSignedUrl(s3Client, command, { expiresIn });

    const response: PresignedUrlResponse = {
      url,
      expiresIn,
    };

    return context.json(response);
  } catch (error) {
    console.error('Failed to generate presigned URL for videos.parquet:', error);
    return context.json({ error: 'Failed to generate presigned URL' }, 500);
  }
});

/**
 * GET /api/data/videos/:filename
 * 生JSONファイルを取得（デバッグ用）- 従来通りR2 Bindingから取得
 */
api.get('/data/videos/:filename', async (c) => {
  const filename = c.req.param('filename');
  const bucket = c.env.SF6_DATA;

  if (!filename.endsWith('.json')) {
    return c.json({ error: 'Only JSON files are allowed' }, 400);
  }

  const object = await bucket.get(`videos/${filename}`);

  if (!object) {
    return c.json({ error: 'File not found' }, 404);
  }

  const data = await object.json();
  return c.json(data);
});

/**
 * GET /api/data/matches/:filename
 * 対戦JSONファイルを取得（デバッグ用）- 従来通りR2 Bindingから取得
 */
api.get('/data/matches/:filename', async (c) => {
  const filename = c.req.param('filename');
  const bucket = c.env.SF6_DATA;

  if (!filename.endsWith('.json')) {
    return c.json({ error: 'Only JSON files are allowed' }, 400);
  }

  const object = await bucket.get(`matches/${filename}`);

  if (!object) {
    return c.json({ error: 'File not found' }, 404);
  }

  const data = await object.json();
  return c.json(data);
});

export { api };
