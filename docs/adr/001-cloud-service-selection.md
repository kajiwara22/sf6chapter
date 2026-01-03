# ADR-001: クラウドサービス選定

- **ステータス**: 承認
- **決定日**: 2024-12-28
- **決定者**: kajiwara22

## 1. 議論の背景

SF6（ストリートファイター6）の配信動画から対戦シーンを自動検出し、YouTubeチャプターを生成するシステムを構築する。

### 要件

- YouTube配信がアーカイブになったタイミングで自動的に処理を開始したい
- 配信頻度は1日1回〜数回程度、動画の長さは30分〜1時間
- 処理結果を保存し、クラウド環境で閲覧できるようにしたい
- 特定のキャラクターとの対戦を検索できるようにしたい
- 生成されたチャプターはYouTubeに自動反映したい
- コストを最小限に抑えたい
- ローカルPCは家族共用のため常時稼働は保証できない

### 技術的前提

- 既存のPythonコードがあり、yt-dlp、OpenCV、Gemini APIを使用
- 動画のダウンロードと解析は計算リソースを消費する重い処理

## 2. 選択肢と結論

### 結論

**Google Cloud（検知・キュー） + Cloudflare（ストレージ・閲覧UI）のハイブリッド構成**を採用する。

### 検討した選択肢

| ID | 選択肢 |
|----|--------|
| A | AWS完結構成 |
| B | Google Cloud完結構成 |
| C | Cloudflare完結構成 |
| D | Google Cloud + Cloudflare ハイブリッド構成 |

## 3. 各選択肢の比較表

| 観点 | A: AWS | B: Google Cloud | C: Cloudflare | D: GCP + CF（採用） |
|------|--------|-----------------|---------------|---------------------|
| 月額コスト | 約$0.5〜1 | $0 | $0 | $0 |
| YouTube/Gemini APIとの親和性 | △ | ◎ | ○ | ◎ |
| メッセージキューの信頼性 | ◎ SQS 14日保持 | ◎ Pub/Sub 7日保持 | ○ Queues 4日保持 | ◎ Pub/Sub 7日保持 |
| 静的サイト構築の容易さ | ○ | ○ | ◎ | ◎ |
| 認証設定の簡単さ | △ Cognito複雑 | ○ Firebase Auth | ◎ Access最も簡単 | ◎ Access |
| ストレージ無料枠 | 5GB (S3) | 5GB (GCS) | 10GB (R2) | 10GB (R2) |
| エグレス（転送量）コスト | 有料 | 有料 | 無料 | 無料 |
| 学習効果 | 低（経験あり） | 中 | 中 | 高（2つのクラウド） |
| 日本語ドキュメント | ◎ | ◎ | △ | ○ |

## 4. 結論を導いた重要な観点

### 4.1 コスト最小化

ローカルPCで重い処理を実行することで、クラウド側の計算コストを$0に抑えられる。Cloudflare R2のエグレス無料は、動画ログの閲覧時に大きなメリット。

### 4.2 検知漏れ防止

ローカルPCが常時稼働できない制約があるため、クラウド側でメッセージキューを持つことが必須。Cloud Pub/Subの7日間保持により、PCがオフの間も検知漏れを防げる。

### 4.3 既存エコシステムとの統合

- Gemini API（Google）を既に使用
- YouTube Data API（Google）でチャプター更新
- Google Cloudを使うことで認証・プロジェクト管理が一元化

### 4.4 認証の簡便さ

Cloudflare Accessは数クリックで「特定メールアドレスのみアクセス可能」を設定できる。AWS CognitoやGoogle Cloud IAPと比較して圧倒的にシンプル。

### 4.5 学習目的

年末の学習も兼ねており、2つのクラウドプラットフォームを実践的に経験することで、それぞれの特性やサービス間連携のパターンを習得できる。

## 5. 帰結

### 5.1 トレードオフ

| メリット | デメリット |
|---------|-----------|
| コスト$0で運用可能 | 管理コンソールが2箇所に分散 |
| 各サービスの強みを活かせる | 認証情報の管理が複雑化（GCP SA、R2トークン、YouTube OAuth、Gemini APIキー） |
| 検知漏れなし | トラブルシュート時の切り分けが必要 |
| 学習効果が高い | 初期構築の学習コスト |

### 5.2 影響

- **運用**: 2つのダッシュボード（Google Cloud Console、Cloudflare Dashboard）を確認する必要がある
- **監視**: エラー発生時にどちらのサービスが原因か切り分けが必要
- **シークレット管理**: GCP Secret Managerに集約するか、各サービスの環境変数に分散するか別途検討が必要

