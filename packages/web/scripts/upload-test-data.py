#!/usr/bin/env python3
"""
ローカルR2にテストデータをアップロード

スキーマに準拠したサンプルParquetファイルを生成します。
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
import sys

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    print("❌ PyArrow がインストールされていません")
    print("")
    print("インストール方法:")
    print("  pip install pyarrow")
    print("  または")
    print("  uv pip install pyarrow")
    sys.exit(1)


def create_test_data():
    """テストデータを生成"""
    characters = ["Ryu", "Ken", "Chun-Li", "Guile", "JP", "Luke", "Juri", "Kimberly"]

    data = {
        "id": [],
        "videoId": [],
        "startTime": [],
        "endTime": [],
        "player1": [],
        "player2": [],
        "detectedAt": [],
        "confidence": [],
    }

    base_date = datetime(2026, 1, 1, 12, 0, 0)

    for i in range(20):
        match_id = f"test_{i:03d}"
        video_id = f"test_video_{(i // 5):02d}"
        start_time = i * 180
        end_time = start_time + 120

        player1_char = characters[i % len(characters)]
        player2_char = characters[(i + 1) % len(characters)]

        detected_at = base_date + timedelta(days=i)

        data["id"].append(match_id)
        data["videoId"].append(video_id)
        data["startTime"].append(start_time)
        data["endTime"].append(end_time)

        # 構造体として定義
        data["player1"].append({
            "character": player1_char,
            "characterRaw": player1_char,
            "side": "left",
        })
        data["player2"].append({
            "character": player2_char,
            "characterRaw": player2_char,
            "side": "right",
        })

        data["detectedAt"].append(detected_at.isoformat() + "Z")
        data["confidence"].append(0.95)

    return data


def main():
    """メイン処理"""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    r2_dir = project_root / ".wrangler" / "state" / "v3" / "r2" / "sf6-chapter-data-dev" / "index"

    print(f"📦 ローカルR2ディレクトリを作成: {r2_dir}")
    r2_dir.mkdir(parents=True, exist_ok=True)

    print("📝 テストデータを生成中...")
    data = create_test_data()

    # PyArrow Schemaを定義
    player_struct = pa.struct([
        ("character", pa.string()),
        ("characterRaw", pa.string()),
        ("side", pa.string()),
    ])

    schema = pa.schema([
        ("id", pa.string()),
        ("videoId", pa.string()),
        ("startTime", pa.int64()),
        ("endTime", pa.int64()),
        ("player1", player_struct),
        ("player2", player_struct),
        ("detectedAt", pa.string()),
        ("confidence", pa.float64()),
    ])

    # PyArrow Tableを作成
    table = pa.Table.from_pydict(data, schema=schema)

    # Parquetファイルに書き込み
    output_path = r2_dir / "matches.parquet"
    pq.write_table(table, output_path)

    print(f"✅ テストデータの生成完了: {output_path}")
    print(f"📊 レコード数: {len(data['id'])}")
    print("")
    print("次のコマンドでアプリケーションを起動:")
    print(f"  cd {project_root}")
    print("  pnpm dev")


if __name__ == "__main__":
    main()
