# ADR-045: DependabotのPyPIレジストリをTakumi Guard経由に変更

## ステータス

承認済み・実装済み - 2026-06-11

## 文脈

### 発端

Dependabotは現在、PyPI（`pypi.org`）に直接アクセスして依存パッケージの新バージョンを検出・更新PRを作成している。この構成では、PyPIに公開された直後の悪意あるパッケージ（サプライチェーン攻撃）に対して無防備であり、検証前のパッケージへの更新PRが作成されうる。

### Takumi Guard とは

[Takumi Guard](https://shisho.dev/docs/t/) は GMO Flatt Security が提供するレジストリプロキシサービス。PyPI・npmなどのパッケージリクエストをインターセプトし、既知の悪意あるパッケージをブロックする。

主な特徴：

- **レジストリURL**: `https://pypi.flatt.tech/simple/`（PyPI Simple API 互換）
- **72時間の検疫（クォランティン）**: 新規公開パッケージは72時間経過するまで配信しない
- **悪性パッケージのブロック**: 既知の悪意あるパッケージを永続的にブロック
- **pip / uv / poetry に対応**
- **無料プラン**あり（匿名トークン `tg_anon_` 形式）

### 72時間検疫の意味

新バージョンが PyPI に公開された直後は、そのパッケージが安全かどうか判明していない場合がある。Takumi Guard は72時間の検疫期間を設けており、その間は当該バージョンをプロキシ経由で配信しない。

これはDependabotにとって「更新が3日遅れる」のではなく、**「検疫が完了して安全と判定されたバージョンのみをDependabotが認識できる」** という動作を意味する。サプライチェーン攻撃のリスクを持つパッケージへの自動更新PRを防ぐことが目的であり、この遅延は意図された保護機能である。

### 対応の選択肢

| 案 | 内容 | 評価 |
|---|---|---|
| A | 現状維持（PyPIへ直接アクセス） | 設定変更不要。ただし悪意あるパッケージの更新PRが作られるリスクが残る |
| B | Takumi Guard をDependabotのレジストリとして設定 | `dependabot.yml` の変更のみで導入可能。検疫済みパッケージのみDependabotが認識する |
| C | GitHub Actions の CI でのみ Takumi Guard を使用 | CI上のインストールは保護されるが、Dependabotの更新PR自体は保護されない |

方案AはサプライチェーンリスクをDependabot経由でも受け入れることになる。方案CはCI保護にはなるがDependabotの挙動は変わらない。方案BはDependabot自体がTakumi Guard経由でバージョン解決するため、検疫中パッケージへの更新PRが作られない。

## 決定事項

**方案Bを採用する。** `dependabot.yml` に `registries` セクションを追加し、Python（uv）エコシステムのDependabotがTakumi Guard経由でパッケージバージョンを解決するよう設定する。

### 実装方針

- `dependabot.yml` の `registries` に `python-index` タイプで Takumi Guard を定義する
- 各 `uv` エコシステムのエントリに `registries` を指定して紐付ける
- 認証トークン（`tg_anon_` 形式）はGitHub Secretsに登録し、`${{secrets.TAKUMI_GUARD_TOKEN}}` として参照する
- `npm` エコシステムは今回のスコープ外とする（別途ADRで検討）

### dependabot.yml の変更イメージ

```yaml
version: 2
registries:
  takumi-guard-pypi:
    type: python-index
    url: https://pypi.flatt.tech/simple/
    token: ${{secrets.TAKUMI_GUARD_TOKEN}}

updates:
  - package-ecosystem: "uv"
    directory: "/packages/local"
    registries:
      - takumi-guard-pypi
    schedule:
      interval: "weekly"
    # ...（他のuvエントリも同様）
```

## 結果

### 良い点

- Dependabotが検疫前（公開直後72時間以内）の悪意あるパッケージへの更新PRを作成しなくなる
- `dependabot.yml` の変更のみで導入でき、アプリケーションコードへの影響がない
- Takumi Guard は PyPI Simple API 互換のため、uv エコシステムとの互換性が保たれる

### 制約・トレードオフ

- 新バージョンのパッケージは公開から最大72時間後にDependabotが検出するようになる（意図された遅延）
- Takumi Guard が外部サービスであるため、サービス障害時にDependabotの更新が失敗する可能性がある
- 認証トークンのローテーション管理が必要になる
- npm エコシステムへの適用は今回のスコープ外
