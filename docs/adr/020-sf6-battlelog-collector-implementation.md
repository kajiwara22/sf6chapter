# ADR-020: SF6 Battlelog 対戦ログ収集システムの実装

## ステータス

採用（Accepted） - 2026-02-17

## 文脈

YouTube配信動画のSF6対戦シーンを自動検出するシステムでは、対戦結果の詳細情報（キャラクター、結果、レート等）が必要である。しかし、YouTube Data APIには試合結果の詳細情報が含まれていない。

### 課題

1. **データソースの不足**: YouTube動画には対戦結果の詳細情報がない
2. **プレイヤー情報の取得**: 動画内のプレイヤーIDを特定し、その対戦ログを取得する必要がある
3. **非公開API**: Street Fighter公式APIが公開されていない
4. **認証が必要**: Capcom IDでのログインが必要

### 既存の制約

- SFBuff（非公開APIを推定）は、buildIdとJWT認証が必要
- Playwrightでのブラウザ自動化は追加の依存関係
- 対戦ログは1ページ最大10件のページネーション方式

## 決定

**SF6 Battlelog 対戦ログ収集システムを新規実装**

### 実装内容

#### 1. パッケージ構成: `sf6_battlelog`

モジュラー設計で3つのコンポーネントから構成：

```
sf6_battlelog/
├── authenticator.py       # Capcom ID認証
├── site_client.py         # buildId取得
├── api_client.py          # battlelog API（HTMLスクレイピング）
├── battlelog_parser.py    # HTML解析
└── __init__.py            # 公開インターフェース
```

#### 2. 主要コンポーネント

##### a. `CapcomIdAuthenticator` - 認証

**機能**: Playwrightを使用したCapcom ID認証

```python
# 使用方法
authenticator = CapcomIdAuthenticator()

# 環境変数から認証情報を取得する場合
# BUCKLER_EMAIL, BUCKLER_PASSWORD を設定

# キャッシュされたクッキーを使用する場合
# BUCKLER_ID_COOKIE を設定

# 出力: buckler_id クッキー
auth_cookie = await authenticator.login()
```

**特徴**:
- Playwright ヘッドレスブラウザで実際のログインフロー実行
- Cookie同意ダイアログ自動処理
- プラットフォーム選択画面自動処理
- `BUCKLER_ID_COOKIE` 環境変数でログインスキップ可能

**実装ファイル**: `packages/local/src/sf6_battlelog/authenticator.py`

##### b. `BattlelogSiteClient` - buildId取得

**機能**: Next.jsサイトから動的buildIdを取得

```python
# 使用方法
site_client = BattlelogSiteClient()
build_id = await site_client.get_build_id()
```

**技術詳細**:
- `https://www.streetfighter.com/6/buckler/profile` にHTTP GETリクエスト
- レスポンスHTMLから `<script id="__NEXT_DATA__">` タグを抽出
- JSONパース → `build_id` フィールド抽出

**実装ファイル**: `packages/local/src/sf6_battlelog/site_client.py`

##### c. `BattlelogCollector` - 対戦ログ取得

**機能**: battlelogページから対戦ログを収集（HTMLスクレイピング）

```python
# 使用方法
collector = BattlelogCollector(
    build_id=build_id,
    auth_cookie=auth_cookie
)

# 1ページ取得（最大10件）
replays = await collector.get_replay_list(
    player_id="1319673732",
    page=1
)

# ページング情報取得
pagination = await collector.get_pagination_info(
    player_id="1319673732",
    page=1
)
```

**API エンドポイント**:
```
GET https://www.streetfighter.com/6/buckler/battlelog?player_id={player_id}&page={page_num}
```

**技術詳細**:
- 認証クッキーとbuildIdをHTTPヘッダーに含める
- レスポンスHTMLから `__NEXT_DATA__` を抽出
- JSON解析 → `props.pageProps.battlelog` から対戦ログ配列を取得
- ページネーション情報も同時取得

**実装ファイル**: `packages/local/src/sf6_battlelog/api_client.py`

