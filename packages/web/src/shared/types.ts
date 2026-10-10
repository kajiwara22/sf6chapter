/**
 * SF6 Chapter - 共通型定義
 * サーバー・クライアント両方から参照
 */

/** プレイヤー情報 */
export interface Player {
  /** 正規化されたキャラクター名 */
  character: string;
  /** プレイヤーの位置 */
  side: 'left' | 'right';
  /** Battlelog マッピング結果（勝敗） */
  result?: 'win' | 'loss';
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
  /** Battlelog マッピング成功フラグ */
  battlelogMatched?: boolean;
  /** Battlelog 信頼度 */
  battlelogConfidence?: 'high' | 'medium' | 'low';
  /** Battlelog リプレイID */
  battlelogReplayId?: string | null;
  /** Battlelog 時間差（秒） */
  battlelogTimeDiff?: number | null;
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

/** ソート順 */
export type SortOrder = 'publishedAt_desc' | 'publishedAt_asc' | 'confidence_desc';

/** 検索フィルター */
export interface SearchFilters {
  /** キャラクター名（1人目） */
  character?: string;
  /** キャラクター名（2人目、対戦カード検索用） */
  character2?: string;
  /** 動画タイトル検索（部分一致） */
  videoTitle?: string;
  /** 期間（開始） */
  dateFrom?: string;
  /** 期間（終了） */
  dateTo?: string;
  /** ソート順 */
  sortBy?: SortOrder;
  /** 検索上限 */
  limit?: number;
  /** プレイヤーの勝敗（キャラクターフィルターとの組み合わせ） */
  playerResult?: 'win' | 'loss';
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

/** マッチアップチャートの1行 */
export interface MatchupChartRow {
  /** 対戦相手キャラクター名 */
  opponentCharacter: string;
  /** 対戦相手の入力タイプ（0=クラシック, 1=モダン） */
  opponentInputType: number;
  /** 入力タイプ名 */
  opponentInputTypeName: string;
  /** 総対戦数 */
  total: number;
  /** 勝利数 */
  wins: number;
  /** 敗北数 */
  losses: number;
  /** 引き分け数 */
  draws: number;
  /** 勝率 (0-100) */
  winRate: number;
}

/** マッチアップチャートのフィルター */
export interface MatchupChartFilters {
  /** 期間（開始） YYYY-MM-DD */
  dateFrom?: string;
  /** 期間（終了） YYYY-MM-DD */
  dateTo?: string;
  /** 開始時刻 HH:MM（JSTで指定） */
  timeFrom?: string;
  /** 終了時刻 HH:MM（JSTで指定） */
  timeTo?: string;
  /** マッチタイプ（1=Ranked, 3=BattleHub, 4=CustomRoom） */
  battleType?: number;
  /** 自キャラクター名 */
  myCharacter?: string;
  /** 対戦相手入力タイプ（0=クラシック, 1=モダン） */
  opponentInputType?: number;
}

/** 対戦履歴の1行 */
export interface MatchHistoryRow {
  /** 自キャラクター名（Battlelog or matches由来） */
  myCharacter: string;
  /** 自入力タイプ（0=クラシック, 1=モダン）。YouTube側のみの場合はnull */
  myInputType: number | null;
  /** 勝敗（自分視点）。round_results から算出し、YouTube側のみの場合は matches の result にフォールバック */
  result: 'win' | 'loss' | 'draw' | null;
  /** 自分視点の各ラウンド決着方法IDのJSON配列文字列。YouTube側のみの場合はnull */
  myRounds: string | null;
  /** 相手視点の各ラウンド決着方法IDのJSON配列文字列。YouTube側のみの場合はnull */
  oppRounds: string | null;
  /** 相手プレイヤーID（fighter_id）。YouTube側のみの場合はnull */
  opponentName: string | null;
  /** 相手キャラクター名（Battlelog or matches由来） */
  opponentCharacter: string;
  /** 相手入力タイプ（0=クラシック, 1=モダン）。YouTube側のみの場合はnull */
  opponentInputType: number | null;
  /** ゲームモード名。YouTube側のみの場合はnull */
  battleTypeName: string | null;
  /** リプレイID。YouTube側のみの場合はnull */
  replayId: string | null;
  /** 試合日時（Battlelog uploaded_at or matches videoPublishedAt） */
  uploadedAt: string;
  /** YouTube動画ID（NULLの場合あり） */
  videoId: string | null;
  /** YouTube開始時間（秒）（NULLの場合あり） */
  startTime: number | null;
  /** matches.id（round_stats との突合キー）。Battlelogのみの行はnull */
  matchId: string | null;
  /** 自分が player1 か player2 か（round_stats の突合に使う） */
  selfSide: 'player1' | 'player2';
  /** ラウンド単位のカウンター回数（ADR-049、未計測時は空配列） */
  roundCounters: RoundCounterRow[];
}

/** round_stats のラウンド別カウンター回数（ADR-049） */
export interface RoundCounterRow {
  /** 試合ID（matches.id と一致） */
  matchId: string;
  /** ラウンド番号（1始まり） */
  round: number;
  /** サイド（生データのまま） */
  side: 'player1' | 'player2';
  /** COUNTER 回数（未計測時は null） */
  counterCount: number | null;
  /** PUNISH COUNTER 回数（未計測時は null） */
  punishCounterCount: number | null;
}

/** 対戦履歴のフィルター */
export interface MatchHistoryFilters {
  /** 自キャラクター名 */
  myCharacter?: string;
  /** 自入力タイプ（0=クラシック, 1=モダン） */
  myInputType?: number;
  /** 相手キャラクター名 */
  opponentCharacter?: string;
  /** 相手入力タイプ（0=クラシック, 1=モダン） */
  opponentInputType?: number;
  /** ゲームモード（battle_type） */
  battleType?: number;
  /** 期間（開始）YYYY-MM-DD */
  dateFrom?: string;
  /** 期間（終了）YYYY-MM-DD */
  dateTo?: string;
  /** 開始時刻 HH:MM（JSTで指定） */
  timeFrom?: string;
  /** 終了時刻 HH:MM（JSTで指定） */
  timeTo?: string;
  /** ページ番号（0始まり） */
  page?: number;
}

/** LP推移グラフの1点 */
export interface LpHistoryRow {
  /** 試合日時（DuckDB TIMESTAMP。Unixミリ秒数値文字列 or ISO文字列） */
  uploadedAt: string;
  /** 試合開始時点のLP */
  leaguePoint: number;
  /** 相手キャラクター名 */
  opponentCharacter: string;
  /** 勝敗（自分視点。round_results から算出） */
  result: 'win' | 'loss' | 'draw';
}

/** LP推移グラフのフィルター */
export interface LpHistoryFilters {
  /** 期間（開始） YYYY-MM-DD（JST） */
  dateFrom?: string;
  /** 期間（終了） YYYY-MM-DD（JST） */
  dateTo?: string;
  /** 開始時刻 HH:MM（JST） */
  timeFrom?: string;
  /** 終了時刻 HH:MM（JST） */
  timeTo?: string;
}

/** gauges JSON の1サイド分の時系列データ（ADR-048） */
export interface GaugeSideData {
  /** ラウンド内で HUD を計測できた最初の経過秒 */
  visibleFrom: number;
  /** ラウンド内で HUD を計測できた最後の経過秒 */
  visibleTo: number;
  /** ドライブを計測できたサンプル率（0〜1、1.0 に近いほど良好） */
  coverage: number;
  /** ドライブ本数の変化点列 [経過秒, 本数(0〜6)] */
  drive: [number, number][];
  /** バーンアウト期間 [開始経過秒, 終了経過秒] */
  driveBurnout: [number, number][];
  /** SAストック数の変化点列 [経過秒, ストック(0〜3)] */
  sa: [number, number][];
  /** 次ストックへの進捗の変化点列 [経過秒, 進捗(0〜1)] */
  saProgress: [number, number][];
  /** CA（クリティカルアート）表示期間 [開始経過秒, 終了経過秒] */
  saCriticalArt: [number, number][];
}

/** gauges JSON の1ラウンド分（ADR-048） */
export interface GaugeRound {
  /** ラウンド番号（1始まり） */
  round: number;
  /** ラウンド開始の動画内絶対時刻（秒） */
  roundStartTime: number;
  /** ラウンド終了の動画内絶対時刻（秒） */
  roundEndTime: number;
  /** ラウンド終了理由（next_round / match_end など） */
  endReason: string;
  /** ROUND バナーを検出できたか */
  bannerDetected: boolean;
  /** 1P 側の時系列データ */
  player1: GaugeSideData;
  /** 2P 側の時系列データ */
  player2: GaugeSideData;
}

/** gauges/{matchId}.json の内容（ADR-048） */
export interface GaugeData {
  /** YouTube動画ID */
  videoId: string;
  /** 試合ID（matches.id と一致） */
  matchId: string;
  /** 動画から検出したラウンド数 */
  detectedRoundCount?: number;
  /** Battlelog の round_results のラウンド数 */
  battlelogRoundCount?: number | null;
  /** 動画と Battlelog のラウンド数が一致したか */
  roundCountMatch?: boolean | null;
  /** ラウンド一覧 */
  rounds: GaugeRound[];
}

/** round_stats.parquet の1行（ADR-048） */
export interface RoundStatsRow {
  /** YouTube動画ID */
  videoId: string;
  /** 試合ID（matches.id と一致） */
  matchId: string;
  /** ラウンド番号（1始まり） */
  round: number;
  /** サイド（生データのまま） */
  side: 'player1' | 'player2';
  /** キャラクター名（matches に無い場合は null） */
  character: string | null;
  /** HUD 表示区間の開始（動画内絶対秒） */
  roundStartTime: number;
  /** HUD 表示区間の終了（動画内絶対秒） */
  roundEndTime: number;
  /** HUD 表示区間の長さ（秒） */
  durationSec: number;
  /** ドライブ本数の最小値 */
  driveMin: number | null;
  /** ドライブ本数の時間重み付き平均 */
  driveAvg: number | null;
  /** ドライブ本数の最終値 */
  driveEnd: number | null;
  /** 到達した最大 SA ストック数 */
  saMax: number | null;
  /** SA ストックが減少した回数 */
  saUsedCount: number | null;
  /** 計測できたサンプル率 */
  detectionCoverage: number | null;
  /** COUNTER 回数（ADR-049、未計測時は null） */
  counterCount: number | null;
  /** PUNISH COUNTER 回数（ADR-049、未計測時は null） */
  punishCounterCount: number | null;
}

/** 自分視点判定用の Battlelog サイド情報 */
export interface MatchBattlelogSides {
  /** Battlelog 1P のプレイヤー short_id */
  p1ShortId: number;
  /** Battlelog 2P のプレイヤー short_id */
  p2ShortId: number;
  /** Battlelog 1P のキャラクター名 */
  p1Character: string;
  /** Battlelog 2P のキャラクター名 */
  p2Character: string;
}

/** ヘルスチェックレスポンス */
export interface HealthResponse {
  status: 'ok' | 'error';
  environment: string;
  timestamp: string;
}
