"""
BattlelogCollector - Street Fighter 6 対戦ログ収集クライアント

battlelogページから認証情報を使用してStreet Fighter 6の対戦ログを取得
"""

import asyncio
import os
from typing import Any

import aiohttp

from src.utils.logger import get_logger

from .battlelog_parser import BattlelogParser
from .cache import BattlelogCacheManager

logger = get_logger()


class BattlelogCollector:
    """Street Fighter 6公式APIクライアント"""

    # APIエンドポイント（推測ベース）
    # 注：正確なエンドポイントは https://github.com/alanoliveira/sfbuff
    # のコード分析から推測されています
    API_BASE_URL = "https://api.streetfighter.com/v1"
    BUCKLER_API_URL = "https://www.streetfighter.com/6/buckler/api"

    class Unauthorized(Exception):
        """認証エラー"""
        pass

    class PageNotFound(Exception):
        """ページ不在エラー"""
        pass

    def __init__(
        self,
        build_id: str,
        auth_cookie: str,
        user_agent: str | None = None,
        timeout: int = 30,
        cache: BattlelogCacheManager | None = None,
        cache_db_path: str = "./battlelog_cache.db",
    ):
        """
        Args:
            build_id: Next.js buildId
            auth_cookie: 認証クッキー
            user_agent: HTTPリクエスト用User-Agent
            timeout: HTTPリクエストのタイムアウト秒数
            cache: キャッシュマネージャー（未指定時は新規作成）
            cache_db_path: キャッシュDBパス（cache未指定時に使用）
        """
        self.build_id = build_id
        self.auth_cookie = auth_cookie
        self.user_agent = (
            user_agent
            or os.environ.get("SFBUFF_DEFAULT_USER_AGENT")
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.cache = cache or BattlelogCacheManager(db_path=cache_db_path)

    def _get_headers(self, accept: str = "application/json") -> dict[str, str]:
        """
        リクエストヘッダーを構築

        Args:
            accept: Accept ヘッダーの値（デフォルト: application/json）
        """
        return {
            "User-Agent": self.user_agent,
            "Cookie": f"buckler_id={self.auth_cookie}",
            "X-Build-ID": self.build_id,
            "Accept": accept,
            "Referer": "https://www.streetfighter.com/6/buckler/",
        }

    async def _request(
        self,
        method: str,
        url: str,
        response_type: str = "json",
        **kwargs,
    ) -> Any:
        """
        HTTP リクエスト実行

        Args:
            method: HTTPメソッド（GET, POST等）
            url: リクエストURL
            response_type: レスポンスタイプ（json or text）
            **kwargs: aiohttp.ClientSession.request()に渡す追加パラメータ

        Returns:
            レスポンス（JSON または テキスト）

        Raises:
            Unauthorized: 認証エラー（401）
            PageNotFound: ページ不在（404）
            aiohttp.ClientError: その他のネットワークエラー
        """
        headers = kwargs.pop("headers", {})
        # response_type に応じて Accept ヘッダーを設定
        accept_header = (
            "text/html" if response_type == "text" else "application/json"
        )
        headers.update(self._get_headers(accept=accept_header))

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.request(
                method,
                url,
                headers=headers,
                **kwargs,
            ) as resp:
                logger.debug("%s %s -> %d", method, url, resp.status)

                if resp.status == 401:
                    raise self.Unauthorized("Authentication failed (401)")
                elif resp.status == 404:
                    raise self.PageNotFound(f"Endpoint not found: {url}")
                elif resp.status >= 400:
                    text = await resp.text()
                    logger.error("HTTP %d: %s", resp.status, text[:200])
                    raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")

                if response_type == "text":
                    return await resp.text()
                else:
                    return await resp.json()

    async def get_matches(
        self,
        player_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        battle_type_id: str | None = None,
        home_character_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        プレイヤーの対戦ログを取得

        Args:
            player_id: プレイヤーID（例: "1319673732"）
            date_from: 開始日付（ISO 8601形式: "2026-01-01"）
            date_to: 終了日付（ISO 8601形式: "2026-01-31"）
            battle_type_id: 対戦タイプフィルタ
                - "" or "0": すべて
                - "1": ランクマッチ
                - "2": カジュアルマッチ
                - "3": バトルハブ
                - "4": カスタムルーム
            home_character_id: 使用キャラクターフィルタ

        Returns:
            対戦情報リスト

        Example Response:
            [
                {
                    "id": "MH4C37HAN",
                    "playedAt": "2026-01-27T15:30:00Z",
                    "result": "win",
                    "myCharacter": "JP",
                    "myInputType": "C",
                    "opponentName": "ゆゆゆ/Tiger!(φω・)",
                    "opponentCharacter": "ジュリ",
                    "opponentInputType": "C",
                    "battleType": 1,  # 1=ランクマッチ, 2=カジュアル等
                    ...
                },
                ...
            ]

        Raises:
            Unauthorized: 認証エラー
            PageNotFound: エンドポイント不在
            RuntimeError: その他のエラー
        """
        # パラメータ構築
        params = {
            "player_id": player_id,
        }
        if date_from:
            params["played_from"] = date_from
        if date_to:
            params["played_to"] = date_to
        if battle_type_id:
            params["battle_type_id"] = battle_type_id
        if home_character_id:
            params["home_character_id"] = home_character_id

        logger.info(
            "Fetching matches for player %s from %s to %s",
            player_id, date_from, date_to
        )

        # 複数のエンドポイント候補を試す
        endpoints = [
            f"{self.BUCKLER_API_URL}/fighters/{player_id}/matches",
            f"{self.API_BASE_URL}/fighters/{player_id}/matches",
            f"https://www.streetfighter.com/6/buckler/api/fighters/{player_id}/matches",
        ]

        last_error = None
        for endpoint in endpoints:
            try:
                logger.debug("Trying endpoint: %s", endpoint)
                result = await self._request(
                    "GET",
                    endpoint,
                    params=params,
                )
                logger.info("Successfully fetched from %s", endpoint)
                return result.get("matches", result) if isinstance(result, dict) else result

            except self.PageNotFound as e:
                last_error = e
                logger.debug("Endpoint not found: %s", endpoint)
                continue
            except (RuntimeError, aiohttp.ClientError) as e:
                last_error = e
                logger.debug("Error on %s: %s", endpoint, e)
                continue

        # すべてのエンドポイントが失敗
        logger.error("All endpoints failed. Last error: %s", last_error)
        raise RuntimeError(
            f"Could not fetch matches from any endpoint. Last error: {last_error}"
        ) from last_error

    async def get_battlelog_html(
        self,
        player_id: str,
        page: int = 1,
        language: str = "ja-jp",
    ) -> str:
        """
        battlelog ページの HTML を取得

        Args:
            player_id: プレイヤーID
            page: ページ番号（1-10）
            language: 言語コード（ja-jp, en, fr等）

        Returns:
            battlelog ページの HTML

        Raises:
            Unauthorized: 認証エラー
            PageNotFound: ページ不在
            RuntimeError: その他のエラー
        """
        url = (
            f"https://www.streetfighter.com/6/buckler/{language}/"
            f"profile/{player_id}/battlelog"
        )

        logger.info("Fetching battlelog for player %s, page %d", player_id, page)

        # ページパラメータを付与
        params = {"page": str(page)}

        html = await self._request(
            "GET",
            url,
            response_type="text",
            params=params,
        )

        logger.debug("Fetched battlelog HTML: %d chars", len(html))
        return html

    async def get_replay_list(
        self,
        player_id: str,
        page: int = 1,
        language: str = "ja-jp",
    ) -> list[dict[str, Any]]:
        """
        プレイヤーの対戦ログリストを取得（キャッシング対応）

        battlelog ページから __NEXT_DATA__ を抽出して対戦ログを取得。
        キャッシュにない対戦ログのみをキャッシュに追加。

        Args:
            player_id: プレイヤーID
            page: ページ番号（1-10）
            language: 言語コード

        Returns:
            対戦ログの配列（キャッシュ + API新規データのマージ）

        Raises:
            Unauthorized: 認証エラー
            PageNotFound: ページ不在
            ValueError: HTML解析エラー
            RuntimeError: その他のエラー
        """
        # 1. キャッシュから既存データを取得
        cached_replays = self.cache.get_cached_replays(player_id)
        cached_uploaded_at_set = self.cache.get_cached_uploaded_at_set(player_id)

        # 2. HTML を取得してパース
        html = await self.get_battlelog_html(
            player_id=player_id,
            page=page,
            language=language,
        )

        # __NEXT_DATA__ を抽出
        try:
            next_data = BattlelogParser.extract_next_data(html)
            api_replays = BattlelogParser.get_replay_list(next_data)
            logger.info("Successfully extracted %d replays from API", len(api_replays))
        except (ValueError, KeyError) as e:
            logger.error("Failed to extract replay list: %s", e)
            raise RuntimeError(f"Failed to parse battlelog HTML: {e}") from e

        # 3. キャッシュにない対戦ログを抽出
        new_replays = [
            r for r in api_replays
            if str(r.get("uploaded_at")) not in cached_uploaded_at_set
        ]

        # 4. 新規データをキャッシュに保存
        if new_replays:
            cached_count = self.cache.cache_replays(player_id, new_replays)
            logger.info(f"Cached {cached_count} new replays for {player_id}")

        # 5. キャッシュ + API レスポンスをマージして返却
        return cached_replays + api_replays

    async def get_replay_list_incremental(
        self,
        player_id: str,
        language: str = "ja-jp",
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """
        最新キャッシュ以降のリプレイのみを増分取得

        battlelog ページから __NEXT_DATA__ を抽出してリプレイを取得。
        最新キャッシュ以降の新しいリプレイのみを取得し、キャッシュ境界に到達したら終了。

        Args:
            player_id: プレイヤーID
            language: 言語コード
            max_pages: 最大ページ数（安全装置）

        Returns:
            キャッシュ + 新規リプレイのマージ結果

        Raises:
            Unauthorized: 認証エラー
            PageNotFound: ページ不在
            ValueError: HTML解析エラー
            RuntimeError: その他のエラー
        """
        # 1. キャッシュから既存データを取得
        cached_replays = self.cache.get_cached_replays(player_id)
        cached_uploaded_at_set = self.cache.get_cached_uploaded_at_set(player_id)
        latest_cached_at = self.cache.get_latest_uploaded_at(player_id)

        logger.info(
            "Starting incremental fetch for %s: latest_cached_at=%s, cached_count=%d",
            player_id, latest_cached_at, len(cached_replays)
        )

        all_new_replays = []

        # 2. ページ1から順に取得
        for page in range(1, max_pages + 1):
            # ページを取得
            html = await self.get_battlelog_html(
                player_id=player_id,
                page=page,
                language=language,
            )

            try:
                next_data = BattlelogParser.extract_next_data(html)
                page_replays = BattlelogParser.get_replay_list(next_data)
                logger.info(
                    "Fetching battlelog for player %s, page %d: got %d replays",
                    player_id, page, len(page_replays)
                )
            except (ValueError, KeyError) as e:
                logger.error("Failed to parse page %d: %s", page, e)
                break

            # 3. キャッシュにない対戦ログを抽出
            new_page_replays = [
                r for r in page_replays
                if str(r.get("uploaded_at")) not in cached_uploaded_at_set
            ]

            if new_page_replays:
                all_new_replays.extend(new_page_replays)
                self.cache.cache_replays(player_id, new_page_replays)
                logger.info("Cached %d new replays from page %d", len(new_page_replays), page)

            # 4. キャッシュ境界に到達したか確認（新規リプレイがない = 境界到達）
            if not new_page_replays:
                logger.info("No new replays found on page %d. Reached cache boundary. Stopping incremental fetch.", page)
                break

            # 5. ラストページの判定（10件未満）
            if len(page_replays) < 10:
                logger.info("Page %d has only %d replays. This is likely the last page.", page, len(page_replays))
                break

        logger.info("Incremental fetch completed: fetched %d new replays", len(all_new_replays))

        # 6. キャッシュ + 新規データをマージして返却
        return cached_replays + all_new_replays

    async def get_pagination_info(
        self,
        player_id: str,
        page: int = 1,
        language: str = "ja-jp",
    ) -> dict[str, int]:
        """
        ページング情報を取得

        Args:
            player_id: プレイヤーID
            page: ページ番号
            language: 言語コード

        Returns:
            current_page と total_page を含む辞書
        """
        html = await self.get_battlelog_html(
            player_id=player_id,
            page=page,
            language=language,
        )

        try:
            next_data = BattlelogParser.extract_next_data(html)
            pagination_info = BattlelogParser.get_pagination_info(next_data)
            logger.info("Pagination: %s", pagination_info)
            return pagination_info
        except (ValueError, KeyError) as e:
            logger.error("Failed to extract pagination info: %s", e)
            raise RuntimeError(f"Failed to parse battlelog HTML: {e}") from e

    async def get_friends(self) -> dict[str, Any]:
        """
        フレンド情報を取得（接続テスト用）

        Returns:
            フレンド情報

        Raises:
            Unauthorized: 認証エラー
            RuntimeError: その他のエラー
        """
        logger.info("Testing connection by fetching friends list...")

        endpoints = [
            f"{self.BUCKLER_API_URL}/friends",
            f"{self.API_BASE_URL}/friends",
            "https://www.streetfighter.com/6/buckler/api/friends",
        ]

        last_error = None
        for endpoint in endpoints:
            try:
                logger.debug("Trying endpoint: %s", endpoint)
                result = await self._request("GET", endpoint)
                logger.info("Connection test successful via %s", endpoint)
                return result

            except self.PageNotFound:
                last_error = "PageNotFound"
                continue
            except (RuntimeError, aiohttp.ClientError) as e:
                last_error = e
                continue

        raise RuntimeError(f"Connection test failed. Last error: {last_error}") from last_error

    # 同期版メソッド
    def get_matches_sync(
        self,
        player_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        battle_type_id: str | None = None,
        home_character_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """同期版get_matches"""
        return asyncio.run(
            self.get_matches(
                player_id=player_id,
                date_from=date_from,
                date_to=date_to,
                battle_type_id=battle_type_id,
                home_character_id=home_character_id,
            )
        )

    def get_replay_list_sync(
        self,
        player_id: str,
        page: int = 1,
        language: str = "ja-jp",
    ) -> list[dict[str, Any]]:
        """同期版get_replay_list"""
        return asyncio.run(
            self.get_replay_list(
                player_id=player_id,
                page=page,
                language=language,
            )
        )

    def get_replay_list_incremental_sync(
        self,
        player_id: str,
        language: str = "ja-jp",
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """同期版get_replay_list_incremental"""
        return asyncio.run(
            self.get_replay_list_incremental(
                player_id=player_id,
                language=language,
                max_pages=max_pages,
            )
        )

    def get_pagination_info_sync(
        self,
        player_id: str,
        page: int = 1,
        language: str = "ja-jp",
    ) -> dict[str, int]:
        """同期版get_pagination_info"""
        return asyncio.run(
            self.get_pagination_info(
                player_id=player_id,
                page=page,
                language=language,
            )
        )

    def get_friends_sync(self) -> dict[str, Any]:
        """同期版get_friends"""
        return asyncio.run(self.get_friends())