##### d. `BattlelogParser` - HTML解析ユーティリティ

**機能**: battlelog HTMLから構造化データを抽出

```python
parser = BattlelogParser(html_content)

# 対戦ログリスト取得
replay_list = parser.get_replay_list()

# ページング情報取得
pagination_info = parser.get_pagination_info()

# プレイヤー情報取得
fighter_info = parser.get_fighter_info()
```

**実装ファイル**: `packages/local/src/sf6_battlelog/battlelog_parser.py`

### 3. テストスクリプト

#### `test_battlelog_collector.py`

**機能**: 統合テスト（6ステップ）

```bash
# JSON形式で出力
uv run scripts/test_battlelog_collector.py \
  --player-id 1319673732 \
  --output-format json

# Pretty形式（デフォルト）
uv run scripts/test_battlelog_collector.py \
  --player-id 1319673732
```

**テストフロー**:
1. buildId取得
2. ログイン認証
3. APIクライアント初期化
4. battlelogから対戦ログ取得
5. ページング情報取得
6. レスポンス構造検査

**実装ファイル**: `packages/local/scripts/test_battlelog_collector.py`

### 4. 依存関係の追加

`pyproject.toml` に以下を追加:

```toml
[project]
dependencies = [
    "playwright>=1.40.0",      # ブラウザ自動化
    "aiohttp>=3.9.0",          # 非同期HTTP通信
    # ... 既存の依存関係
]
```

### 5. 設計原則

#### a. 非同期対応

すべてのコンポーネントで非同期メソッドを提供：

```python
# 非同期版
build_id = await site_client.get_build_id()
auth_cookie = await authenticator.login()
replays = await collector.get_replay_list(player_id, page)

# 同期版（テスト用）
build_id = site_client.get_build_id_sync()
auth_cookie = authenticator.login_sync()
replays = collector.get_replay_list_sync(player_id, page)
```

#### b. 環境変数サポート

```python
# Capcom ID認証
BUCKLER_EMAIL          # メールアドレス
BUCKLER_PASSWORD       # パスワード
BUCKLER_ID_COOKIE      # キャッシュされたクッキー（優先）

# HTTP設定
DEFAULT_USER_AGENT     # User-Agent（Bot判定回避）
```

#### c. エラーハンドリング

```python
class BattlelogCollector:
    class Unauthorized(Exception):
        """認証エラー（401）"""
        pass

    class PageNotFound(Exception):
        """ページ取得エラー（404）"""
        pass
```

#### d. タイムアウト設定

デフォルト: 30秒（カスタマイズ可能）

```python
collector = BattlelogCollector(
    build_id=build_id,
    auth_cookie=auth_cookie,
    timeout=60  # 60秒に設定
)
```

## 検討した代替案

### 代替案1: 公式APIの利用

Street Fighter公式APIを使用する。

**却下理由**:
- 公開APIが存在しない
- Capcom側でAPIを公開する見込みが不明確
- HTMLスクレイピングが現実的

### 代替案2: Seleniumを使用

Playwrightの代わりにSeleniumを使用。

**却下理由**:
- Playwrightの方が軽量で高速
- TypeScript/JavaScriptとの相互運用性が良い
- Cloudflareでのブラウザレンダリングと組み合わせやすい

### 代替案3: HeadlessChrome直接制御

DevTools Protocolで直接ブラウザを制御。

**却下理由**:
- 実装が複雑
- Playwrightは既に最適化済み
- メンテナンスコストが増加

## 結果

### 期待される効果

| 項目 | 期待値 |
|------|--------|
| **対戦ログ取得の自動化** | ✓ 可能 |
| **実装期間** | 1-2日 |
| **追加コスト** | $0（YouTube APIのクォータ内） |
| **保守性** | 高（モジュラー設計） |

### 検証方法

