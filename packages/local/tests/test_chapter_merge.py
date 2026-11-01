"""過分割チャプターの統合（ADR-069）のユニットテスト"""

from main import _merge_single_round_chapters


def _chapter(start: int, title: str) -> dict:
    return {"startTime": start, "title": title, "matchId": f"test_{start}"}


class TestMergeSingleRoundChapters:
    """ROUND バナーが 1 つしか無いチャプターの統合"""

    def test_merges_oversplit_chapter_into_previous(self):
        """試合中のラウンド開始画面を誤検出したチャプターを前の試合に統合する

        F16OBc27nSc の 1314（2 バナー）/ 1402（1 バナー）/ 1456（3 バナー）を再現する。
        """
        chapters = [
            _chapter(1226, "JP VS JAMIE"),
            _chapter(1314, "JP VS JAMIE"),
            _chapter(1402, "JP VS JAMIE"),
            _chapter(1456, "JP VS JAMIE"),
        ]
        banners = [1226.25, 1276.0, 1314.5, 1352.5, 1406.75, 1456.75, 1510.75, 1544.5]

        kept, removed = _merge_single_round_chapters(chapters, banners)

        assert [chapter["startTime"] for chapter in kept] == [1226, 1314, 1456]
        assert [chapter["startTime"] for chapter in removed] == [1402]

    def test_keeps_chapter_when_neighbor_card_differs(self):
        """バナー数が 1 でも隣接チャプターが別カードなら統合しない（認識誤りと区別できない）"""
        chapters = [
            _chapter(100, "JP VS LUKE"),
            _chapter(200, "JP VS JAMIE"),
            _chapter(300, "ARJUN VS JP"),
        ]
        banners = [100.5, 150.0, 200.5, 300.5, 340.0, 370.0]

        kept, removed = _merge_single_round_chapters(chapters, banners)

        assert [chapter["startTime"] for chapter in kept] == [100, 200, 300]
        assert removed == []

    def test_merges_into_following_chapter(self):
        """先頭チャプターが 1 バナーで次のチャプターと同カードなら次へ統合する"""
        chapters = [
            _chapter(100, "JP VS LUKE"),
            _chapter(140, "JP VS LUKE"),
            _chapter(260, "ARJUN VS JP"),
        ]
        banners = [100.5, 140.5, 180.0, 260.5, 300.0, 340.0]

        kept, removed = _merge_single_round_chapters(chapters, banners)

        assert [chapter["startTime"] for chapter in kept] == [100, 260]
        assert [chapter["startTime"] for chapter in removed] == [140]

    def test_returns_input_when_banner_times_missing(self):
        """バナー時刻が未計測なら何もしない"""
        chapters = [_chapter(100, "JP VS LUKE"), _chapter(140, "JP VS LUKE")]

        kept, removed = _merge_single_round_chapters(chapters, [])

        assert kept == chapters
        assert removed == []

    def test_returns_input_for_single_chapter(self):
        """チャプターが 1 件なら統合しない"""
        chapters = [_chapter(100, "JP VS LUKE")]

        kept, removed = _merge_single_round_chapters(chapters, [100.5])

        assert kept == chapters
        assert removed == []
