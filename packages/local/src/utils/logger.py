"""ログ設定モジュール

標準出力と起動時刻ベースのログファイルに同時出力する。
"""

import logging
from pathlib import Path
from datetime import datetime


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

    # 起動時刻をファイル名に含める
    startup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_path / f"{name}_{startup_time}.log"

    # ファイルハンドラ
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
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
