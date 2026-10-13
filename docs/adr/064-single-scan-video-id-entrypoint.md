# ADR-064: 動画ID指定による本線フローの単発実行（1回走査）

## ステータス

採用 - 2026-10-14

## 文脈

### 発端

本線パイプライン `SF6ChapterProcessor.process_video()` は、検出（テンプレートマッチング）と同時にゲージ計測（ADR-048）・カウンター計測（ADR-049）を同じデコードループで実行している。つまり**動画の走査は1回**で、検出・ゲージ・カウンターがすべて揃う。

一方、動画を個別に処理するための既存の入口は次の2つしかなかった。

1. `--mode once` / `--mode daemon`: Firestore のキュー（`queued` の動画）をまとめて処理する。特定の1本だけを処理することはできない
2. `--mode test --test-step all --video-id <id>`: テスト用の個別ステップ実行。`test_detection()` は `TemplateMatcher` を新規生成するが、ゲージ／カウンターの analyzer を配線していないため、**この走査ではゲージ・カウンターが計測されない**

このため、テスト経路で1本を処理する場合は、`--test-step all` の後に `scripts/analyze_counters.py` などで**もう一度フルデコード**する必要があり、動画の走査が2回になっていた。32分の動画で追加約6分のデコードが発生する。

### 要件

- 動画IDを指定して、キューを介さずに1本だけを**本線と同じコードパス**で処理したい
- 検出・ゲージ・カウンターは**1回の走査**で計測したい
- 検証・再処理のために、Firestore を参照・更新せずに繰り返し実行できるようにしたい

## 決定事項

**通常モードに `--video-id` を追加し、`process_video()` を呼ぶ単発実行の入口を設ける。**

あわせて以下を追加する。

- `--no-firestore`: Firestore の参照（`is_completed`）・更新（`processing` / `completed` / `failed`）を行わない。`--video-id` との併用を必須とする（キュー処理 `run_once` / `run_forever` は Firestore が必須のため）
- `--cookie-path`: yt-dlp に渡す cookie ファイル（デフォルト `./cookie/cookie.txt`。存在しない場合は無視）
- `process_video(..., skip_download_if_exists=True)`: 単発実行では既存のダウンロード済みファイルを再利用する

`scripts/analyze_gauges.py` / `scripts/analyze_counters.py` は**チューニング・バックフィル用として残す**。検出＋Gemini 認識を再実行せずに計測だけを回せる価値があるため。

### 実装

- `SF6ChapterProcessor.__init__(use_firestore=True)`: `False` の場合は `FirestoreClient` を生成しない（`self.firestore = None`）
- `process_video()`: 各 Firestore 呼び出しを `if self.firestore:` でガード
- `run_video_by_id(processor, video_id, cookie_path)`: YouTube API から動画情報を取得し、cookie を設定して `process_video()` を呼ぶ
- `main()`: `--video-id` 指定時は `run_video_by_id()` を実行して終了

## 結果

### 良い点

- 動画IDを指定した1本の処理が、検出・ゲージ・カウンター・認識・YouTube更新・R2アップロードまで**1回の走査**で完結する
- 本線と同一のコードパス（`_detect_and_recognize` → `_save_gauge_data` / `_save_counter_data`）を通るため、テスト経路との差分（`characters` 未伝播など）による計測漏れが起きない
- `--no-firestore` により、`completed` 状態に影響されず再実行・検証できる

### 制約・トレードオフ

- `--no-firestore` 指定時は処理状態が Firestore に記録されないため、本番の重複防止・進捗管理の対象外になる（検証用途に限定する）
- 単発実行は1本ずつしか処理できない（複数本は従来どおり `--mode once` / `daemon`）

### 検証

`ovM5BMIsyKw`（32分37秒）で、従来の2回走査（`--test-step all` ＋ `scripts/analyze_counters.py`）と本導線（1回走査）の結果を比較した。

- 検出13試合、Battlelog 13/13 マッチ、YouTubeチャプター13件、`round_stats` 68行は一致
- ゲージ本体データ（ドライブ・SA・体力・回復可能ダメージ・SAクリティカルアート・ラウンド数）は一致
- 差分は `coverage` / `healthCoverage` が1〜2%程度（`video_end` の与え方の差）と `boundaryEndTime` の丸めのみ

## 関連

- [ADR-048: ラウンド単位のドライブゲージ・SAゲージ時系列取得](./048-round-drive-sa-gauge-timeline-capture.md)
- [ADR-049: ラウンド単位のカウンター・パニッシュカウンター回数取得](./049-round-counter-count-capture.md)
- [ADR-036: Pub/Sub キューを Firestore キューに置き換える](./036-replace-pubsub-with-firestore-queue.md)