### 5.3 将来の見直し条件

以下の場合、アーキテクチャの見直しを検討する：

1. **配信頻度が大幅に増加**（1日10回以上）した場合
   - Pub/Subのコストが無料枠を超える可能性
   - ローカルPCの処理が追いつかない可能性

2. **複数人での利用**を想定する場合
   - 認証・認可の要件が複雑化
   - データの分離が必要

3. **ローカルPCが完全に使えなくなった**場合
   - クラウド側で全処理を実行する構成に移行
   - ECS Fargate / Cloud Runの導入を検討

4. **Google Cloud / Cloudflareの料金体系が変更**された場合
   - 無料枠の縮小や廃止
   - 新しい課金体系の導入

## 6. 各選択肢の説明

### 選択肢A: AWS完結構成

```
EventBridge Scheduler → Lambda → SQS → ローカルPC
                                         ↓
                              S3 → CloudFront → Cognito → ブラウザ
```

AWS経験があるため構築は容易だが、以下の理由で不採用：
- YouTube/Gemini APIとの統合で追加の設定が必要
- S3のエグレスコストが発生
- 学習効果が単一クラウドに限定される

### 選択肢B: Google Cloud完結構成

```
Cloud Scheduler (2時間毎) → Cloud Functions → Pub/Sub → ローカルPC
                                                           ↓
                              Cloud Storage → Firebase Hosting → Firebase Auth → ブラウザ
```

YouTube/Gemini APIとの親和性は高いが、以下の理由で不採用：
- Firebase Authの設定がCloudflare Accessより複雑
- Cloud Storageのエグレスコストが発生
- 学習効果が単一クラウドに限定される

### 選択肢C: Cloudflare完結構成

```
Workers Cron → Workers → Queues → ローカルPC
                                     ↓
                          R2 → Pages → Access → ブラウザ
```

開発体験とコストは優れているが、以下の理由で不採用：
- Queuesのメッセージ保持期間が4日と短い
- Workers独自の制約（CPU時間制限等）の学習コスト
- YouTube APIとの統合がGoogle Cloudほど自然でない

### 選択肢D: Google Cloud + Cloudflare ハイブリッド構成（採用）

```
Cloud Scheduler (2時間毎) → Cloud Functions → Pub/Sub → ローカルPC
                                                           ↓
                                    R2 → Pages Functions → Access → ブラウザ
```

両サービスの強みを組み合わせた構成：
- **Google Cloud**: YouTube/Gemini APIとの親和性、Pub/Subの信頼性
- **Cloudflare**: R2の無料エグレス、Accessの簡便さ、Pagesの開発体験

#### Cloudflare PagesとWorkersの選択

**採用: Cloudflare Pages + Pages Functions**

Cloudflare側のWebアプリケーション構築において、Pages FunctionsとWorkersの2つの選択肢があった：

| 観点 | Pages Functions（採用） | Workers |
|------|------------------------|---------|
| 静的アセット配信 | ◎ 自動最適化 | ○ Static Assets設定必要 |
| CI/CD | ◎ Git連携自動 | △ 手動設定 |
| プレビュー環境 | ◎ PR毎に自動生成 | △ 手動設定 |
| 開発体験 | ◎ Vite統合簡単 | ○ |
| 将来性 | △ Workersが推奨 | ◎ 公式推奨プラットフォーム |
| マイグレーションコスト | - | ○ 低（同一ランタイム） |

**決定理由**:
- 現時点（2026年1月）では Pages Functions が最も開発体験が良い
- Workers への移行コストは低い（同一ランタイム、Honoコード流用可能）
- Git連携とプレビュー環境の自動化が強力
- 将来的にWorkersへ移行する可能性を考慮し、Pages固有機能への依存を最小化

詳細は[ADR-009: Cloudflare PagesからWorkersへの段階的移行戦略](009-cloudflare-pages-to-workers-migration-strategy.md)を参照。

---

## 参考資料

- [Google Cloud Pub/Sub ドキュメント](https://cloud.google.com/pubsub/docs)
- [Cloudflare R2 ドキュメント](https://developers.cloudflare.com/r2/)
- [Cloudflare Pages Functions ドキュメント](https://developers.cloudflare.com/pages/functions/)
- [Cloudflare Access ドキュメント](https://developers.cloudflare.com/cloudflare-one/policies/access/)
