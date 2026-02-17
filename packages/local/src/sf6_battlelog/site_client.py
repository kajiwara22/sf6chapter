"""
BattlelogSiteClient - Street Fighter 6 Next.jsサイトクライアント

Next.jsの_nextデータエンドポイントからbuildIdを取得
"""

import asyncio
import os
from typing import Any

import aiohttp

from src.utils.logger import get_logger

logger = get_logger()


class BattlelogSiteClient:
    """Street Fighter 6公式サイトのNext.jsクライアント"""

    # Street Fighter 6公式サイトベースURL
    BASE_URL = "https://www.streetfighter.com/6/buckler"

    def __init__(
        self,
        user_agent: str | None = None,
        timeout: int = 30,
    ):
        """
        Args:
            user_agent: HTTPリクエスト用User-Agent（省略時は環境変数から）
            timeout: HTTPリクエストのタイムアウト秒数
        """
        self.user_agent = (
            user_agent
            or os.environ.get("SFBUFF_DEFAULT_USER_AGENT")
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def get_next_data(self) -> dict[str, Any]:
        """
        Next.jsの_nextデータエンドポイントからページデータを取得

        Returns:
            {
                "buildId": "abc123def456...",
                "pageProps": {...},
                ...その他Next.jsプロパティ
            }

        Raises:
            aiohttp.ClientError: ネットワークエラー
            RuntimeError: buildIdが見つからない場合
        """
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # Step 1: プロフィールページにアクセスしてHTMLを取得
                # Next.jsの__NEXT_DATA__スクリプトタグからbuildIdを抽出
                async with session.get(
                    f"{self.BASE_URL}",
                    headers={"User-Agent": self.user_agent},
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to fetch profile page: {resp.status}")
                        raise RuntimeError(f"HTTP {resp.status} from profile page")

                    html = await resp.text()
                    logger.debug(f"Retrieved profile page: {len(html)} bytes")

                    # __NEXT_DATA__スクリプトタグからJSONを抽出
                    import json
                    import re

                    # Next.jsのデータは <script id="__NEXT_DATA__" type="application/json">
                    match = re.search(
                        r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>',
                        html,
                    )
                    if not match:
                        logger.warning("Could not find __NEXT_DATA__ in HTML response")
                        raise RuntimeError("Could not find Next.js data in profile page")

                    next_data = json.loads(match.group(1))
                    logger.debug(f"Extracted Next.js data: buildId={next_data.get('buildId')}")

                    return next_data

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching Next data: {e}")
            raise

    async def get_build_id(self) -> str:
        """
        buildIdのみを取得

        Returns:
            buildId文字列

        Raises:
            RuntimeError: buildIdが見つからない場合
        """
        next_data = await self.get_next_data()

        build_id = next_data.get("buildId")
        if not build_id:
            raise RuntimeError(f"buildId not found in Next.js data. Available keys: {list(next_data.keys())}")

        logger.info(f"Obtained buildId: {build_id[:20]}...")
        return build_id

    def get_next_data_sync(self) -> dict[str, Any]:
        """同期版get_next_data"""
        return asyncio.run(self.get_next_data())

    def get_build_id_sync(self) -> str:
        """同期版get_build_id"""
        return asyncio.run(self.get_build_id())
