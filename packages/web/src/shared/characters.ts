/**
 * SF6 Chapter - キャラクター名の正規化
 *
 * Battlelog は日本語名（`ルーク`）、バックラー公開統計（ADR-072）は英語名（`LUKE`）
 * を返すため、日本語名を英語の name_alpha に寄せてから照合する。
 *
 * 日本語名の一覧は `packages/local/config/character_aliases.json` と
 * Battlelog の実データ（2026-11 時点の 32 名）に基づく。
 * report-generator の `canonical_character_name` と同じ規則。
 */

/** 地域別の別名（バックラー ja-jp の name_alpha → 英語表記） */
const NAME_ALIASES: Record<string, string> = {
  GOUKI: 'AKUMA',
  VEGA: 'M. BISON',
};

/** 日本語名 → バックラーの name_alpha */
const JA_TO_CANONICAL: Record<string, string> = {
  リュウ: 'RYU',
  ケン: 'KEN',
  春麗: 'CHUN-LI',
  ガイル: 'GUILE',
  ザンギエフ: 'ZANGIEF',
  ダルシム: 'DHALSIM',
  本田: 'E.HONDA',
  エドモンド本田: 'E.HONDA',
  ブランカ: 'BLANKA',
  ジェイピー: 'JP',
  ジュリ: 'JURI',
  キンバリー: 'KIMBERLY',
  リリー: 'LILY',
  マノン: 'MANON',
  マリーザ: 'MARISA',
  ディージェイ: 'DEE JAY',
  キャミィ: 'CAMMY',
  ルーク: 'LUKE',
  ジェイミー: 'JAMIE',
  アキ: 'A.K.I.',
  豪鬼: 'GOUKI',
  ベガ: 'VEGA',
  テリー: 'TERRY',
  マイ: 'MAI',
  舞: 'MAI',
  不知火舞: 'MAI',
  サガット: 'SAGAT',
  アレックス: 'ALEX',
  ヴァイパー: 'C.VIPER',
  バイパー: 'C.VIPER',
  'C.ヴァイパー': 'C.VIPER',
  イングリッド: 'INGRID',
  エレナ: 'ELENA',
  ヤスミン: 'YASMINE',
  エド: 'ED',
  ラシード: 'RASHID',
  ボシュ: 'BOSCH',
  アルジュン: 'ARJUN',
  ティファ: 'TIFA',
};

/** 照合用のキーに正規化する（日本語名の変換・別名解決・記号と空白の除去） */
export function canonicalCharacterName(name: string): string {
  const trimmed = name.trim();
  const base = JA_TO_CANONICAL[trimmed] ?? trimmed;
  const upper = base.toUpperCase();
  const alias = NAME_ALIASES[upper] ?? upper;
  return alias.replace(/[^A-Z0-9]/g, '');
}

/** マッチアップの照合キー（自キャラ・相手キャラ・相手の入力タイプ） */
export function benchmarkKey(myCharacter: string, opponentCharacter: string, inputLabel: string): string {
  return `${canonicalCharacterName(myCharacter)}|${canonicalCharacterName(opponentCharacter)}|${inputLabel}`;
}
