"""
CapcomIdAuthenticator - Street Fighter 6公式サイト認証

Playwrightを使用してStreet Fighter 6の公式サイト（Capcom ID）にログインし、
認証クッキーを取得する
"""

import asyncio
import os

from src.utils.logger import get_logger

logger = get_logger()


class CapcomIdAuthenticator:
    """Street Fighter 6公式サイトのブラウザベース認証"""

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
    ):
        """
        Args:
            email: Capcom ID のメールアドレス（省略時は環境変数から）
            password: Capcom ID のパスワード（省略時は環境変数から）
        """
        self.email = email or os.environ.get("BUCKLER_EMAIL")
        self.password = password or os.environ.get("BUCKLER_PASSWORD")

        if not self.email or not self.password:
            raise ValueError(
                "Email and password must be provided or set via environment variables (BUCKLER_EMAIL, BUCKLER_PASSWORD)"
            )

    async def login(self) -> str:
        """
        Playwrightを使用してStreet Fighter 6にログインし、auth_cookieを取得

        Returns:
            認証クッキー文字列

        Raises:
            RuntimeError: ログイン失敗時

        Note:
            環境変数 BUCKLER_ID_COOKIE が設定されている場合、
            Playwright でのログインをスキップしてそれを使用します
        """
        # 環境変数から Cookie が指定されている場合は、それを使用
        env_cookie = os.environ.get("BUCKLER_ID_COOKIE")
        if env_cookie:
            logger.info("Using buckler_id from BUCKLER_ID_COOKIE environment variable")
            return env_cookie

        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise ImportError("playwright is required for BucklerAuthenticator. Install with: pip install playwright") from e

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,  # デバッグ用：ブラウザウィンドウを表示
                slow_mo=100,  # 100ms遅延：操作を目視確認可能に
            )
            context = await browser.new_context()
            page = await context.new_page()

            try:
                logger.info("Starting login to Street Fighter 6 official site...")

                # ストリートファイター公式サイトのログインエンドポイントにアクセス
                login_url = "https://www.streetfighter.com/6/buckler/auth/loginep?redirect_url=/information/all/1"
                await page.goto(
                    login_url,
                    wait_until="domcontentloaded",
                )
                logger.debug(f"Navigated to login page: {login_url}")

                # フォーム要素を待機（ページ読み込み完了を確認）
                await page.wait_for_selector('input[name="email"]', timeout=5000)
                logger.debug("Login form is ready")

                # CapcomID ログインフォーム入力（name属性で検索）
                email_field = page.locator('input[name="email"]')
                if await email_field.count() > 0:
                    await email_field.fill(self.email)
                    logger.debug("Filled email field")
                else:
                    logger.warning("Email field not found")

                password_field = page.locator('input[name="password"]')
                if await password_field.count() > 0:
                    await password_field.fill(self.password)
                    logger.debug("Filled password field")
                else:
                    logger.warning("Password field not found")

                # ログインボタン（name="submit"で検索）
                submit_button = page.locator('button[name="submit"]')
                if await submit_button.count() > 0:
                    await submit_button.click()
                    logger.debug("Clicked submit button")

                    # Cookie 同意ダイアログを手動で処理するのを待機
                    try:
                        # ダイアログが表示されるまで待機（最大10秒）
                        consent_dialog = page.locator('[role="dialog"]')
                        await consent_dialog.wait_for(timeout=10000, state="visible")
                        logger.info("⚠️  Cookie 同意ダイアログが表示されています")
                        logger.info("📋 ブラウザで「必要なCookieのみを使用する」ボタンを手動で押してください")
                        logger.info("⏳ スクリプトが再開を待機しています...")

                        # ダイアログが閉じられるのを待機（最大60秒）
                        await consent_dialog.wait_for(timeout=60000, state="hidden")
                        logger.info("✓ Cookie 同意を確認しました。次の処理に進みます")
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except TimeoutError:
                        logger.debug("No cookie consent dialog displayed (timeout)")
                    except Exception as e:
                        logger.debug(f"Cookie consent handling: {type(e).__name__}")

                    # プラットフォーム選択画面を処理
                    try:
                        # プラットフォーム選択画面を検出（最大5秒待機）
                        platform_heading = page.locator('h1:has-text("Select a platform")')
                        await platform_heading.wait_for(timeout=5000, state="visible")
                        logger.info("プラットフォーム選択画面が表示されました")

                        # 最初のプラットフォーム（PlayStation）をクリック
                        platform_item = page.locator('listitem').first
                        await platform_item.click()
                        logger.debug("Selected first platform (PlayStation)")

                        # 「Confirm Platform」ボタンをクリック
                        confirm_button = page.locator('button:has-text("Confirm Platform")')
                        if await confirm_button.count() > 0:
                            await confirm_button.click()
                            logger.debug("Clicked Confirm Platform button")
                            # プラットフォーム確認後のリダイレクトを待機
                            await page.wait_for_load_state("networkidle", timeout=10000)
                            logger.info("✓ プラットフォーム選択を確認しました")
                        else:
                            logger.warning("Confirm Platform button not found")
                    except TimeoutError:
                        logger.debug("No platform selection screen (timeout)")
                    except Exception as e:
                        logger.debug(f"Platform selection handling: {type(e).__name__}")

                    # ログイン後のリダイレクト待機（クエリパラメータを含む）
                    # パターン: /information/all/1 または /information/all/1?status=login など
                    await page.wait_for_url("**/information/all/1*", timeout=15000)
                    logger.debug(f"Login redirect completed: {page.url}")
                else:
                    logger.warning("Submit button not found")

                # クッキーから認証トークンを抽出
                cookies = await context.cookies()
                logger.debug(f"Retrieved {len(cookies)} cookies")

                # すべてのクッキーをログ出力（デバッグ用）
                cookie_names = [c["name"] for c in cookies]
                logger.debug(f"Available cookies: {cookie_names}")
                for cookie in cookies:
                    logger.debug(f"  - {cookie['name']}: {cookie['value'][:50] if len(cookie['value']) > 50 else cookie['value']}")

                # 可能性のある認証クッキー名（優先順）
                auth_cookie_names = [
                    "buckler_id",  # Street Fighter 6 認証クッキー（最優先）
                    "auth_token",
                    "authentication_token",
                    "session",
                    "_session_id",
                    "sid",
                    "capcom_auth",
                    "streetfighter_auth",
                    "SESSION",
                ]

                auth_cookie = None
                for cookie_name in auth_cookie_names:
                    matching_cookies = [c["value"] for c in cookies if c["name"].lower() == cookie_name.lower()]
                    if matching_cookies:
                        auth_cookie = matching_cookies[0]
                        logger.info(f"Found auth cookie: {cookie_name}")
                        break

                # クッキーが見つからない場合は、セッション関連を試す
                if not auth_cookie:
                    logger.warning("No recognized auth cookie found. Searching for session-related cookies...")
                    # セッション関連のクッキーを試す
                    for cookie in cookies:
                        if any(keyword in cookie["name"].lower() for keyword in ["buckler", "session", "auth", "token", "sid", "capcom"]):
                            auth_cookie = cookie["value"]
                            logger.info(f"Using cookie: {cookie['name']}")
                            break

                if not auth_cookie:
                    raise RuntimeError(f"Failed to extract auth cookie from login. Available cookies: {', '.join(cookie_names)}")

                logger.info("Successfully obtained authentication cookie")
                return auth_cookie

            finally:
                await browser.close()

    def login_sync(self) -> str:
        """
        同期版ログイン（asyncioイベントループが無い場合用）

        Returns:
            認証クッキー文字列
        """
        return asyncio.run(self.login())
