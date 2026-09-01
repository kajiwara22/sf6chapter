import obspython as obs
import subprocess
import os

# 実行したいスクリプトのフルパスと作業ディレクトリ
SCRIPT_PATH = r"C:\Users\yutaka\Documents\sf6chapter\packages\obs-title-updater\src\main.py"
CWD_PATH = r"C:\Users\yutaka\Documents\sf6chapter\packages\obs-title-updater"

def on_event(event):
    if event == obs.OBS_FRONTEND_EVENT_STREAMING_STOPPED:
        try:
            # 非同期実行
            # shell=True を入れると、Windows環境でコマンドが見つからないエラーを回避しやすくなります
            subprocess.Popen(["uv", "run", SCRIPT_PATH], cwd=CWD_PATH, shell=True)
            print(f"OBS配信停止: {SCRIPT_PATH} を実行しました")
        except Exception as e:
            print(f"OBS配信停止スクリプト実行エラー: {e}")

def script_load(settings):
    # OBS起動時/スクリプト読み込み時にイベントコールバックを登録
    obs.obs_frontend_add_event_callback(on_event)

def script_description():
    return "配信開始時に外部スクリプト（obs-title-updater）を実行します。"