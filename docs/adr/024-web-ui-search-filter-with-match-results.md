# ADR-024: Web UI 検索フィルター - Battlelog 勝敗結果対応

## ステータス

承認・実装完了（Approved & Implemented） - 2026-02-17
実装コミット: `4e96b18`

## 文脈

ADR-021 で YouTube チャプターと Battlelog リプレイのマッピングを実装し、各対戦に `player1_result` / `player2_result` の勝敗情報が付与された。

Web UI の検索フィルターをこの新しい勝敗データに対応させ、ユーザーが以下のユースケースで対戦を検索できるようにする必要がある：

1. **単キャラ検索**: 「特定キャラが勝った試合」「特定キャラが負けた試合」
2. **対戦カード検索**: 「特定キャラA vs 特定キャラB の対戦全て」
3. **複合検索**: 「対戦カード + 勝敗フィルター」で「キャラAが勝ったキャラBとの対戦」

### 要件

1. **単キャラ検索**
   - キャラクター1 を指定
   - 勝敗フィルター（全て / 勝利 / 敗北）を適用
   - 相手キャラは問わない

2. **対戦カード検索**
   - キャラクター1 + キャラクター2 を指定
   - 勝敗フィルターは「キャラクター1 の結果」に限定
   - 順序は問わない（GOUKI vs JP = JP vs GOUKI）

3. **UI/UX**
   - ユーザーが 2つの検索モードを直感的に切り替えられる
   - 検索ロジックはクライアント側で実行（DuckDB-WASM）
   - 既存フォームに最小限の変更で対応

4. **検索対象**
   - Battlelog マッピング失敗レコード（`result=NULL`）は勝敗フィルター指定時には除外
   - 勝敗フィルター未指定時は全レコード表示

5. **Vanilla JS**
   - React / Vue などのフレームワークを使用しない
   - 純粋な DOM 操作で UI 更新を実装

## 決定

Web UI 検索フィルターを以下の仕様で実装する。

### 1. 検索モードの分類

#### モード A: 単キャラ検索（デフォルト）

```typescript
interface SingleCharacterSearch {
  character: string;        // キャラクター1（必須）
  character2?: undefined;   // キャラクター2は指定しない
  playerResult?: 'win' | 'loss';
}
```

**SQL フィルター**:
```sql
WHERE (
  (player1.character = ? AND player1.result = ?)
  OR
  (player2.character = ? AND player2.result = ?)
)
```

**例**: GOUKI が勝った試合
```sql
WHERE (
  (player1.character = 'GOUKI' AND player1.result = 'win')
  OR
  (player2.character = 'GOUKI' AND player2.result = 'win')
)
```

#### モード B: 対戦カード検索

```typescript
interface MatchupSearch {
  character: string;        // キャラクター1（必須）
  character2: string;       // キャラクター2（必須）
  playerResult?: 'win' | 'loss';  // キャラクター1 の結果
}
```

**SQL フィルター**:
```sql
WHERE (
  (player1.character = ? AND player2.character = ? AND player1.result = ?)
  OR
  (player1.character = ? AND player2.character = ? AND player2.result = ?)
)
```

**例**: GOUKI vs JP で GOUKI が勝った試合
```sql
WHERE (
  (player1.character = 'GOUKI' AND player2.character = 'JP' AND player1.result = 'win')
  OR
  (player1.character = 'JP' AND player2.character = 'GOUKI' AND player2.result = 'win')
)
```

### 2. UI/UX デザイン

#### 2-1. フォーム構造（HTML）

**キャラクター2 フィールドの表示制御**:
- キャラ1 のみ指定 → 単キャラモード
- キャラ1 + キャラ2 指定 → 対戦カードモード

**勝敗ラベルの動的更新**:
- キャラ1 が選択されたら、ラベルを「勝敗 ({キャラ1}の)」に更新
- キャラ1 がクリアされたら、ラベルを「勝敗」に戻す

```html
<!-- フォーム例 -->
<div class="form-group">
  <label for="character-select">キャラクター1</label>
  <select id="character-select" name="character">
    <option value="">すべて</option>
    <!-- キャラクター一覧を動的に生成 -->
  </select>
</div>

<div class="form-group">
  <label for="character-select-2">キャラクター2（オプション）</label>
  <select id="character-select-2" name="character2">
    <option value="">指定しない</option>
    <!-- キャラクター一覧を動的に生成 -->
  </select>
</div>

<div class="form-group">
  <label for="player-result">
    勝敗<span id="player-result-context"></span>
  </label>
  <select id="player-result" name="playerResult">
    <option value="">すべて</option>
    <option value="win">勝利</option>
    <option value="loss">敗北</option>
  </select>
</div>
```

#### 2-2. キャラクター1 変更時の動的更新

