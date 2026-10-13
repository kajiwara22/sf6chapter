---
name: analyze-video
description: Use when the user asks to analyze a YouTube video/stream for SF6 chapter generation and data updates — trigger phrases include "この動画を解析して", "この配信のチャプターを作って", "動画ID <id> で解析", "YouTubeとR2を更新して", "analyze this video <url>". Runs the single-scan local pipeline (detection + gauge + counter → recognition → YouTube chapters → R2) and verifies/reports the result. Do not load for web-only or parameter-tuning work.
---

# analyze-video - 動画解析（チャプター生成・ゲージ計測・R2反映）

SF6 の配信動画を動画ID指定で処理し、YouTube チャプターと R2 データを更新する手順書。

本線フロー（`SF6ChapterProcessor.process_video()`）は、**検出・ゲージ計測（ADR-048）・カウンター計測（ADR-049）を同じデコードループで実行する（1回走査）**。
`--video-id` を指定した単発処理を使うこと。`--mode test --test-step all` はテスト用でゲージ・カウンターを計測しないため使わない。

## 入力

- YouTube の URL または動画ID（`https://youtube.com/live/<ID>`、`https://www.youtube.com/watch?v=<ID>`、または `<ID>`）
- 再処理（再実行）かどうか

## 前提条件

- 作業ディレクトリ: `packages/local`
- 環境変数（この順で確認する）:
  - `ENABLE_R2=true`
  - `SF6_PLAYER_ID`（Battlelog マッピングに必須）
  - `GOOGLE_CLOUD_PROJECT`
  - `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_ENDPOINT_URL` / `R2_BUCKET_NAME`
- 認証ファイル: `token.pickle`、`client_secrets.json`、`cookie/cookie.txt`（yt-dlp 用。既定の `--cookie-path`）
- `uv` / `ffmpeg` / yt-dlp の JS ランタイム（deno 等）

環境変数が無い場合は `mise env` などで読み込む。無ければユーザーに確認する。

```bash
cd packages/local
test -f token.pickle && test -f client_secrets.json && echo "auth OK"
test -f cookie/cookie.txt && echo "cookie OK"
printenv ENABLE_R2 SF6_PLAYER_ID R2_BUCKET_NAME GOOGLE_CLOUD_PROJECT >/dev/null && echo "env OK"
```

## 実行

**長時間かかる（32分動画で約10分、長い配信では数十分〜）ため、必ずデタッチして起動し、ポーリングする。** `setsid` でプロセスグループを切り離さないと、待機コマンドの中断に巻き込まれて落ちる。

```bash
cd packages/local
setsid env ENABLE_R2=true uv run python main.py --video-id <ID> > /tmp/sf6_<ID>.log 2>&1 < /dev/null &
disown
```

- 既定（Firestore あり）: 本番同様に処理状態を記録する。Firestore が `completed` の動画はスキップされる。
- 再処理・検証（Firestore を参照・更新しない）: `--no-firestore` を付ける。

```bash
setsid env ENABLE_R2=true uv run python main.py --video-id <ID> --no-firestore > /tmp/sf6_<ID>.log 2>&1 < /dev/null &
```

### 進捗確認（ポーリング）

```bash
tail -5 /tmp/sf6_<ID>.log
grep -nE "Downloaded:|Found [0-9]+ matches|Matched [0-9]+/[0-9]+ chapters|Saved gauge analysis|Saved [0-9]+ round stat|Updated YouTube|Successfully processed|Error|Traceback" /tmp/sf6_<ID>.log | tail -20
```

処理の流れ: ダウンロード → 検出＋ゲージ＋カウンター（1回走査）→ Gemini 認識 → YouTube チャプター更新 → Battlelog マッピング → R2 アップロード → manifest 更新。

## 検証

### YouTube チャプター

```bash
uv run python - <<'EOF'
from src.youtube import YouTubeChapterUpdater
info = YouTubeChapterUpdater().get_video_info("<ID>")
print(info["title"]); print(info["description"])
EOF
```

### R2（Parquet / gauges / manifest）

```bash
uv run python - <<'EOF'
import os, io, json, boto3, pyarrow.parquet as pq
ep = os.environ["R2_ENDPOINT_URL"]; ep = ep if ep.startswith("http") else "https://" + ep
s3 = boto3.client("s3", endpoint_url=ep,
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
b = os.environ["R2_BUCKET_NAME"]; vid = "<ID>"
get = lambda k: s3.get_object(Bucket=b, Key=k)["Body"].read()
m = json.loads(get("manifest.json")); print("manifest:", m["version"])
for name in ("matches.parquet", "round_stats.parquet"):
    df = pq.read_table(io.BytesIO(get(name))).to_pandas()
    print(name, "thisVideo:", int((df["videoId"] == vid).sum()))
print("videos.json chapters:", len(json.loads(get(f"videos/{vid}.json"))["chapters"]))
print("gauges sample exists:", bool(get(f"gauges/{vid}_34.json")))
EOF
```

確認ポイント:
- YouTube 説明欄に `0:00 本編開始` ＋ 全試合チャプターが入っている
- `matches.parquet` / `round_stats.parquet` に当該 videoId の行がある
- `gauges/{matchId}.json` が存在する
- ラウンド数の突合（不一致）: 実行ログの `[Gauge] round count mismatch` を確認する。dry-run でまとめて見る場合は次を実行。

```bash
uv run python scripts/upload_gauge_data.py --video-id <ID> --dry-run
# → "round_count(match/mismatch/unknown)=N/0/0" が理想
```

## 結果の報告

- 動画タイトル・長さ・公開日
- 検出試合数、キャラクター、Battlelog マッチ率
- YouTube チャプター数
- R2: manifest version、`round_stats` 行数、`gauges` 件数、ラウンド数不一致の有無
- 中間ファイル: `intermediate/<ID>/`
- 気づいた問題（検出漏れ・誤検出・新キャラ等）

## トラブルシューティング

- **ダウンロードが途中で止まった / プロセスが落ちた**: yt-dlp は `.part` から再開する。同じコマンドを再実行すればよい。完了済みファイルがあれば再利用される（`skip_download_if_exists=True`）。
- **Firestore が `completed` でスキップされた**: 再処理は `--no-firestore` を付ける。
- **検出漏れ・誤検出**: `intermediate/<ID>/detection_summary.json` と `frame_*.png` を目視確認する。`chapters.json` を手修正した場合は、次で YouTube と R2 に再反映できる。
  ```bash
  ENABLE_R2=true uv run python main.py --mode test --test-step chapters --video-id <ID> --from-intermediate
  ```
- **新キャラクターで体力が既定値になる**: `schema/character_health.json` に追記する（canonical 名は `packages/local/config/character_aliases.json` に合わせる）。実行時に `config/character_health.json` として R2 へ自動アップロードされる。
- **ゲージだけ再計測したい（パラメータ調整・バックフィル）**: `scripts/analyze_counters.py --video-id <ID>` → `scripts/upload_gauge_data.py --video-id <ID>`（検出＋Gemini を再実行せずに計測できる）。

## 関連

- ADR-064: 動画ID指定による本線フローの単発実行（1回走査）
- ADR-048 / ADR-049: ゲージ・カウンター計測
- `packages/local/README.md`: 実行方法の詳細
