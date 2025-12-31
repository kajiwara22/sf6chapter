"""
共通認証モジュール
YouTube API と Gemini API の OAuth2 認証を統一管理
"""

from .oauth import get_oauth_credentials

__all__ = ["get_oauth_credentials"]