```javascript
// キャラ1 セレクト変更時
document.getElementById('character-select').addEventListener('change', (e) => {
  const selectedChar = e.target.value;
  const contextSpan = document.getElementById('player-result-context');

  if (selectedChar) {
    contextSpan.textContent = ` (${selectedChar}の)`;
  } else {
    contextSpan.textContent = '';
  }
});
```

### 3. クライアント側の検索ロジック

#### 3-1. SQL 生成関数

```typescript
function generateMatchFilter(filters: SearchFilters): string {
  let conditions: string[] = [];

  if (!filters.character) {
    // キャラクター1 が未指定の場合、他のフィルターも無視
    return '';
  }

  const char1 = filters.character;
  const resultFilter = filters.playerResult ? `AND player1.result = '${filters.playerResult}'` : '';

  if (filters.character2) {
    // 対戦カード検索モード
    const char2 = filters.character2;
    conditions.push(`
      (player1.character = '${char1}' AND player2.character = '${char2}' ${resultFilter})
      OR
      (player1.character = '${char2}' AND player2.character = '${char1}' AND player2.result = '${filters.playerResult}')
    `);
  } else {
    // 単キャラ検索モード
    if (filters.playerResult) {
      conditions.push(`
        (player1.character = '${char1}' AND player1.result = '${filters.playerResult}')
        OR
        (player2.character = '${char1}' AND player2.result = '${filters.playerResult}')
      `);
    } else {
      conditions.push(`
        (player1.character = '${char1}')
        OR
        (player2.character = '${char1}')
      `);
    }
  }

  return conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
}
```

#### 3-2. バリデーション

```typescript
function validateSearchFilters(filters: SearchFilters): {valid: boolean; error?: string} {
  // キャラクター1 は必須
  if (!filters.character) {
    return {
      valid: false,
      error: 'キャラクター1を選択してください'
    };
  }

  // キャラクター2 のみの指定は不可
  if (!filters.character && filters.character2) {
    return {
      valid: false,
      error: 'キャラクター2 を指定する場合、キャラクター1 も指定してください'
    };
  }

  return {valid: true};
}
```

### 4. SearchFilters 型の拡張

現在の型定義：
```typescript
export interface SearchFilters {
  character?: string;
  character2?: string;
  playerResult?: 'win' | 'loss';
  videoTitle?: string;
  dateFrom?: string;
  dateTo?: string;
  sortBy?: SortOrder;
  limit?: number;
}
```

**変更**: そのまま使用（`character2` の有無で自動判定）

モード指定を明示的に管理する必要はなく、以下で判定：
- `character` のみ → 単キャラモード
- `character && character2` → 対戦カードモード

### 5. Parquet スキーマ確認

実際のデータ構造（DuckDB で確認済み）:

```
player1: STRUCT("character" VARCHAR, characterRaw VARCHAR, result VARCHAR, side VARCHAR)
player2: STRUCT("character" VARCHAR, characterRaw VARCHAR, result VARCHAR, side VARCHAR)
```

**結果データの状態**:
- 現在: 369 件中 20 件に `result` が入力（Battlelog マッピング完了分）
- NULL の場合: Battlelog マッピング失敗、または未実行
- 勝敗フィルター指定時: `result IS NOT NULL` で自動的に絞り込み

### 6. 実装上の考慮点

#### 6-1. Vanilla JS での UI 更新

フレームワークを使わないため、以下のリスナー実装が必要：

1. **キャラクター1 選択変更時**
   - `player-result-context` のラベルを動的更新
   - 検索フォーム送信時の SQL フィルター生成に反映

2. **キャラクター2 選択変更時**
   - 検索モード切り替え判定（単キャラ ↔ 対戦カード）
   - SQL フィルター生成ロジック切り替え

3. **フォーム送信時**
   - バリデーション実行
   - DuckDB-WASM で SQL 実行
   - 結果表示

#### 6-2. SQL インジェクション対策

現在の実装：フォームから取得する値を直接 SQL に埋め込んでいる可能性あり。

**対策**:
- キャラクター名は既知の値セット（ドロップダウン選択肢）のみ許可
- 入力値のバリデーション追加
- DuckDB パラメータ化クエリの使用検討（将来）

#### 6-3. 状態管理

ユーザーが検索条件を切り替える際の状態保持：

```
単キャラ (GOUKI, 勝敗=勝利)
  ↓ (キャラ2に JP を指定)
対戦カード (GOUKI, JP, 勝敗=勝利)
  ↓ (キャラ2 をクリア)
単キャラ (GOUKI, JP=[], 勝敗=勝利)
```

→ キャラ2 をクリアすると自動的に単キャラモードに戻る
→ 勝敗フィルターは保持される

## 検証方法

### DuckDB で実行確認（既実施）

