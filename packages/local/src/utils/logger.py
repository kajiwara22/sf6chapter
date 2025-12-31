"""ログ設定モジュール

標準出力と日時ごとのログファイルに同時出力する。
"""

import logging
from pathlib import Path
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler


def setup_logger(name: str = "sf6-chapter", log_dir: str = "logs") -> logging.Logger:
    """ロガーをセットアップする

    Args:
        name: ロガー名
        log_dir: ログディレクトリのパス

    Returns:
        設定済みのLogger
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 既存のハンドラをクリア（重複防止）
    if logger.handlers:
        logger.handlers.clear()

    # ログフォーマット（タイムスタンプ、レベル、モジュール名、メッセージ）
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 標準出力ハンドラ
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # ログディレクトリ作成
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # ファイルハンドラ（日次ローテーション）
    log_file = log_path / f"{name}.log"
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",  # 深夜0時にローテーション
        interval=1,
        backupCount=30,  # 30日分保持
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    # ローテーション時のファイル名に日付を付与
    file_handler.suffix = "%Y%m%d"
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "sf6-chapter") -> logging.Logger:
    """既存のロガーを取得する

    Args:
        name: ロガー名

    Returns:
        Logger
    """
    return logging.getLogger(name)
