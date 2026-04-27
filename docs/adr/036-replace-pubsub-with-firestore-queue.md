# ADR-036: Pub/Sub キューを Firestore キューに置き換える

## ステータス

承認済み - 2026-04-27

## 文脈

### 現状のアーキテクチャ

現在のメッセージング構成は以下のとおり：

```
Cloud Scheduler (2時間毎)
    → Cloud Functions (check-new-video)
        → Firestore に status="queued" を書き込み
        → Pub/Sub に動画メタデータを発行

ローカルPC
    → Pub/Sub から Pull（--mode once / --mode daemon）
    → 動画処理を実行
```

Cloud Function では Firestore への書き込みと Pub/Sub への発行を両方行っており、ローカルPC 側は Pub/Sub からメッセージを取り出して処理する。

### 課題

#### 運用の煩雑さ

- Pub/Sub のサブスクリプション管理、認証設定（OAuth2）が必要
- Cloud Console 上でキューの状態（未処理メッセージ数）が直感的に確認しにくい
- Firestore と Pub/Sub という2つのシステムに状態が分散しており、整合性の把握が難しい

#### `--mode once` の信頼性

実際の主な使い方は `--mode once`（Pub/Sub から Pull して処理）か、特定の動画を直接指定する `--mode test --video-id` の2パターンに絞られる。

```python
def run_once(self) -> None:
    self.subscriber.pull_messages(
        callback=self.process_video,
        max_messages=10,
        timeout=30.0,  # 30秒待ってメッセージがなければ終了
    )
```

- Pull は即座に返らないことがある（タイミング依存）
- `timeout=30.0` の間にメッセージが来なければ何も処理されずに終了する
- Ack 漏れが起きると再配信され、Firestore の重複チェックにより「処理済み」として誤スキップされる可能性がある

#### 7日間保持の実質的な不要性

Pub/Sub を採用した当初の理由はローカルPC 長期停止中の取りこぼし防止（7日間メッセージ保持）だったが、実運用では PC が停止するシナリオはほとんど発生していない。

### 要件

- `--mode once` で確実に未処理動画を処理できること
- デバッグ時に「現在キューに何件あるか」が直接確認できること
- 既存の `--mode test --video-id` のフローは変更しないこと

## 決定

### Pub/Sub を廃止し、Firestore をキューとして使う

Cloud Function がすでに Firestore に `status="queued"` で書き込んでいる。この情報を直接利用してローカルPC 側がキューとして扱う構成に変更する。

#### 新しいアーキテクチャ

```
Cloud Scheduler (2時間毎)
    → Cloud Functions (check-new-video)
        → Firestore に status="queued" を書き込む（変更なし）
        → Pub/Sub への発行を削除

ローカルPC
    → Firestore の status="queued" なレコードをクエリして処理
```

#### 変更箇所

**Cloud Function 側（`packages/gcp-functions/check-new-video/main.py`）**

- `publish_to_pubsub()` の呼び出しを削除
- Pub/Sub 関連のクライアント・設定を削除
- Firestore への書き込みは変更なし

**ローカルPC 側（`packages/local/`）**

- `src/pubsub.py` の代わりに Firestore をキューとして扱うロジックを実装
- `run_once()` を「Firestore の `queued` レコードを取得して処理」に変更
- `run_forever()` を「定期的に Firestore をポーリング」に変更
- `src/pubsub.py` は削除または空実装に

#### デバッグの改善

Firestore コンソールで `processed_videos` コレクションを `status="queued"` でフィルタすれば、未処理動画の一覧と件数が即座に確認できる。

## 選択肢の比較

### 選択肢A: Firestore キューに置き換える（採用）

| 観点 | 評価 |
|------|------|
| 運用コスト | ◎ Pub/Sub の管理が不要になる |
| デバッグのしやすさ | ◎ Firestore コンソールで状態が一目瞭然 |
| 信頼性 | ○ Pull タイミングに依存しない |
| 変更量 | ○ 小〜中程度（Cloud Function 側は削除のみ） |
| 7日間保持 | △ 消えるが実運用では不要 |
| Firestore コスト | △ ポーリングによる読み取りが増加（ただし微小） |

### 選択肢B: Pub/Sub は残して `--mode once` の挙動を改善する

| 観点 | 評価 |
|------|------|
| 運用コスト | ✕ Pub/Sub の管理は変わらない |
| デバッグのしやすさ | △ Pull 挙動は改善されるが状態分散は解消しない |
| 信頼性 | ○ timeout 等のチューニングで改善可能 |
| 変更量 | ○ ローカル側のみ変更 |
| 7日間保持 | ◎ 引き続き保持される |

### 選択肢C: `--mode once` に `--video-id` を渡す方式に統一する

| 観点 | 評価 |
|------|------|
| 運用コスト | ○ Pub/Sub を廃止できる |
| デバッグのしやすさ | ◎ 処理対象が明示的 |
| 信頼性 | ◎ 直接処理なので失敗しない |
| 変更量 | △ Cloud Function から ローカルPC を呼び出す仕組みが新たに必要 |
| 自動化 | ✕ Cloud Function → ローカルPC の自動連携が難しい |

### 結論

選択肢A を採用。Firestore はすでに状態管理に使用しており、これをキューとして活用することで Pub/Sub を完全に排除できる。コードの変更量が最小限で済み、デバッグ性が大幅に改善される。

## トレードオフと帰結

### メリット

- Pub/Sub のサブスクリプション・認証管理が不要になる
- Firestore コンソールでキュー状態を直接確認できる（`status="queued"` フィルタ）
- 状態管理が Firestore に一元化され、整合性が把握しやすくなる
- `--mode once` が Pull タイミングに左右されなくなる

### デメリット・注意点

- Pub/Sub の7日間メッセージ保持がなくなる（実運用上は許容範囲）
- Firestore へのポーリングによる読み取りが増加するが、実行頻度を考えると無視できるレベル
- Firestore の `queued` レコードが処理失敗時に残り続ける場合、再試行ロジックが必要（既存の `status` 管理で対応済み）

### 将来の見直し条件

- PC が長期停止するような運用変化が生じた場合、Pub/Sub の再導入を検討する
- 処理対象動画数が大幅に増加した場合、Firestore ポーリングの効率化を検討する

## 実装チェックリスト

- [x] `packages/gcp-functions/check-new-video/main.py`: `publish_to_pubsub()` の呼び出し削除
- [x] `packages/gcp-functions/check-new-video/main.py`: Pub/Sub 関連コードの削除
- [x] `packages/local/src/pubsub.py`: `PubSubSubscriber` の利用を `main.py` から除去（`pubsub/` モジュール自体は残存）
- [x] `packages/local/main.py`: `run_once()` を Firestore クエリベースに変更
- [x] `packages/local/main.py`: `run_forever()` を Firestore ポーリングベースに変更（`POLL_INTERVAL_SEC` 環境変数で間隔制御）
- [ ] 動作確認: `--mode once` で Firestore の `queued` レコードが処理されること
- [ ] 動作確認: 処理済み後に `status` が `completed` に更新されること

## 関連 ADR

- [ADR-006: Firestoreによる処理済み動画の追跡](006-firestore-for-duplicate-prevention.md) - Firestore の状態管理設計
- [ADR-007: Cloud Schedulerの実行間隔最適化](007-cloud-scheduler-interval-optimization.md) - Cloud Function の実行頻度設計