```sql
-- GOUKI が勝った試合全て
SELECT COUNT(*) FROM read_parquet('./.uncommit/matches.parquet')
WHERE (
  (player1.character = 'GOUKI' AND player1.result = 'win')
  OR
  (player2.character = 'GOUKI' AND player2.result = 'win')
);
-- 結果: 2

-- GOUKI vs JP（順序問わず）
SELECT COUNT(*) FROM read_parquet('./.uncommit/matches.parquet')
WHERE (
  (player1.character = 'GOUKI' AND player2.character = 'JP')
  OR
  (player1.character = 'JP' AND player2.character = 'GOUKI')
);
-- 結果: 37

-- GOUKI vs JP で GOUKI が勝った
SELECT COUNT(*) FROM read_parquet('./.uncommit/matches.parquet')
WHERE (
  (player1.character = 'GOUKI' AND player2.character = 'JP' AND player1.result = 'win')
  OR
  (player1.character = 'JP' AND player2.character = 'GOUKI' AND player2.result = 'win')
);
-- 結果: 2
```

### Web UI 実装後の検証

1. **単キャラ検索**
   - キャラ1 のみ選択 → ラベルが「勝敗 ({キャラ名}の)」に更新
   - 勝敗フィルター指定 → 結果が正しくフィルターされる

2. **対戦カード検索**
   - キャラ1 + キャラ2 選択 → 順序に関わらず対戦が検出
   - 勝敗フィルター指定 → キャラ1 の結果でフィルター

3. **エッジケース**
   - 同キャラ対戦（例: JP vs JP）も正しく検出
   - キャラ2 クリア時に単キャラモードに戻る
   - 勝敗データなしレコードは適切に除外

## トレードオフと帰結

### メリット

- ✅ **ユースケースに最適**: 単キャラ検索と対戦カード検索の 2 モードで、対戦見返しのユースケースをカバー
- ✅ **UI が直感的**: キャラ2 フィールド表示制御で、モード切り替えが暗黙的
- ✅ **実装が軽量**: 新しい状態管理不要、SQL フィルター生成で実現
- ✅ **検証済み**: DuckDB クエリで期待通りの結果確認済み

### デメリット

- ⚠️ **SQL 生成ロジック複雑化**: 複数条件の OR 結合で可読性低下の可能性
- ⚠️ **SQL インジェクション**: フレームワーク使用時より対策が必要
- ⚠️ **勝敗データの依存**: ADR-021 のマッピング完了に依存（現在 20/369 件のみ）

### 将来の改善

1. **複数結果フィルター**
   - 「GOUKI が勝った AND JP が負けた」的な複合条件も対応可能に拡張

2. **SQL パラメータ化**
   - DuckDB-WASM のパラメータ化クエリ API 活用でセキュリティ向上

3. **キャッシング**
   - 検索結果をクライアント側でキャッシュして、重複検索を高速化

4. **ユーザー体験の改善**
   - 検索履歴の保存
   - 「お気に入りの対戦カード」機能

## 実装ファイル

### 修正対象ファイル

- **packages/web/src/client/components/SearchForm.ts**
  - キャラ1 変更時のリスナー追加
  - ラベル動的更新ロジック実装

- **packages/web/src/client/search.ts**
  - SQL フィルター生成関数の実装
  - バリデーション関数の追加
  - 対戦カードモード対応

- **packages/web/src/server/routes/pages.tsx**
  - HTML フォーム修正（キャラ2 ラベル更新、span 追加）

- **packages/web/src/shared/types.ts**
  - 型定義は既存のまま（character2 フィールドで判定）

### 新規作成ファイル

不要（既存構造内で実装）

## 実装完了

### 実装内容

#### 1. UI コンポーネント修正
- ✅ キャラクター1 変更時にラベルを「勝敗 ({キャラ名}の)」に動的更新
- ✅ キャラクター2（オプション）ラベルを追加
- ✅ 勝敗ラベル内に動的コンテキストスパン追加

#### 2. 検索ロジック拡張
- ✅ 単キャラ検索モード：キャラが勝った/負けた試合を検索
- ✅ 対戦カード検索モード：キャラ1 vs キャラ2 の対戦を検索
- ✅ 対戦カード検索時：キャラ1 の結果でフィルター
- ✅ パラメータ化クエリで SQL インジェクション対策

#### 3. 修正ファイル
- `packages/web/src/client/types.ts` - DOM_IDS 追加
- `packages/web/src/client/components/SearchForm.ts` - リスナー実装
- `packages/web/src/client/search.ts` - SQL 生成ロジック修正
- `packages/web/src/server/routes/pages.tsx` - HTML 修正

### 検証済み

- ✅ 単キャラ検索（勝敗フィルター有無）
- ✅ 対戦カード検索（順序問わず検出）
- ✅ キャラ2 クリア時のモード切り替え
- ✅ ラベル動的更新
- ✅ Cloudflare Pages デプロイ後の動作確認

## 参考資料

- ADR-021: YouTube チャプターと Battlelog リプレイのマッピング実装
- DuckDB-WASM: https://duckdb.org/docs/api/wasm
- Parquet スキーマ: `packages/web/src/shared/types.ts` の Match インターフェース
