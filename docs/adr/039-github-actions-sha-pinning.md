# ADR-039: GitHub Actions サードパーティ Action の SHA ピンニング

## ステータス

承認済み - 2026-05-05

## 文脈

### 現状の課題

ADR-038 で整備した GitHub Actions ワークフロー（`ci-*.yml`, `dependabot-auto-merge.yml`）では、サードパーティ Action をタグ名で参照している。

```yaml
# 現状（タグ参照）
- uses: actions/checkout@v4
- uses: astral-sh/setup-uv@v6
```

GitHub のタグは後から別コミットに付け替えが可能なため、タグ参照のままではサプライチェーン攻撃のリスクがある。悪意ある第三者が Action リポジトリを乗っ取ってタグを書き換えた場合、次のワークフロー実行時に改ざんされたコードが実行される。

本リポジトリのワークフローは Cloud Functions へのデプロイや自動マージなどを含むため、ワークフロー上での任意コード実行はリポジトリや GCP リソースへの不正アクセスに直結するリスクがある。

### 対応案

| 案 | 内容 | 評価 |
|---|---|---|
| A: タグ参照のまま運用 | 変更なし | 可読性は高いが、タグ書き換え攻撃に無防備 |
| B: SHA ピンニング（固定） | コミット SHA で参照を固定する | 攻撃を防げるが、手動更新が必要で陳腐化リスクがある |
| C: SHA ピンニング + Dependabot による自動更新 | B に Dependabot を組み合わせる | セキュリティと鮮度を両立できる |

Dependabot は `github-actions` エコシステムに対応しており、SHA ピンニングされた Action のバージョンアップを検知して PR を自動作成できる。ADR-038 で既に Dependabot は設定済みであり、`github-actions` エコシステムを追加するだけで対応できる。

## 決定事項

**サードパーティ Action をすべてコミット SHA で固定し、Dependabot で SHA の自動更新を行う（案C）。**

- `.github/workflows/` 内の全サードパーティ Action をコミット SHA で参照し、バージョンをコメントで明示する
- `.github/dependabot.yml` に `github-actions` エコシステムを追加し、週次で Action の SHA 更新 PR を自動作成する

### SHA ピンニングの記述形式

```yaml
# 変更後（SHA ピンニング + バージョンコメント）
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
- uses: astral-sh/setup-uv@bd01e18f51369d5a26f1651c3cb451d3417e3bba  # v6.3.1
```

### Dependabot 設定への追加

```yaml
- package-ecosystem: "github-actions"
  directory: "/"
  schedule:
    interval: "weekly"
    day: "monday"
  groups:
    github-actions:
      patterns: ["*"]
```

## 結果

### 良い点

- タグの書き換えによるサプライチェーン攻撃を防げる。SHA は不変であり、参照先コードの改ざんを検知できる
- Dependabot により最新の Action への追従が自動化され、手動での陳腐化を防げる
- ADR-038 で整備した Dependabot の仕組みをそのまま活用できる

### 注意点・今後の対応

- 新しいサードパーティ Action をワークフローに追加する際は、必ずコミット SHA で参照する。タグやブランチ名での参照は行わない
- Dependabot が Action の SHA 更新 PR を作成した場合、`patch` 相当の更新であれば ADR-038 の auto-merge ポリシーに従って自動マージされる

## 参考資料

- [Security hardening for GitHub Actions - GitHub Docs](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions)
- [Keeping your GitHub Actions and packages up to date with Dependabot - GitHub Docs](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/keeping-your-actions-up-to-date-with-dependabot)
- [ADR-038: Dependabot + GitHub Actions による依存関係自動更新の導入](./038-dependabot-and-github-actions-for-dependency-updates.md)
