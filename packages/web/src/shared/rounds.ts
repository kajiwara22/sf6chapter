/**
 * SF6 Chapter - ラウンド結果（round_results）の定義と判定ロジック
 *
 * Battlelog API の round_results は各ラウンドの決着方法IDを表す（ADR-037）。
 * 値の定義・配色は sfbuff に準拠する（ADR-047）:
 *   - app/models/round.rb
 *   - app/helpers/rounds_helper.rb
 *
 * 副作用のない純関数のみを置き、Vitest でテストする（ADR-040）。
 */

/** 勝敗 */
export type RoundOutcome = 'win' | 'loss' | 'draw';

/** ラウンドの決着方法 */
export interface Round {
  /** 決着方法ID（round_results の要素） */
  id: number;
  /** 表示名（L / V / C / T / D / OD / SA / CA / P） */
  name: string;
  /** 勝敗（0 は負け、4 は引き分け、それ以外は勝ち） */
  outcome: RoundOutcome;
  /** ツールチップに表示する説明 */
  description: string;
  /** バッジの背景色 */
  backgroundColor: string;
  /** バッジの文字色 */
  textColor: string;
}

/**
 * 決着方法IDの定義（ADR-037 / sfbuff Round enum）
 *
 *   0=L(LOSS) / 1=V(通常勝利 / Vanilla KO) / 2=C(Chip KO) / 3=T(Time Up)
 *   4=D(DRAW) / 5=OD(Overdrive KO) / 6=SA(Super Art KO)
 *   7=CA(Critical Art KO) / 8=P(Perfect)
 */
export const ROUNDS: readonly Round[] = [
  { id: 0, name: 'L', outcome: 'loss', description: 'LOSS', backgroundColor: '#2D3644', textColor: '#C7C7C8' },
  { id: 1, name: 'V', outcome: 'win', description: '通常勝利', backgroundColor: '#2C003E', textColor: '#E297FF' },
  { id: 2, name: 'C', outcome: 'win', description: 'Chip KO', backgroundColor: '#003A3D', textColor: '#9BFAFF' },
  { id: 3, name: 'T', outcome: 'win', description: 'Time Up', backgroundColor: '#00123E', textColor: '#97B4FF' },
  { id: 4, name: 'D', outcome: 'draw', description: 'DRAW', backgroundColor: '#363636', textColor: '#CBCBCB' },
  { id: 5, name: 'OD', outcome: 'win', description: 'Overdrive KO', backgroundColor: '#113D00', textColor: '#BFFFA6' },
  { id: 6, name: 'SA', outcome: 'win', description: 'Super Art KO', backgroundColor: '#5F003A', textColor: '#FF93D5' },
  { id: 7, name: 'CA', outcome: 'win', description: 'Critical Art KO', backgroundColor: '#442600', textColor: '#FFD097' },
  { id: 8, name: 'P', outcome: 'win', description: 'Perfect', backgroundColor: '#605C00', textColor: '#FFFB97' },
];

/** 未知の決着方法IDを表示するためのフォールバック */
const UNKNOWN_ROUND = {
  name: '?',
  outcome: 'draw',
  description: '不明',
  backgroundColor: '#363636',
  textColor: '#CBCBCB',
} as const;

const ROUND_BY_ID: ReadonlyMap<number, Round> = new Map(ROUNDS.map((r) => [r.id, r]));

/**
 * 決着方法IDから Round を取得する。未知のIDは "?" を返す。
 */
export function getRound(id: number): Round {
  return ROUND_BY_ID.get(id) ?? { id, ...UNKNOWN_ROUND };
}

/**
 * round_results のJSON配列文字列を数値配列に変換する。
 * NULL・空文字・不正なJSON・配列以外は空配列を返す。
 */
export function parseRoundIds(roundResultsJson: string | null | undefined): number[] {
  if (!roundResultsJson) return [];

  let parsed: unknown;
  try {
    parsed = JSON.parse(roundResultsJson);
  } catch {
    return [];
  }

  if (!Array.isArray(parsed)) return [];

  const ids: number[] = [];
  for (const value of parsed) {
    const n = Number(value);
    if (Number.isFinite(n)) ids.push(n);
  }
  return ids;
}

/**
 * 勝利ラウンド数を数える。
 *
 * 決着方法IDは 0（LOSS）のみが負けであり、それ以外（1〜8）は 0 より大きいため
 * 勝ちラウンドとして数える（ADR-037）。新しい勝利種別が追加されても 0 以外なら
 * 自動的に対応できる。
 */
export function countRoundWins(roundResultsJson: string | null | undefined): number {
  return parseRoundIds(roundResultsJson).filter((id) => id > 0).length;
}

/**
 * 自分視点・相手視点の round_results から勝敗を判定する。
 * 勝利ラウンド数が多い方を勝ちとし、同数なら引き分け（ADR-037）。
 */
export function determineResultFromRounds(
  myRounds: string | null | undefined,
  oppRounds: string | null | undefined,
): RoundOutcome {
  const myWins = countRoundWins(myRounds);
  const oppWins = countRoundWins(oppRounds);

  if (myWins > oppWins) return 'win';
  if (myWins < oppWins) return 'loss';
  return 'draw';
}
