"""补生成帧缩略图（断点续跑时可能跳过了缩略图生成）"""
import os
import json
from review import generate_thumbnail
import video_config

frame_results_dir = os.path.join(video_config.OUTPUT_DIR, "frame_results")
thumb_dir = video_config.THUMBNAIL_DIR
os.makedirs(thumb_dir, exist_ok=True)

count = 0
for fname in os.listdir(frame_results_dir):
    if not fname.endswith("_frames.json"):
        continue
    with open(os.path.join(frame_results_dir, fname), "r", encoding="utf-8") as f:
        frames = json.load(f)
    for fr in frames:
        if fr.get("review_status") != "success":
            continue
        frame_path = fr.get("frame_path", "")
        if not frame_path or not os.path.exists(frame_path):
            continue
        basename = os.path.splitext(os.path.basename(frame_path))[0]
        thumb_path = os.path.join(thumb_dir, basename + "_thumb.png")
        if not os.path.exists(thumb_path):
            generate_thumbnail(frame_path, thumb_path)
            count += 1

print(f"生成 {count} 个缩略图到 {thumb_dir}")
