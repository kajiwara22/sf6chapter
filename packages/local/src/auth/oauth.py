"""
OAuth2認証の共通処理
YouTube Data API と Vertex AI (Gemini API) で同じ認証情報を使用
"""

import pickle
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


def get_oauth_credentials(
    client_secrets_file: str = "client_secrets.json",
    token_file: str = "token.pickle",
    scopes: list[str] | None = None,
) -> Credentials:
    """
    OAuth2認証情報を取得

    Args:
        client_secrets_file: OAuth2クライアントシークレットファイルのパス
        token_file: 認証トークン保存ファイルのパス（pickle形式）
        scopes: OAuth2スコープのリスト

    Returns:
        認証済みのCredentials

    Raises:
        FileNotFoundError: client_secrets_fileが存在しない場合
    """
    if scopes is None:
        # デフォルトスコープ（YouTube + Vertex AI）
        scopes = [
            "https://www.googleapis.com/auth/youtube.force-ssl",  # YouTube Data API
            "https://www.googleapis.com/auth/cloud-platform",  # Vertex AI (Gemini API)
        ]

    # client_secrets_fileの存在確認
    if not Path(client_secrets_file).exists():
        raise FileNotFoundError(
            f"OAuth2クライアントシークレットファイルが見つかりません: {client_secrets_file}\n"
            "Google Cloud Consoleから取得してください。\n"
            "https://console.cloud.google.com/apis/credentials"
        )

    creds = None

    # 保存済みトークンを読み込み（pickle形式）
    if Path(token_file).exists():
        with open(token_file, "rb") as token:
            creds = pickle.load(token)

    # トークンが無効な場合は再認証
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # トークンをリフレッシュ
            creds.refresh(Request())
        else:
            # 新規認証フロー
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, scopes)
            creds = flow.run_local_server(port=0)

        # トークンを保存（pickle形式）
        with open(token_file, "wb") as token:
            pickle.dump(creds, token)

    return creds
