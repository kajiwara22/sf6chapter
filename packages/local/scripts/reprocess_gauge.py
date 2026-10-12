"""ゲージ計測だけを再実行して gauges.json / gauges_samples.csv を再生成する（検証用）"""
import json
import sys
from pathlib import Path

import cv2

from src.detection.config import load_detection_params
from src.detection.gauge import GaugeAnalyzer


def main() -> None:
    video_id = sys.argv[1]
    video_path = sys.argv[2]

    app_root = Path(__file__).parent
    params = load_detection_params(
        profile="production", config_path=str(app_root / "config" / "detection_params.json")
    )
    analyzer = GaugeAnalyzer(params.gauge_analysis, app_root=app_root)

    video_data = json.load(open(app_root / "intermediate" / video_id / "video_data.json"))
    matches = [(ch["matchId"], float(ch["startTime"])) for ch in video_data["chapters"]]

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        analyzer.feed(frame, frame_idx / fps)
        frame_idx += 1
    cap.release()
    video_end = frame_idx / fps

    result = analyzer.build(matches, video_end=video_end)
    result["videoId"] = video_id

    gauges_dir = app_root / "intermediate" / video_id / "gauges"
    gauges_dir.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(gauges_dir / "gauges.json", "w"), ensure_ascii=False, indent=2)
    analyzer.write_samples_csv(gauges_dir / "gauges_samples.csv")
    print("saved", gauges_dir / "gauges.json")


if __name__ == "__main__":
    main()
