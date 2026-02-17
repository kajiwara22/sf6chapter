"""
BattlelogCacheManager - SQLite ベースのキャッシング機構

Battlelog API のレスポンスをキャッシュして、重複リクエストを削減。
キャッシュキーは player_id + uploaded_at の組み合わせ。
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger()


class BattlelogCacheManager:
    """SQLite ベースの Battlelog キャッシュ管理"""

    DB_SCHEMA_VERSION = 1

    def __init__(self, db_path: str = "./battlelog_cache.db"):
        """
        キャッシュマネージャーを初期化

        Args:
            db_path: SQLite データベースのパス
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """データベースを初期化（テーブル作成）"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # テーブルが存在しなければ作成
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                replay_data TEXT NOT NULL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(player_id, uploaded_at)
            )
            """
        )

        # インデックスを作成
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_player_id ON replay_cache(player_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploaded_at ON replay_cache(uploaded_at)"
        )

        conn.commit()
        conn.close()
        logger.debug(f"Database initialized: {self.db_path}")

    def cache_replay(self, player_id: str, replay: dict[str, Any]) -> bool:
        """
        単一の対戦ログをキャッシュに保存

        Args:
            player_id: プレイヤーID
            replay: 対戦ログオブジェクト

        Returns:
            新規追加時は True、既存時（重複）は False

        Raises:
            KeyError: replay に uploaded_at がない場合
            sqlite3.Error: データベースエラー
        """
        uploaded_at = replay.get("uploaded_at")
        if uploaded_at is None:
            raise KeyError("replay must have 'uploaded_at' field")

        replay_json = json.dumps(replay, ensure_ascii=False)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO replay_cache (player_id, uploaded_at, replay_data)
                VALUES (?, ?, ?)
                """,
                (player_id, str(uploaded_at), replay_json),
            )
            conn.commit()
            logger.debug(
                f"Cached replay: player_id={player_id}, uploaded_at={uploaded_at}"
            )
            return True

        except sqlite3.IntegrityError:
            # UNIQUE 制約違反 = 既に存在
            logger.debug(
                f"Replay already cached: player_id={player_id}, uploaded_at={uploaded_at}"
            )
            return False

        finally:
            conn.close()

    def cache_replays(self, player_id: str, replays: list[dict[str, Any]]) -> int:
        """
        複数の対戦ログを一括キャッシュ

        Args:
            player_id: プレイヤーID
            replays: 対戦ログの配列

        Returns:
            新規追加されたレコード数

        Raises:
            sqlite3.Error: データベースエラー
        """
        count = 0
        for replay in replays:
            if self.cache_replay(player_id, replay):
                count += 1
        return count

    def get_cached_replays(self, player_id: str) -> list[dict[str, Any]]:
        """
        キャッシュから player_id に一致するすべての対戦ログを取得

        Args:
            player_id: プレイヤーID

        Returns:
            対戦ログの配列（キャッシュなしの場合は空配列）

        Raises:
            sqlite3.Error: データベースエラー
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT replay_data FROM replay_cache WHERE player_id = ? ORDER BY uploaded_at DESC",
                (player_id,),
            )
            rows = cursor.fetchall()

            replays = []
            for row in rows:
                replay = json.loads(row[0])
                replays.append(replay)

            logger.debug(f"Retrieved {len(replays)} cached replays for {player_id}")
            return replays

        finally:
            conn.close()

    def get_cached_uploaded_at_set(self, player_id: str) -> set[str]:
        """
        特定 player_id のキャッシュ済み uploaded_at 値の集合を取得

        キャッシュの有無判定に利用

        Args:
            player_id: プレイヤーID

        Returns:
            uploaded_at 値の集合

        Raises:
            sqlite3.Error: データベースエラー
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT uploaded_at FROM replay_cache WHERE player_id = ?",
                (player_id,),
            )
            rows = cursor.fetchall()
            result = {str(row[0]) for row in rows}
            logger.debug(f"Found {len(result)} cached uploaded_at values for {player_id}")
            return result

        finally:
            conn.close()

    def get_all_cached_replays(self) -> list[dict[str, Any]]:
        """
        キャッシュ全体のすべての対戦ログを取得

        Returns:
            対戦ログの配列

        Raises:
            sqlite3.Error: データベースエラー
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT replay_data FROM replay_cache ORDER BY cached_at DESC"
            )
            rows = cursor.fetchall()

            replays = []
            for row in rows:
                replay = json.loads(row[0])
                replays.append(replay)

            logger.debug(f"Retrieved {len(replays)} total cached replays")
            return replays

        finally:
            conn.close()

    def clear_cache(self, player_id: Optional[str] = None) -> int:
        """
        キャッシュをクリア

        Args:
            player_id: 削除対象の player_id（未指定時は全削除）

        Returns:
            削除されたレコード数

        Raises:
            sqlite3.Error: データベースエラー
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            if player_id:
                cursor.execute(
                    "DELETE FROM replay_cache WHERE player_id = ?", (player_id,)
                )
                logger.info(f"Cleared cache for player_id={player_id}")
            else:
                cursor.execute("DELETE FROM replay_cache")
                logger.info("Cleared all cache")

            conn.commit()
            return cursor.rowcount

        finally:
            conn.close()

    def get_cache_stats(self) -> dict[str, Any]:
        """
        キャッシュ統計情報を取得

        Returns:
            統計情報の辞書

        Raises:
            sqlite3.Error: データベースエラー
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            # 全レコード数
            cursor.execute("SELECT COUNT(*) FROM replay_cache")
            total_records = cursor.fetchone()[0]

            # プレイヤー数
            cursor.execute("SELECT COUNT(DISTINCT player_id) FROM replay_cache")
            unique_players = cursor.fetchone()[0]

            # プレイヤーごとのレコード数
            cursor.execute(
                "SELECT player_id, COUNT(*) FROM replay_cache GROUP BY player_id ORDER BY COUNT(*) DESC"
            )
            unique_replays_by_player = {row[0]: row[1] for row in cursor.fetchall()}

            # データベースファイルサイズ
            db_size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0

            stats = {
                "total_records": total_records,
                "unique_players": unique_players,
                "unique_replays_by_player": unique_replays_by_player,
                "db_size_bytes": db_size_bytes,
            }

            logger.debug(f"Cache stats: {stats}")
            return stats

        finally:
            conn.close()

    def get_latest_uploaded_at(self, player_id: str) -> int | None:
        """
        特定 player_id のキャッシュ済み対戦ログで最新の uploaded_at を取得

        Returns:
            最新の uploaded_at（キャッシュなしの場合は None）

        Raises:
            sqlite3.Error: データベースエラー
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT MAX(CAST(uploaded_at AS INTEGER)) FROM replay_cache WHERE player_id = ?",
                (player_id,),
            )
            result = cursor.fetchone()[0]
            logger.debug(f"Latest cached uploaded_at for {player_id}: {result}")
            return result  # None or int

        finally:
            conn.close()

    def has_reached_cache_boundary(
        self,
        player_id: str,
        current_page_replays: list[dict[str, Any]],
    ) -> bool:
        """
        現在のページが最新キャッシュに到達したかを判定

        Args:
            player_id: プレイヤーID
            current_page_replays: 現在のページから取得した対戦ログリスト

        Returns:
            キャッシュ境界に到達した場合は True

        Raises:
            sqlite3.Error: データベースエラー
        """
        if not current_page_replays:
            logger.debug(f"Empty page for {player_id}: reached boundary")
            return True  # 空ページ = 終了

        latest_cached_at = self.get_latest_uploaded_at(player_id)
        if latest_cached_at is None:
            logger.debug(f"No cache for {player_id}: continue fetching")
            return False  # キャッシュなし = まだ続行

        # 現在のページの最も古い対戦ログがキャッシュの最新より古い = 境界到達
        oldest_in_page = min(
            int(r.get("uploaded_at", float("inf"))) for r in current_page_replays
        )
        has_reached = oldest_in_page <= latest_cached_at
        logger.debug(
            f"Cache boundary check for {player_id}: "
            f"oldest_in_page={oldest_in_page}, latest_cached_at={latest_cached_at}, "
            f"reached={has_reached}"
        )
        return has_reached
