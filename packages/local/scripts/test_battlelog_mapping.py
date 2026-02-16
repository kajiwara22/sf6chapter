#!/usr/bin/env python3
"""
SF6 Battlelog マッピング検証スクリプト

YouTubeのチャプター情報とBattlelogの対戦ログをマッピングし、
勝敗情報を付与できるかを検証。

使用方法:
    uv run scripts/test_battlelog_mapping.py \\
        --video-id dQwqkOG2SQo \\
        --player-id 1319673732 \\
        --chapters-file ./intermediate/dQwqkOG2SQo/chapters.json \\
        [--output-format json|pretty]

環境変数:
    BUCKLER_ID_COOKIE: 認証用 buckler_id クッキー
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# プロジェクトのsrcディレクトリをpythonpathに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sf6_battlelog import BattlelogCollector, BattlelogSiteClient
from utils.logger import get_logger
from auth.oauth import get_oauth_credentials
from googleapiclient.discovery import build

logger = get_logger()


class CharacterNormalizer:
    """キャラクター名の正規化"""

    def __init__(self, aliases_file: Optional[str] = None):
        """
        Args:
            aliases_file: character_aliases.json のパス
        """
        self.aliases_map = {}
        if aliases_file and Path(aliases_file).exists():
            self._load_aliases(aliases_file)
        else:
            # デフォルトの簡易マッピング
            self._setup_default_aliases()

    def _load_aliases(self, file_path: str) -> None:
        """aliases ファイルから読み込み"""
        with open(file_path) as f:
            data = json.load(f)
            for char_key, char_data in data.get("characters", {}).items():
                canonical = char_data.get("canonical", char_key)
                for alias in char_data.get("aliases", []):
                    self.aliases_map[alias.lower()] = canonical

    def _setup_default_aliases(self) -> None:
        """デフォルトの正規化マッピング"""
        self.aliases_map = {
            # Akuma / Gouki
            "akuma": "GOUKI",
            "豪鬼": "GOUKI",
            "gouki": "GOUKI",
            # JP
            "jp": "JP",
            "j.p.": "JP",
            "ジェイピー": "JP",
            # Blanka
            "blanka": "BLANKA",
            "ブランカ": "BLANKA",
            # Chun-Li
            "chun-li": "CHUN-LI",
            "chunli": "CHUN-LI",
            "春麗": "CHUN-LI",
            # Dhalsim
            "dhalsim": "DHALSIM",
            "ダルシム": "DHALSIM",
            # Dee Jay
            "dee jay": "DEE JAY",
            "deejay": "DEE JAY",
            "ディージェイ": "DEE JAY",
            # Guile
            "guile": "GUILE",
            "ガイル": "GUILE",
            # Marisa
            "marisa": "MARISA",
            "マリーザ": "MARISA",
            # Manon
            "manon": "MANON",
            "マノン": "MANON",
            # Ryu
            "ryu": "RYU",
            "リュウ": "RYU",
            # Ken
            "ken": "KEN",
            "ケン": "KEN",
            # Mai
            "mai": "MAI",
            "マイ": "MAI",
            "不知火舞": "MAI",
            # Ed
            "ed": "ED",
            "エド": "ED",
        }

    def normalize(self, name: str) -> str:
        """
        キャラクター名を正規化

        Args:
            name: キャラクター名（大文字小文字混在、日本語など）

        Returns:
            正規化されたキャラクター名（大文字）
        """
        normalized = self.aliases_map.get(name.lower(), name.upper())
        return normalized


class BattlelogMatcher:
    """Battlelogマッチング処理"""

    def __init__(self, normalizer: CharacterNormalizer):
        self.normalizer = normalizer

    def extract_chapter_characters(self, chapter_title: str) -> Optional[tuple[str, str]]:
        """
        チャプターのタイトルからキャラクター名を抽出

        Args:
            chapter_title: チャプタータイトル（例: "GOUKI VS JP"）

        Returns:
            (char1, char2) または None
        """
        if " VS " not in chapter_title:
            return None

        parts = chapter_title.split(" VS ")
        if len(parts) != 2:
            return None

        char1 = parts[0].strip()
        char2 = parts[1].strip()
        return (char1, char2)

    def extract_battlelog_characters(
        self, replay: dict[str, Any]
    ) -> tuple[str, str]:
        """
        Battlelogレコードからキャラクター名を抽出

        Args:
            replay: Battlelogのレプレイ情報

        Returns:
            (char1, char2)
        """
        # playing_character_tool_name を優先、フォールバック として character_name
        p1_char = (
            replay.get("player1_info", {}).get("playing_character_tool_name")
            or replay.get("player1_info", {}).get("character_name", "Unknown")
        )
        p2_char = (
            replay.get("player2_info", {}).get("playing_character_tool_name")
            or replay.get("player2_info", {}).get("character_name", "Unknown")
        )
        return (p1_char, p2_char)

    def extract_battle_results(
        self, replay: dict[str, Any]
    ) -> tuple[str, str]:
        """
        Battlelogレコードから各プレイヤーの勝敗を判定

        Args:
            replay: Battlelogのレプレイ情報

        Returns:
            (player1_result, player2_result) - "win" または "loss"
        """
        p1_results = replay.get("player1_info", {}).get("round_results", [])
        p2_results = replay.get("player2_info", {}).get("round_results", [])

        p1_wins = sum(1 for r in p1_results if r > 0)
        p2_wins = sum(1 for r in p2_results if r > 0)

        # 勝敗を判定
        if p1_wins > p2_wins:
            p1_result = "win"
            p2_result = "loss"
        else:
            p1_result = "loss"
            p2_result = "win"

        return (p1_result, p2_result)

    def _determine_confidence_level(self, time_diff: float) -> str:
        """
        時間差に基づいて信頼度レベルを決定

        仕様に従う:
        - high: 時間差180秒以内
        - medium: 時間差180〜600秒
        - low: キャラクター不一致 またはマッチなし（この関数では呼ばれない）

        Args:
            time_diff: 時刻差（秒）

        Returns:
            信頼度レベル ("high" | "medium")
        """
        if time_diff <= 180:
            return "high"
        elif time_diff <= 600:
            return "medium"
        else:
            return "low"

    def match_chapter_with_battlelog(
        self,
        chapter: dict[str, Any],
        battlelog_replays: list[dict[str, Any]],
        video_published_at: str,
        used_replay_ids: set[str],
        tolerance_seconds: int = 600,  # 最大 10分
    ) -> dict[str, Any]:
        """
        チャプターをBattlelogの対戦と照合

        マッピングロジック:
        1. チャプター推定時刻 = 配信開始時刻 + startTime
        2. キャラクター名を照合（文字揺れ吸収）
        3. 時間差が最小のリプレイを選択
        4. 時間差600秒超は失敗、重複排除

        Args:
            chapter: チャプター情報
            battlelog_replays: Battlelogの対戦ログ（アップロード時刻昇順）
            video_published_at: 動画公開日時（ISO 8601）
            used_replay_ids: 既にマッチ済みのリプレイID集合
            tolerance_seconds: 時刻差の許容範囲（秒、デフォルト: 600秒=10分）

        Returns:
            マッピング結果
            {
                "matched": bool,
                "confidence": "high" | "medium" | "low",
                "player1_character": str | None,
                "player1_result": "win" | "loss" | None,
                "player2_character": str | None,
                "player2_result": "win" | "loss" | None,
                "replay_id": str | None,
                "uploaded_at": int | None,
                "time_difference_seconds": int | None,
                "details": str,
            }
        """
        chapter_title = chapter.get("title", "")
        start_time = chapter.get("startTime", 0)

        # ステップ1: チャプターのキャラクター名を抽出
        chapter_chars = self.extract_chapter_characters(chapter_title)
        if not chapter_chars:
            logger.info(f"  ✗ {start_time}s: {chapter_title} - VS抽出失敗")
            return {
                "matched": False,
                "confidence": "low",
                "player1_character": None,
                "player1_result": None,
                "player2_character": None,
                "player2_result": None,
                "replay_id": None,
                "uploaded_at": None,
                "time_difference_seconds": None,
                "details": f"Failed to extract characters from title: {chapter_title}",
            }

        chapter_char1, chapter_char2 = chapter_chars
        chapter_chars_set = {
            self.normalizer.normalize(chapter_char1),
            self.normalizer.normalize(chapter_char2),
        }

        logger.debug(
            f"  チャプター {start_time}s: {chapter_title} "
            f"→ {chapter_chars_set}"
        )

        # ステップ1: 動画公開日時をパース
        try:
            video_time = datetime.fromisoformat(
                video_published_at.replace("Z", "+00:00")
            )
        except Exception as e:
            logger.error(f"Failed to parse video_published_at: {e}")
            return {
                "matched": False,
                "confidence": "low",
                "player1_character": None,
                "player1_result": None,
                "player2_character": None,
                "player2_result": None,
                "replay_id": None,
                "uploaded_at": None,
                "time_difference_seconds": None,
                "details": f"Failed to parse video_published_at: {e}",
            }

        # チャプターの推定絶対時刻を計算
        chapter_absolute_time = video_time + timedelta(seconds=start_time)

        # ステップ2&3: キャラクター一致 + 時間差最小のリプレイを探す
        best_match = None
        min_time_diff = float("inf")

        for replay in battlelog_replays:
            replay_id = replay.get("replay_id")

            # 既にマッチ済みならスキップ
            if replay_id in used_replay_ids:
                continue

            # キャラクターを抽出・正規化
            p1_char, p2_char = self.extract_battlelog_characters(replay)
            battlelog_chars_set = {
                self.normalizer.normalize(p1_char),
                self.normalizer.normalize(p2_char),
            }

            # ステップ2: キャラクター名が一致するか？
            if chapter_chars_set != battlelog_chars_set:
                continue

            # 時刻をチェック
            uploaded_at = replay.get("uploaded_at")
            if not uploaded_at:
                continue

            try:
                replay_time = datetime.fromtimestamp(uploaded_at, tz=timezone.utc)
                time_diff = (replay_time - chapter_absolute_time).total_seconds()

                # ステップ3: 時間差が正か、許容範囲内か確認
                # リプレイは試合後のアップロードなので、時間差は正の値になるはず
                if time_diff < 0:
                    # マッチング対象外（チャプター時刻より前のアップロード）
                    continue

                if time_diff > tolerance_seconds:
                    # 許容範囲外（10分超）
                    continue

                # 時間差が最小のものを記録
                if time_diff < min_time_diff:
                    min_time_diff = time_diff
                    p1_result, p2_result = self.extract_battle_results(replay)
                    confidence = self._determine_confidence_level(time_diff)

                    best_match = {
                        "replay_id": replay_id,
                        "uploaded_at": uploaded_at,
                        "time_difference": time_diff,
                        "player1_character": p1_char,
                        "player1_result": p1_result,
                        "player2_character": p2_char,
                        "player2_result": p2_result,
                        "confidence": confidence,
                    }

            except Exception as e:
                logger.debug(f"Failed to process replay: {e}")
                continue

        # ステップ4: マッチング結果の検証
        if not best_match:
            logger.info(f"  ✗ {start_time}s: {chapter_title} - マッチなし")
            return {
                "matched": False,
                "confidence": "low",
                "player1_character": None,
                "player1_result": None,
                "player2_character": None,
                "player2_result": None,
                "replay_id": None,
                "uploaded_at": None,
                "time_difference_seconds": None,
                "details": f"No matching replay found within {tolerance_seconds}s",
            }

        logger.info(
            f"  ✓ {start_time}s: {chapter_title} - "
            f"replay_id={best_match['replay_id']}, "
            f"{best_match['player1_character']}({best_match['player1_result']}) vs "
            f"{best_match['player2_character']}({best_match['player2_result']}), "
            f"confidence={best_match['confidence']}, "
            f"time_diff={best_match['time_difference']:.1f}s"
        )

        return {
            "matched": True,
            "confidence": best_match["confidence"],
            "player1_character": best_match["player1_character"],
            "player1_result": best_match["player1_result"],
            "player2_character": best_match["player2_character"],
            "player2_result": best_match["player2_result"],
            "replay_id": best_match["replay_id"],
            "uploaded_at": best_match["uploaded_at"],
            "time_difference_seconds": int(best_match["time_difference"]),
            "details": f"Matched (time_diff={best_match['time_difference']:.1f}s)",
        }


async def main(
    video_id: str,
    player_id: str,
    chapters_file: str,
    output_format: str = "pretty",
    video_published_at: Optional[str] = None,
    tolerance_seconds: int = 300,
) -> None:
    """
    Battlelogマッピング検証

    Args:
        video_id: YouTube動画ID
        player_id: プレイヤーID
        chapters_file: チャプターJSONファイルのパス
        output_format: 出力フォーマット (pretty|json)
        video_published_at: 動画公開日時（未指定時は chapters_file のメタデータから取得）
        tolerance_seconds: 時刻差の許容範囲（秒）
    """
    logger.info("=" * 70)
    logger.info("SF6 Battlelog マッピング検証")
    logger.info("=" * 70)

    # 1. チャプターファイルを読み込み
    logger.info("\n[Step 1] チャプターファイルを読み込み...")
    chapters_path = Path(chapters_file)
    if not chapters_path.exists():
        logger.error(f"File not found: {chapters_file}")
        return

    try:
        with open(chapters_path) as f:
            chapters_data = json.load(f)
        chapters = chapters_data.get("chapters", [])
        logger.info(f"✓ {len(chapters)} 件のチャプターを読み込み")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse chapters file: {e}")
        return

    # 2. Battlelog APIから対戦ログを取得
    logger.info("\n[Step 2] Battlelog APIから対戦ログを取得...")

    try:
        # buildId取得
        site_client = BattlelogSiteClient()
        build_id = await site_client.get_build_id()
        logger.info(f"✓ buildId取得: {build_id[:20]}...")

        # 認証クッキー
        auth_cookie = os.environ.get("BUCKLER_ID_COOKIE")
        if not auth_cookie:
            logger.error("BUCKLER_ID_COOKIE environment variable not set")
            return

        # BattlelogCollectorで対戦ログ取得
        collector = BattlelogCollector(build_id=build_id, auth_cookie=auth_cookie)

        # 全ページの対戦ログを取得
        all_replays = []
        for page in range(1, 11):  # 最大10ページ
            logger.info(f"  ページ {page}/10 を取得中...")
            try:
                replays = await collector.get_replay_list(player_id=player_id, page=page)
                all_replays.extend(replays)
                logger.debug(f"    → {len(replays)} 件取得")
                if len(replays) == 0:
                    break
            except Exception as e:
                logger.debug(f"    Page {page} failed (this may be normal): {e}")
                break

        logger.info(f"✓ 合計 {len(all_replays)} 件の対戦ログを取得")

    except Exception as e:
        logger.error(f"Failed to fetch battlelog: {e}")
        import traceback

        traceback.print_exc()
        return

    # 3. 動画公開日時を決定
    if not video_published_at:
        try:
            # YouTube Data API から取得
            logger.info("  YouTube Data API から動画情報を取得中...")
            creds = get_oauth_credentials()
            youtube = build("youtube", "v3", credentials=creds)
            request = youtube.videos().list(part="snippet", id=video_id)
            response = request.execute()

            if response.get("items"):
                video_published_at = response["items"][0]["snippet"]["publishedAt"]
                logger.info("✓ YouTube API から publishedAt を取得")
            else:
                raise ValueError(f"Video not found: {video_id}")
        except Exception as e:
            logger.warning(f"⚠ YouTube API 取得失敗: {e}")
            # フォールバック: chapters_data から取得
            video_published_at = chapters_data.get("publishedAt")
            if not video_published_at:
                logger.error(
                    "YouTube API も chapters_data も利用できません。"
                    "--video-published-at で明示的に指定してください"
                )
                return

    logger.info(f"  動画公開日時: {video_published_at}")

    # 4. マッピング処理
    logger.info("\n[Step 3] チャプターをBattlelogにマッピング...")

    app_root = Path(__file__).parent.parent
    aliases_file = app_root / "config" / "character_aliases.json"

    normalizer = CharacterNormalizer(str(aliases_file))
    matcher = BattlelogMatcher(normalizer)

    # ステップ1: チャプターを時系列順（startTime昇順）にソート
    sorted_chapters = sorted(chapters, key=lambda c: c.get("startTime", 0))

    # ステップ2: リプレイを時系列順（uploaded_at昇順）にソート
    sorted_replays = sorted(all_replays, key=lambda r: r.get("uploaded_at", 0))

    # ステップ3: 既にマッチ済みのリプレイIDを追跡
    used_replay_ids = set()

    enriched_chapters = []
    for chapter in sorted_chapters:
        result = matcher.match_chapter_with_battlelog(
            chapter,
            sorted_replays,
            video_published_at,
            used_replay_ids,
            tolerance_seconds=tolerance_seconds,
        )

        # マッチ成功時、リプレイIDを記録（重複排除用）
        if result.get("matched") and result.get("replay_id"):
            used_replay_ids.add(result["replay_id"])

        enriched_chapter = {**chapter, **result}
        enriched_chapters.append(enriched_chapter)

    # 5. 結果を集計
    matched_count = sum(1 for c in enriched_chapters if c.get("matched"))
    high_confidence_count = sum(
        1 for c in enriched_chapters if c.get("matched") and c.get("confidence") == "high"
    )
    medium_confidence_count = sum(
        1 for c in enriched_chapters if c.get("matched") and c.get("confidence") == "medium"
    )

    logger.info("\n" + "=" * 70)
    logger.info("マッピング結果サマリー")
    logger.info("=" * 70)
    logger.info(f"総チャプター数: {len(enriched_chapters)}")
    logger.info(f"マッチ成功: {matched_count} ({matched_count*100//len(enriched_chapters) if enriched_chapters else 0}%)")
    logger.info(f"  高信頼度 (high):   {high_confidence_count}")
    logger.info(f"  中信頼度 (medium): {medium_confidence_count}")

    # 6. 詳細結果を出力
    logger.info("\n詳細結果:")

    if output_format == "json":
        output = {
            "videoId": video_id,
            "videoPublishedAt": video_published_at,
            "playerId": player_id,
            "summary": {
                "totalChapters": len(enriched_chapters),
                "matched": matched_count,
                "highConfidence": high_confidence_count,
            },
            "chapters": enriched_chapters,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:  # pretty
        for i, chapter in enumerate(enriched_chapters, 1):
            status = "✓" if chapter.get("matched") else "✗"
            confidence = chapter.get("confidence", "low")
            title = chapter.get("title", "Unknown")
            start_time = chapter.get("startTime", 0)

            if chapter.get("matched"):
                p1_char = chapter.get("player1_character", "?")
                p1_result = chapter.get("player1_result", "?").upper()
                p2_char = chapter.get("player2_character", "?")
                p2_result = chapter.get("player2_result", "?").upper()
                result_str = f" [{p1_char}({p1_result}) vs {p2_char}({p2_result})]"
            else:
                result_str = ""

            logger.info(
                f"{status} #{i:2d} {start_time:4d}s {title:25s} "
                f"({confidence:6s}){result_str}"
            )

            if chapter.get("matched"):
                logger.info(
                    f"      replay_id={chapter.get('replay_id')}, "
                    f"time_diff={chapter.get('time_difference_seconds')}s"
                )
            else:
                details = chapter.get("details", "")
                logger.info(f"      {details}")

    # 7. 結果ファイルに保存
    output_file = Path(chapters_file).parent / "battlelog_mapping_result.json"
    output = {
        "videoId": video_id,
        "videoPublishedAt": video_published_at,
        "playerId": player_id,
        "generatedAt": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "totalChapters": len(enriched_chapters),
            "matched": matched_count,
            "highConfidence": high_confidence_count,
            "toleranceSeconds": tolerance_seconds,
        },
        "chapters": enriched_chapters,
    }

    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"\n✓ 結果を保存: {output_file}")
    logger.info("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SF6 Battlelog マッピング検証スクリプト"
    )
    parser.add_argument("--video-id", required=True, help="YouTube動画ID")
    parser.add_argument("--player-id", required=True, help="プレイヤーID")
    parser.add_argument(
        "--chapters-file", required=True, help="チャプターJSONファイルのパス"
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "pretty"],
        default="pretty",
        help="出力フォーマット",
    )
    parser.add_argument(
        "--video-published-at",
        help="動画公開日時（ISO 8601形式、未指定時は推定）",
    )
    parser.add_argument(
        "--tolerance-seconds",
        type=int,
        default=600,
        help="時刻差の許容範囲（秒、デフォルト: 600秒=10分）",
    )

    args = parser.parse_args()

    asyncio.run(
        main(
            video_id=args.video_id,
            player_id=args.player_id,
            chapters_file=args.chapters_file,
            output_format=args.output_format,
            video_published_at=args.video_published_at,
            tolerance_seconds=args.tolerance_seconds,
        )
    )