```bash
# テスト実行
uv run scripts/test_battlelog_collector.py --player-id 1319673732

# 期待される出力
# - Step 1: buildId取得成功
# - Step 2: ログイン成功
# - Step 3: APIクライアント初期化成功
# - Step 4: 対戦ログ10件取得
# - Step 5: ページング情報取得成功（total_page: 10）
# - Step 6: JSON出力
```

### 成功基準

1. ✓ テストスクリプトが正常に実行される
2. ✓ 対戦ログを複数ページ取得できる
3. ✓ 対戦結果の詳細フィールドが取得できる
4. ✓ エラーハンドリングが適切に機能する

## トレードオフと影響

### 長所

| 項目 | 説明 |
|------|------|
| **柔軟性** | モジュラー設計で各コンポーネント独立 |
| **メンテナンス性** | 各コンポーネントに明確な責務 |
| **テスト可能性** | 同期版メソッドでテスト容易 |
| **再利用性** | 他のプロジェクトでも利用可能 |

### 短所

| 項目 | 説明 | 対策 |
|------|------|------|
| **Playwright依存** | ヘッドレスブラウザ起動のオーバーヘッド | 認証クッキーキャッシュで軽減 |
| **APIの安定性** | HTML構造変更で破損のリスク | 正規表現ベースの堅牢なパーサ |
| **保守負荷** | Street Fighter側の仕様変更に対応必要 | ADRで変更履歴を記録 |

## リスク管理

| リスク | 影響 | 対策 |
|-------|------|------|
| Street Fighter側がAPI構造を変更 | システム全体が機能停止 | HTML解析ロジックの堅牢化、定期的な監視 |
| Capcom IDのセキュリティ強化 | ログイン失敗 | `BUCKLER_ID_COOKIE` 環境変数でバイパス可能 |
| API Rate Limitingの導入 | 大量リクエストで制限 | リトライロジック（指数バックオフ）実装予定 |
| Playgrounds起動失敗 | 運用継続不可 | エラーハンドリング強化、フォールバック機構 |

## 実装ファイル

### 新規作成ファイル

| ファイル | 説明 |
|----------|------|
| `packages/local/src/sf6_battlelog/__init__.py` | モジュール定義 |
| `packages/local/src/sf6_battlelog/authenticator.py` | Capcom ID認証 |
| `packages/local/src/sf6_battlelog/site_client.py` | buildId取得 |
| `packages/local/src/sf6_battlelog/api_client.py` | battlelog API |
| `packages/local/src/sf6_battlelog/battlelog_parser.py` | HTML解析 |
| `packages/local/scripts/test_battlelog_collector.py` | 統合テスト |
| `packages/local/docs/sf6-battlelog-api-integration.md` | ドキュメント |

### 修正ファイル

| ファイル | 変更内容 |
|----------|---------|
| `packages/local/pyproject.toml` | playwright, aiohttp 追加 |
| `SFBUFF_IMPLEMENTATION_SUMMARY.md` | 実装内容のまとめ |

## 関連するADR

- [ADR-004: ローカルPC処理でOAuth2認証を使用](004-oauth2-authentication-for-all-gcp-apis.md)
- [ADR-011: 中間ファイル保存による人間確認フロー](011-intermediate-file-preservation.md)
- [ADR-017: 検出パラメータの最適化](017-detection-parameter-optimization.md)

## 次のステップ

### 短期（1-2週間）

1. テストスクリプトの実行
2. 複数プレイヤーIDでのテスト
3. エラーケースの検証

### 中期（1ヶ月）

1. 対戦ログとYouTube動画の紐付けロジック実装
2. Gemini キャラクター認識との統合（ADR-019）
3. Intermediate ファイルへの対戦ログ統計情報追加

### 長期（2-3ヶ月）

1. API Rate Limitingへの対応
2. キャッシング機構の実装（buildId、認証クッキー）
3. スケジューラ統合

## 参考資料

- [Playwright Documentation](https://playwright.dev/python/)
- [aiohttp Documentation](https://docs.aiohttp.org/)
- [Street Fighter 6 Buckler (公式サイト)](https://www.streetfighter.com/6/buckler/)
