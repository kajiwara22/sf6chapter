"""
YouTube Data APIを使用したチャプター更新
動画の説明文にチャプター情報を追加
"""

import pickle
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


class YouTubeChapterUpdater:
    """YouTube チャプター更新器"""

    SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

    def __init__(
        self,
        client_secrets_file: str = "client_secrets.json",
        token_file: str = "token.pickle",
    ):
        """
        Args:
            client_secrets_file: OAuth2クライアントシークレットファイルのパス
            token_file: 認証トークン保存ファイルのパス
        """
        self.client_secrets_file = client_secrets_file
        self.token_file = token_file
        self.youtube = self._get_authenticated_service()

    def _get_authenticated_service(self):
        """認証済みYouTube Data APIサービスを取得"""
        creds = None

        # 保存済みトークンを読み込み
        if Path(self.token_file).exists():
            with open(self.token_file, "rb") as token:
                creds = pickle.load(token)

        # トークンが無効な場合は再認証
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, self.SCOPES)
                creds = flow.run_local_server(port=0)

            # トークンを保存
            with open(self.token_file, "wb") as token:
                pickle.dump(creds, token)

        return build("youtube", "v3", credentials=creds)

    def get_video_info(self, video_id: str) -> dict[str, Any]:
        """
        動画情報を取得

        Args:
            video_id: YouTube動画ID

        Returns:
            動画情報
        """
        request = self.youtube.videos().list(part="snippet,contentDetails", id=video_id)
        response = request.execute()

        if not response.get("items"):
            raise ValueError(f"Video not found: {video_id}")

        item = response["items"][0]
        return {
            "title": item["snippet"]["title"],
            "description": item["snippet"]["description"],
            "channelId": item["snippet"]["channelId"],
            "channelTitle": item["snippet"]["channelTitle"],
            "publishedAt": item["snippet"]["publishedAt"],
            "duration": item["contentDetails"]["duration"],
        }

    def format_timestamp(self, seconds: float) -> str:
        """
        秒数をYouTubeチャプター形式のタイムスタンプに変換

        Args:
            seconds: 秒数

        Returns:
            タイムスタンプ文字列（例: "1:23:45" or "12:34"）
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"

    def generate_chapter_description(
        self,
        chapters: list[dict[str, Any]],
        original_description: str = "",
    ) -> str:
        """
        チャプター情報を含む説明文を生成

        Args:
            chapters: チャプター情報リスト
                     [{"startTime": 47, "title": "第01戦 Ryu VS Ken"}, ...]
            original_description: 元の説明文

        Returns:
            チャプター付き説明文
        """
        # チャプター部分を生成
        chapter_lines = ["0:00 本編開始"]

        for chapter in sorted(chapters, key=lambda x: x["startTime"]):
            timestamp = self.format_timestamp(chapter["startTime"])
            title = chapter["title"]
            chapter_lines.append(f"{timestamp} {title}")

        chapter_text = "\n".join(chapter_lines)

        # 元の説明文と結合
        if original_description:
            # 既存のチャプター情報を削除（0:00から始まる行を検出）
            lines = original_description.split("\n")
            non_chapter_lines = []
            in_chapter_section = False

            for line in lines:
                if line.strip().startswith("0:00"):
                    in_chapter_section = True
                    continue
                if in_chapter_section and ":" in line and line.strip()[0].isdigit():
                    continue
                in_chapter_section = False
                non_chapter_lines.append(line)

            original_text = "\n".join(non_chapter_lines).strip()
            return f"{chapter_text}\n\n{original_text}"
        else:
            return chapter_text

    def update_video_description(
        self,
        video_id: str,
        chapters: list[dict[str, Any]],
        preserve_original: bool = True,
    ) -> None:
        """
        動画の説明文にチャプター情報を追加

        Args:
            video_id: YouTube動画ID
            chapters: チャプター情報リスト
            preserve_original: 元の説明文を保持するか
        """
        # 現在の動画情報を取得
        video_info = self.get_video_info(video_id)

        # 新しい説明文を生成
        original_description = video_info["description"] if preserve_original else ""
        new_description = self.generate_chapter_description(chapters, original_description)

        # 説明文を更新
        request = self.youtube.videos().update(
            part="snippet",
            body={
                "id": video_id,
                "snippet": {
                    "title": video_info["title"],
                    "description": new_description,
                    "categoryId": "20",  # Gaming
                },
            },
        )
        request.execute()

        print(f"Updated description for video {video_id}")
        print(f"Added {len(chapters)} chapters")
