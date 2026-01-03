# ADR-009: Cloudflare PagesからWorkersへの段階的移行戦略

- **ステータス**: 承認
- **決定日**: 2026-01-03
- **決定者**: kajiwara22

## 1. 議論の背景

2026年1月時点で、Cloudflareは公式ブログで以下の方針を表明している：

1. **Workersへの投資シフト**: 今後のフルスタック開発はWorkersを主軸とする
2. **PagesとWorkersの統合**: 両プラットフォームは技術的に統合が進んでおり、最終的には区別がなくなる方向
3. **Workers Static Assets**: Workersでも静的アセット配信が可能になり、Pagesの強みを取り込んでいる

参考: [Full-stack development on Cloudflare Workers](https://blog.cloudflare.com/ja-jp/full-stack-development-on-cloudflare-workers/)

### 現在の構成

```
R2 (ストレージ、非公開)
    → Pages Functions (Hono) - API
    → Pages (静的サイト) - HTML/CSS/JS
    → Access (認証)
```

### 検討すべき問題

- Pages Functionsを使い続けるべきか？
- それともWorkersに移行すべきか？
- いつ移行すべきか？

## 2. 選択肢と結論

### 結論

**現時点（2026年1月）ではPages Functionsで実装を継続し、Cloudflareの動向を見て将来的にWorkersへの移行を検討する。**

### 検討した選択肢

| ID | 選択肢 |
|----|--------|
| A | Pages Functionsで実装継続（採用） |
| B | 即座にWorkersへ移行 |
| C | 最初からWorkers + Static Assetsで実装 |

## 3. 各選択肢の比較表

| 観点 | A: Pages Functions（採用） | B: 即座にWorkers移行 | C: Workers + Static Assets |
|------|---------------------------|---------------------|----------------------------|
| 実装コスト | ○ 既存設計のまま | △ 移行作業が必要 | △ 新規設計が必要 |
| CI/CD | ◎ Git連携自動 | ○ 手動設定 | ○ 手動設定 |
| プレビュー環境 | ◎ 自動生成 | △ 手動設定 | △ 手動設定 |
| 静的アセット配信 | ◎ 自動最適化 | △ Static Assets設定 | ○ Static Assets |
| 将来性 | △ Workersが推奨 | ◎ 推奨プラットフォーム | ◎ 推奨プラットフォーム |
| マイグレーションコスト | ○ 将来的に必要 | - | - |
| 技術的負債 | △ 最小限 | - | - |
| ランタイム | ◎ workerd（同一） | ◎ workerd | ◎ workerd |
| R2 Bindings | ◎ 同一仕様 | ◎ 同一仕様 | ◎ 同一仕様 |
| Honoフレームワーク | ◎ 完全サポート | ◎ 完全サポート | ◎ 完全サポート |

## 4. 結論を導いた重要な観点

### 4.1 Pages FunctionsとWorkersの技術的同一性

Pages Functionsは内部的にWorkersと同じランタイム（workerd）を使用しており、以下が共通：

- R2 Bindings
- Honoフレームワーク
- TypeScript/JavaScript環境
- 環境変数とシークレット管理

**結論**: Pages Functionsで書いたコードは、Workersへほぼそのまま移行可能。

### 4.2 Pages独自の強み

**Git連携CI/CD**:
- `git push` で自動デプロイ
- プルリクエストごとに自動プレビュー環境生成
- Cloudflare Dashboard上での履歴管理

**静的アセット配信**:
- `dist/` ディレクトリを自動認識
- 最適化とキャッシュが自動
- カスタムドメインとHTTPS証明書の自動設定

**開発体験**:
- `wrangler pages dev` でローカル開発
- Viteなどのビルドツールとシームレス統合

### 4.3 Workers Static Assetsの成熟度

2026年1月時点では、Workers Static Assets機能は比較的新しく：

- ドキュメントが整備途上
- ベストプラクティスがまだ確立していない
- Pagesほどの自動化がない

### 4.4 本プロジェクトの要件適合性

本プロジェクトの特性：

- **単一開発者**: 複雑なCI/CDは不要だが、自動化のメリットは大きい
- **静的サイト + API**: Pagesの得意分野
- **小規模**: Workersの高度な機能は現時点で不要
- **学習目的**: Pagesの簡便さを活かして早く完成させることが優先

### 4.5 マイグレーションコストの低さ

将来的にWorkersへ移行する場合のコスト：

**変更が必要な部分**:
- `wrangler.toml` の設定
- デプロイスクリプト
- 静的アセット配信の設定（Workers Static Assetsへ）

**変更が不要な部分**:
- Honoのコード（そのまま流用可能）
- R2 Bindings（同一仕様）
- TypeScript/JavaScriptコード
- HTMLテンプレート

**見積もり**: 半日〜1日程度の作業で移行可能。

## 5. 帰結

### 5.1 トレードオフ

| メリット | デメリット |
|---------|-----------|
| Git連携CI/CDが自動 | 将来的にWorkersが推奨される |
| プレビュー環境が自動生成 | Workersへの移行作業が将来必要 |
| 静的アセット配信が最適化 | Workers独自機能は使えない |
| 開発体験が優れている | 技術的負債が若干残る |
| 早期に完成できる | - |

### 5.2 実装方針

**現時点（2026年1月〜）**:
- Cloudflare Pages + Pages Functionsで実装
- Honoフレームワークを使用
- R2 Bindingsでデータアクセス
- Cloudflare Accessで認証

**コード設計の注意点**:
- Workersへの移行を想定し、Pages固有機能への依存を最小化
- Honoのルーティングを中心に設計
- 静的アセットは `dist/` ディレクトリで管理

**マイグレーション判断基準**:

以下のいずれかに該当した場合、Workersへの移行を検討：

1. **Cloudflareの公式推奨変更**: Pages Functionsが非推奨（deprecated）になった場合
2. **Workers独自機能が必要**: Tail Workers、Trace Events、Gradual Deploymentsなど
3. **Pages制約に直面**: Pages Functionsの制約が開発を阻害した場合
4. **Workers Static Assetsの成熟**: ドキュメントとベストプラクティスが十分に整備された場合

### 5.3 マイグレーション手順（将来的に実施）

**Phase 1: 準備**
1. Workers Static Assetsのドキュメント確認
2. サンプルプロジェクトで動作検証
3. マイグレーション計画の詳細化

**Phase 2: 移行実施**
1. `wrangler.toml` の書き換え
2. 静的アセット配信設定の追加
3. デプロイスクリプトの修正
4. プレビュー環境の手動設定

**Phase 3: 検証**
1. 本番環境での動作確認
2. パフォーマンス比較
3. CI/CDパイプラインの調整

**見積もり時間**: 1日程度

### 5.4 技術的負債の評価

**負債レベル**: **低**

理由：
- Pages FunctionsとWorkersは技術的にほぼ同一
- Honoコードはそのまま流用可能
- R2 Bindingsは共通仕様
- マイグレーションコストが小さい

### 5.5 将来の見直し条件

以下の状況で本ADRを見直す：

1. **Cloudflareの公式発表**
   - Pages Functionsの非推奨化アナウンス
   - Workersへの統一方針の明確化

2. **技術的制約**
   - Pages Functionsでは実現できない機能が必要になった場合
   - パフォーマンス要件がPagesの制約を超えた場合

3. **Workers Static Assetsの成熟**
   - ドキュメントが充実し、ベストプラクティスが確立
   - Pagesと同等の自動化機能が提供

4. **プロジェクトの成長**
   - 複数開発者での協業が必要になった場合
   - より高度なCI/CD要件が発生した場合

## 6. 各選択肢の詳細説明

### 選択肢A: Pages Functionsで実装継続（採用）

```
構成:
Pages Functions (Hono)
    ↓
R2 Bindings
    ↓
Pages (静的サイト)
    ↓
Access (認証)
```

**採用理由**:
- 現時点で最も開発体験が良い
- Git連携とプレビュー環境が自動
- マイグレーションコストが低い
- 技術的負債が最小限

### 選択肢B: 即座にWorkersへ移行

```
構成:
Workers (Hono + Static Assets)
    ↓
R2 Bindings
    ↓
Access (認証)
```

**不採用理由**:
- 現時点でメリットが小さい
- CI/CDとプレビュー環境を手動設定する必要がある
- Workers Static Assetsがまだ成熟していない
- 学習コストが増加

### 選択肢C: 最初からWorkers + Static Assetsで実装

**不採用理由**:
- 選択肢Bと同様の理由
- 既に設計したPages構成を破棄する必要がある
- 将来的な方向性としては正しいが、現時点では時期尚早

## 7. 関連ADR

- [ADR-001: クラウドサービス選定](001-cloud-service-selection.md) - Cloudflare採用の理由
- [ADR-002: データストレージ・検索方式](002-data-storage-search.md) - R2 + Parquet + DuckDB-WASM
- [ADR-005: R2バケット専用APIトークン](005-r2-bucket-specific-api-token.md) - R2アクセス方法

## 参考資料

- [Full-stack development on Cloudflare Workers](https://blog.cloudflare.com/ja-jp/full-stack-development-on-cloudflare-workers/)
- [Cloudflare Pages and Workers Integration](https://blog.cloudflare.com/pages-workers-integrations-monorepos-nextjs-wrangler/)
- [Cloudflare Workers Static Assets](https://developers.cloudflare.com/workers/static-assets/)
- [Cloudflare Pages Functions](https://developers.cloudflare.com/pages/functions/)
- [Hono Documentation](https://hono.dev/)
