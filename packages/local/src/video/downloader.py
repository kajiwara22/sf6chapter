"""
YouTube動画ダウンロードモジュール
yt-dlpを使用して動画をダウンロード
"""

import os
import re
from pathlib import Path
from typing import Any

import yt_dlp

from ..utils.logger import get_logger

logger = get_logger()


def _strip_ansi(text: str) -> str:
    """ANSIエスケープシーケンスを除去する"""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class _YtDlpLogger:
    """yt-dlpの出力をPython loggingに橋渡しするアダプター"""

    def __init__(self, error_sink: list[str] | None = None) -> None:
        self.error_sink = error_sink if error_sink is not None else []

    def debug(self, msg: str) -> None:
        # yt-dlpはprogressメッセージもdebugとして送るため、WARNINGより低いレベルで出力
        if msg.startswith("[download]") or msg.startswith("[hlsnative]"):
            logger.info(msg)
        else:
            logger.debug(msg)

    def info(self, msg: str) -> None:
        logger.info(msg)

    def warning(self, msg: str) -> None:
        logger.warning(msg)

    def error(self, msg: str) -> None:
        if self.error_sink is not None:
            self.error_sink.append(msg)
        logger.error(msg)


class VideoDownloader:
    """YouTube動画ダウンローダー"""

    def __init__(
        self,
        download_dir: str = "./download",
        cookie_path: str | None = None,
        player_client: str | None = None,
    ):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.cookie_path = cookie_path
        # デフォルトはweb_embedded。yt-dlpの既定クライアント(android_vr等)は
        # 2026年時点でYouTubeからHTTP 403を返されることが多いため。
        # 環境変数 YTDLP_PLAYER_CLIENT で上書き可能（無効化する場合は空文字）。
        if player_client is not None:
            self.player_client = player_client or None
        else:
            self.player_client = os.environ.get("YTDLP_PLAYER_CLIENT", "web_embedded") or None
        # OpenCVのVideoCaptureがデコードできるよう、既定ではH.264(avc1)を優先する。
        # yt-dlpの既定選択はAV1(av01)を選ぶことがあり、その場合フレーム抽出で
        # 「Your platform doesn't support hardware accelerated AV1 decoding」が発生する。
        # 環境変数 YTDLP_FORMAT で上書き可能。
        self.default_format = os.environ.get("YTDLP_FORMAT", "bv*[vcodec^=avc1]+ba/b")

    def download(
        self,
        video_id: str,
        format_option: str | None = None,
        skip_if_exists: bool = False,
    ) -> str:
        """
        動画をダウンロード

        Args:
            video_id: YouTube動画ID
            format_option: フォーマット指定（省略時は最高品質）
            skip_if_exists: Trueの場合、既存ファイルがあればダウンロードをスキップ

        Returns:
            ダウンロードされたファイルパス
        """
        # 既存ファイルチェック
        if skip_if_exists:
            existing_file = self._find_existing_file(video_id)
            if existing_file:
                logger.info("既存ファイルを使用: %s", existing_file)
                return str(existing_file)

        attempt_client = self.player_client
        info: dict[str, Any] = {}

        while True:
            ret, info, fragment_errors, download_errors = self._download_once(
                video_id, format_option, player_client=attempt_client
            )

            # フラグメント欠損はタイムスタンプずれに直結するため中断（ADR-044）
            if fragment_errors:
                raise RuntimeError(
                    f"フラグメント取得エラーが発生したためダウンロードを中断しました "
                    f"(video_id={video_id}, errors={len(fragment_errors)}件): {fragment_errors[0]}"
                )

            if ret == 0:
                break

            last_error = _strip_ansi(download_errors[-1]) if download_errors else f"yt-dlp exit code={ret}"

            # YouTube側のボット判定で403が返る場合、web_embeddedクライアントで1回だけ再試行する
            if "403" in last_error and attempt_client != "web_embedded":
                logger.warning(
                    "HTTP 403が返されたため player_client=web_embedded で再試行します (video_id=%s): %s",
                    video_id,
                    last_error,
                )
                attempt_client = "web_embedded"
                continue

            raise RuntimeError(f"動画のダウンロードに失敗しました (video_id={video_id}): {last_error}")

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

    def _download_once(
        self,
        video_id: str,
        format_option: str | None = None,
        player_client: str | None = None,
    ) -> tuple[int, dict[str, Any], list[str], list[str]]:
        """yt-dlpで1回だけダウンロードを試みる。

        Returns:
            (戻り値, info, フラグメントエラー一覧, yt-dlpエラー一覧)
        """
        url = f"https://www.youtube.com/watch?v={video_id}"

        fragment_errors: list[str] = []
        download_errors: list[str] = []

        ydl_opts: dict[str, Any] = {
            "outtmpl": str(self.download_dir / "%(upload_date)s[%(id)s].%(ext)s"),
            "ignoreerrors": True,
            "logger": _YtDlpLogger(download_errors),
        }

        if self.cookie_path:
            ydl_opts["cookiefile"] = self.cookie_path

        if format_option:
            ydl_opts["format"] = format_option
        else:
            ydl_opts["format"] = self.default_format

        client = player_client if player_client is not None else self.player_client
        if client:
            ydl_opts["extractor_args"] = {"youtube": {"player_client": [client]}}

        def _on_progress(d: dict[str, Any]) -> None:
            if d.get("status") == "error":
                msg = str(d.get("error", "unknown fragment error"))
                fragment_errors.append(msg)

        ydl_opts["progress_hooks"] = [_on_progress]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 動画情報取得
            info_raw = ydl.extract_info(url, download=False)
            if not info_raw:
                raise ValueError(f"Failed to get video info: {video_id}")

            # JSON直列化可能な形式に変換（yt-dlp推奨）
            info = ydl.sanitize_info(info_raw)

            # ダウンロード
            ret = ydl.download([url])

        return ret, info, fragment_errors, download_errors

    def _find_existing_file(self, video_id: str) -> Path | None:
        """
        指定されたvideo_idの既存ファイルを検索

        Args:
            video_id: YouTube動画ID

        Returns:
            既存ファイルのパス（存在しない場合はNone）
        """
        # globのcharacter class解釈を避けるため、ファイル一覧を手動でスキャン
        for file_path in self.download_dir.iterdir():
            if not file_path.is_file():
                continue
            file_name = file_path.name
            # video_idが[...]で囲まれているか確認
            if f"[{video_id}]" not in file_name:
                continue
            # yt-dlpの一時ファイル（.part / .ytdl / 単一フォーマットの .f{id}.ext）は除外
            if file_name.endswith((".part", ".ytdl")) or "].f" in file_name:
                continue
            return file_path
        return None

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
            "logger": _YtDlpLogger(),
        }

        if self.cookie_path:
            ydl_opts["cookiefile"] = self.cookie_path

        if self.player_client:
            ydl_opts["extractor_args"] = {"youtube": {"player_client": [self.player_client]}}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_raw = ydl.extract_info(url, download=False)
            if not info_raw:
                raise ValueError(f"Failed to get video info: {video_id}")

            # JSON直列化可能な形式に変換（yt-dlp推奨）
            info = ydl.sanitize_info(info_raw)

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
