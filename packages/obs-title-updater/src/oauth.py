"""
OAuth2認証の共通処理

OBS Title Updater用のOAuth2認証
YouTube Data APIスコープのみをサポート
"""

import pickle
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

__all__ = ["get_oauth_credentials"]


def get_oauth_credentials(
    token_path: str | None = None,
    client_secrets_path: str | None = None,
    scopes: list[str] | None = None,
) -> Credentials:
    """
    OAuth2認証情報を取得

    Args:
        token_path: トークンファイルのパス（デフォルト: token.pickle）
        client_secrets_path: クライアントシークレットファイルのパス（デフォルト: client_secrets.json）
        scopes: OAuth2スコープのリスト

    Returns:
        認証済みのCredentials

    Raises:
        FileNotFoundError: client_secrets_pathが存在しない場合
    """
    # デフォルトパスの設定
    if token_path is None:
        token_path = "token.pickle"
    if client_secrets_path is None:
        client_secrets_path = "client_secrets.json"

    if scopes is None:
        # デフォルトスコープ（YouTube Data API）
        scopes = ["https://www.googleapis.com/auth/youtube.force-ssl"]

    # client_secrets_pathの存在確認
    if not Path(client_secrets_path).exists():
        raise FileNotFoundError(
            f"OAuth2クライアントシークレットファイルが見つかりません: {client_secrets_path}\n"
            "Google Cloud Consoleから取得してください。\n"
            "https://console.cloud.google.com/apis/credentials"
        )

    creds = None

    # 保存済みトークンを読み込み（pickle形式）
    if Path(token_path).exists():
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    # トークンが無効な場合は再認証
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # トークンをリフレッシュ
            creds.refresh(Request())
        else:
            # 新規認証フロー
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, scopes)
            creds = flow.run_local_server(port=0)

        # トークンを保存（pickle形式）
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    return creds
