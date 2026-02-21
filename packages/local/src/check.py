import cv2
import numpy as np

# テンプレート読み込み
template = cv2.imread("/Users/kajiwarayutaka/ProjectSand/sf6-chapter/packages/local/template/result_template.png")
win_template = cv2.imread("/Users/kajiwarayutaka/ProjectSand/sf6-chapter/packages/local/template/win_template.png")

# テスト動画でマッチング確認
cap = cv2.VideoCapture("/Users/kajiwarayutaka/ProjectSand/sf6-chapter/packages/local/download/20260214[dQwqkOG2SQo].mp4")
cap.set(cv2.CAP_PROP_POS_FRAMES, int(27840))  # 2秒目のフレーム
ret, frame = cap.read()
cap.release()

# エッジ抽出
def preprocess(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (17, 17), 0)
    edges = cv2.Canny(blurred, 50, 150)
    return edges

template_edges = preprocess(template)
win_edges = preprocess(win_template)
frame_edges = preprocess(frame)

# マッチング
result = cv2.matchTemplate(frame_edges, template_edges, cv2.TM_CCOEFF_NORMED)
win_result = cv2.matchTemplate(frame_edges, win_edges, cv2.TM_CCOEFF_NORMED)

print(f"RESULT screen match: {result.max():.3f}")
print(f"Win text match: {win_result.max():.3f}")

# 閾値チェック（0.3以上が理想）
if result.max() >= 0.3 and win_result.max() >= 0.3:
    print("✅ Templates are valid!")
else:
    print("❌ Adjust templates and retry")
