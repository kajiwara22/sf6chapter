"""
YouTube動画ダウンロードモジュール
yt-dlpを使用して動画をダウンロード
"""

from pathlib import Path
from typing import Any

import yt_dlp


class VideoDownloader:
    """YouTube動画ダウンローダー"""

    def __init__(
        self,
        download_dir: str = "./download",
        cookie_path: str | None = None,
    ):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.cookie_path = cookie_path

    def download(
        self,
        video_id: str,
        format_option: str | None = None,
    ) -> str:
        """
        動画をダウンロード

        Args:
            video_id: YouTube動画ID
            format_option: フォーマット指定（省略時は最高品質）

        Returns:
            ダウンロードされたファイルパス
        """
        url = f"https://www.youtube.com/watch?v={video_id}"

        ydl_opts: dict[str, Any] = {
            "outtmpl": str(self.download_dir / "%(upload_date)s[%(id)s].%(ext)s"),
            "ignoreerrors": True,
        }

        if self.cookie_path:
            ydl_opts["cookiefile"] = self.cookie_path

        if format_option:
            ydl_opts["format"] = format_option

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 動画情報取得
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError(f"Failed to get video info: {video_id}")

            # ダウンロード
            ydl.download([url])

            # ダウンロードされたファイルパスを推定
            upload_date = info.get("upload_date", "unknown")
            ext = info.get("ext", "mp4")
            file_path = self.download_dir / f"{upload_date}[{video_id}].{ext}"

            # 拡張子候補を検索
            if not file_path.exists():
                for candidate_ext in ["mp4", "webm", "mkv"]:
                    candidate = self.download_dir / f"{upload_date}[{video_id}].{candidate_ext}"
                    if candidate.exists():
                        file_path = candidate
                        break

            if not file_path.exists():
                raise FileNotFoundError(f"Downloaded file not found: {file_path}")

            return str(file_path)

    def get_video_info(self, video_id: str) -> dict[str, Any]:
        """
        動画情報を取得（ダウンロードなし）

        Args:
            video_id: YouTube動画ID

        Returns:
            動画メタデータ
        """
        url = f"https://www.youtube.com/watch?v={video_id}"

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
        }

        if self.cookie_path:
            ydl_opts["cookiefile"] = self.cookie_path

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError(f"Failed to get video info: {video_id}")

            return {
                "videoId": video_id,
                "title": info.get("title"),
                "duration": info.get("duration"),
                "uploadDate": info.get("upload_date"),
                "description": info.get("description"),
                "thumbnailUrl": info.get("thumbnail"),
                "channelId": info.get("channel_id"),
                "channelTitle": info.get("uploader"),
            }
