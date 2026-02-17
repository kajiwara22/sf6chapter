"""
BattlelogCollector - Street Fighter 6 対戦ログ収集クライアント

battlelogページから認証情報を使用してStreet Fighter 6の対戦ログを取得
"""

import asyncio
import os
from typing import Any, Optional

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
        user_agent: Optional[str] = None,
        timeout: int = 30,
        cache: Optional[BattlelogCacheManager] = None,
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
                logger.debug(f"{method} {url} -> {resp.status}")

                if resp.status == 401:
                    raise self.Unauthorized("Authentication failed (401)")
                elif resp.status == 404:
                    raise self.PageNotFound(f"Endpoint not found: {url}")
                elif resp.status >= 400:
                    text = await resp.text()
                    logger.error(f"HTTP {resp.status}: {text[:200]}")
                    raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")

                if response_type == "text":
                    return await resp.text()
                else:
                    return await resp.json()

    async def get_matches(
        self,
        player_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        battle_type_id: Optional[str] = None,
        home_character_id: Optional[str] = None,
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
            f"Fetching matches for player {player_id} "
            f"from {date_from} to {date_to}"
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
                logger.debug(f"Trying endpoint: {endpoint}")
                result = await self._request(
                    "GET",
                    endpoint,
                    params=params,
                )
                logger.info(f"Successfully fetched from {endpoint}")
                return result.get("matches", result) if isinstance(result, dict) else result

            except self.PageNotFound as e:
                last_error = e
                logger.debug(f"Endpoint not found: {endpoint}")
                continue
            except Exception as e:
                last_error = e
                logger.debug(f"Error on {endpoint}: {e}")
                continue

        # すべてのエンドポイントが失敗
        logger.error(f"All endpoints failed. Last error: {last_error}")
        raise RuntimeError(
            f"Could not fetch matches from any endpoint. Last error: {last_error}"
        )

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

        logger.info(f"Fetching battlelog for player {player_id}, page {page}")

        # ページパラメータを付与
        params = {"page": str(page)}

        html = await self._request(
            "GET",
            url,
            response_type="text",
            params=params,
        )

        logger.debug(f"Fetched battlelog HTML: {len(html)} chars")
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
            logger.info(f"Successfully extracted {len(api_replays)} replays from API")
        except (ValueError, KeyError, Exception) as e:
            logger.error(f"Failed to extract replay list: {e}")
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
            logger.info(f"Pagination: {pagination_info}")
            return pagination_info
        except (ValueError, KeyError, Exception) as e:
            logger.error(f"Failed to extract pagination info: {e}")
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
                logger.debug(f"Trying endpoint: {endpoint}")
                result = await self._request("GET", endpoint)
                logger.info(f"Connection test successful via {endpoint}")
                return result

            except self.PageNotFound:
                last_error = "PageNotFound"
                continue
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f"Connection test failed. Last error: {last_error}")

    # 同期版メソッド
    def get_matches_sync(
        self,
        player_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        battle_type_id: Optional[str] = None,
        home_character_id: Optional[str] = None,
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
