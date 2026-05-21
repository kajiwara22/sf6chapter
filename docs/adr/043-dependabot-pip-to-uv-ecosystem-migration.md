# ADR-043: Dependabot エコシステムを `pip` から `uv` へ移行

## ステータス

承認済み - 2026-05-21

## 文脈

### 発端

[ADR-038](038-dependabot-and-github-actions-for-dependency-updates.md) で Dependabot を導入し、4 つの Python パッケージ（`packages/local`, `packages/gcp-functions/check-new-video`, `packages/obs-title-updater`, `packages/report-generator`）はいずれも `package-ecosystem: "pip"` で設定していた。

この設定で運用を開始したところ、`packages/report-generator` 向けに作られた Dependabot PR [#11](https://github.com/kajiwara22/sf6chapter/pull/11) の通知において、**更新種別（`update-type`）が空** で届く事象が発生した。

```
chore(deps): bump the report-generator-dependencies group in /packages/report-generator with 2 updates
```

通常であれば `semver-patch` / `semver-minor` / `semver-major` のいずれかが付与されるが、本 PR では `update-type` フィールドが null となっていた。これに伴い「patch なら auto-merge」というマージ方針（ADR-038）が機能しない。

### 原因分析

#### 1. PR の中身

PR #11 の差分は `pyproject.toml` のみで、`uv.lock` は更新されていなかった。

```diff
- "boto3>=1.43.6",
+ "boto3>=1.43.11",
…
- "ruff>=0.15.12",
+ "ruff>=0.15.13",
```

PR タイトルにも `Updates the requirements on boto3 and ruff to permit the latest version.` と書かれており、これは Dependabot 用語で **「version requirement update（下限の引き上げ）」** に該当する更新であった。

#### 2. なぜ requirement update になったか

Dependabot の `pip` エコシステムが認識する manifest / lockfile は次のものに限られる。

- `requirements.txt`
- `Pipfile` / `Pipfile.lock`
- `setup.py` / `setup.cfg`
- `pyproject.toml`（PEP 621 の `dependencies` の読み取りのみ）

**`uv.lock` は `pip` エコシステムの対象外** である。そのため Dependabot は `uv.lock` の存在を無視し、`pyproject.toml` の `>=` 指定だけを参照して動作した。結果、`uv.lock` を更新する代わりに `pyproject.toml` の下限値を書き換える PR が作られた。

#### 3. なぜ update-type が空になるか

`update-type` フィールドは「あるバージョン X から Y への遷移」が確定している場合に semver 分類されて付与される。

- lockfile を更新する更新（version update）: from / to が確定 → `update-type` が付く
- requirement の下限引き上げ（version requirement update）: 単に許容範囲を広げただけで遷移が無い → `update-type` は null

PR #11 は後者にあたるため、通知側で「更新種別なし」となった。

### 対応の選択肢

| 案 | 内容 | 評価 |
|---|---|---|
| A | 現状維持（`pip` のまま `pyproject.toml` だけ更新される） | `uv.lock` は手動で `uv lock --upgrade` が必要。auto-merge 方針が機能しない。NG |
| B | `pip` から **公式 `uv` エコシステム** に切り替える | `uv.lock` を直接更新する PR が作られ、`update-type` も正しく付く。`uv sync --frozen` ベースの CI とも整合する。採用 |
| C | `pyproject.toml` の `>=` を `==` にピン留めする | uv の運用思想に反する。lockfile があるのに requirement にもピンを書く二重管理になる。NG |

## 決定事項

### 1. `.github/dependabot.yml` の変更

以下 4 つの Python パッケージの `package-ecosystem` を `pip` から `uv` に変更する。

- `packages/local`
- `packages/gcp-functions/check-new-video`
- `packages/obs-title-updater`
- `packages/report-generator`

`github-actions` および `packages/web`（`npm`）の設定は変更しない。

### 2. 既存 PR の扱い

`pip` エコシステムで作成済みの PR #11 は閉じる。`uv` エコシステムへの切り替え後、次回スケジュール実行で `uv.lock` を更新する正規の PR が再作成される。ブランチ（`dependabot/pip/packages/report-generator/report-generator-dependencies-b36da19d9a`）も削除する。

### 3. ADR-038 の扱い

ADR-038 の「対象エコシステム」表における `pip (uv)` という表記は、当時の `package-ecosystem: pip` 設定を指している。本 ADR でこれを `uv` 公式エコシステムに変更するが、ADR-038 自体は**当時の意思決定の記録として変更しない**。本 ADR-043 が ADR-038 を更新する位置づけとする。

### 4. 動作確認の手順

設定変更を main にマージした後、以下のいずれかで挙動を確認する。

- 自然スケジュール（weekly）を待つ
- リポジトリ Web UI: **Insights → Dependency graph → Dependabot → 各パッケージの行で "Check for updates"** を手動実行

期待結果:

- PR の差分に `uv.lock` の更新が含まれる
- PR タイトル/本文に `from X to Y` の形でバージョン遷移が示される
- 通知に `update-type: semver-patch` 等が付与される
- patch であれば auto-merge 方針が正しく機能する

## 結果

### 良い点

- Dependabot が `uv.lock` を直接更新するようになり、ローカルでの `uv lock --upgrade` 手動実行が不要になる
- `update-type` が正しく付与され、ADR-038 で定めた「patch は auto-merge、minor/major は手動」というマージ方針が機能する
- 通知の情報量が増え、更新の影響範囲（patch/minor/major）が一目で判断できる
- CI の `uv sync --frozen`（ADR-038）と Dependabot の更新対象（`uv.lock`）が一致し、整合性チェックが意味を持つ

### 制約・トレードオフ

- Dependabot の `uv` エコシステムは比較的新しい機能であり、`pip` ほどの長期実績はない。挙動の差異が見つかった場合は本 ADR を再評価する。
- 切り替え直後は、既存 PR の手動クローズおよびブランチ削除という移行作業が発生する（一度きり）。

### 参考

- PR #11: https://github.com/kajiwara22/sf6chapter/pull/11
- 関連 ADR: [ADR-038](038-dependabot-and-github-actions-for-dependency-updates.md)
