/**
 * SF6 Chapter - 共通型定義
 * サーバー・クライアント両方から参照
 */

/** プレイヤー情報 */
export interface Player {
  /** 正規化されたキャラクター名 */
  character: string;
  /** 生のキャラクター名（OCR結果） */
  characterRaw: string;
  /** プレイヤーの位置 */
  side: 'left' | 'right';
}

/** 対戦データ */
export interface Match {
  /** 一意のID (videoId_startTime) */
  id: string;
  /** YouTube動画ID */
  videoId: string;
  /** YouTube動画タイトル */
  videoTitle: string;
  /** YouTube動画の公開日時 (ISO8601) */
  videoPublishedAt: string;
  /** 対戦開始時間（秒） */
  startTime: number;
  /** 対戦終了時間（秒） */
  endTime?: number;
  /** 1Pプレイヤー */
  player1: Player;
  /** 2Pプレイヤー */
  player2: Player;
  /** 検出日時 (ISO8601) */
  detectedAt: string;
  /** 信頼度スコア (0-1) */
  confidence: number;
}

/** 動画データ */
export interface Video {
  /** YouTube動画ID */
  videoId: string;
  /** 動画タイトル */
  title: string;
  /** チャンネルID */
  channelId: string;
  /** チャンネル名 */
  channelTitle: string;
  /** 公開日時 (ISO8601) */
  publishedAt: string;
  /** 処理日時 (ISO8601) */
  processedAt: string;
  /** チャプター情報 */
  chapters: Chapter[];
  /** 検出統計 */
  detectionStats: DetectionStats;
}

/** チャプター情報 */
export interface Chapter {
  /** 開始時間（秒） */
  startTime: number;
  /** チャプタータイトル */
  title: string;
  /** 対応するMatchのID */
  matchId: string;
}

/** 検出統計 */
export interface DetectionStats {
  /** 処理したフレーム総数 */
  totalFrames: number;
  /** マッチしたフレーム数 */
  matchedFrames: number;
}

/** 検索フィルター */
export interface SearchFilters {
  /** キャラクター名 */
  character?: string;
  /** 期間（開始） */
  dateFrom?: string;
  /** 期間（終了） */
  dateTo?: string;
  /** 検索上限 */
  limit?: number;
}

/** 統計情報 */
export interface Stats {
  /** 総対戦数 */
  totalMatches: number;
  /** 総動画数 */
  totalVideos: number;
  /** キャラクター別対戦数 */
  characterCounts: Record<string, number>;
  /** 最新の検出日時 */
  latestDetectedAt?: string;
}

/** APIレスポンス */
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

/** Presigned URLレスポンス */
export interface PresignedUrlResponse {
  url: string;
  expiresIn: number;
}

/** ヘルスチェックレスポンス */
export interface HealthResponse {
  status: 'ok' | 'error';
  environment: string;
  timestamp: string;
}
