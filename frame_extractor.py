"""
AI视频审核工作流 - ffmpeg抽帧模块
职责：读视频时长 -> 均匀抽6-8帧 -> 转JPG存到临时目录 -> 返回帧路径列表

使用ffmpeg命令行工具，不依赖任何Python视频库
"""

import os
import json
import subprocess

import video_config


def get_video_duration(video_path):
    """
    用ffprobe获取视频时长（秒）
    返回浮点数，如 30.5 表示30.5秒
    """
    cmd = [
        video_config.FFPROBE_PATH,
        "-v", "quiet",  # 静默模式
        "-print_format", "json",
        "-show_format",
        video_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            # ffprobe可能不可用，尝试用ffmpeg获取
            return get_duration_via_ffmpeg(video_path)

        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        return duration
    except Exception:
        return get_duration_via_ffmpeg(video_path)


def get_duration_via_ffmpeg(video_path):
    """
    用ffmpeg获取视频时长（备用方案）
    ffmpeg输出中解析 Duration: 00:00:30.50
    """
    cmd = [
        video_config.FFMPEG_PATH,
        "-i", video_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        # ffmpeg对-i会返回非0退出码，但stderr里有信息
        output = result.stderr
        import re
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def extract_frames(video_path, output_dir=None, frame_count=None):
    """
    从视频中均匀抽取N帧，保存为JPG图片

    参数:
        video_path: 视频文件路径
        output_dir: 帧图片输出目录，None则用默认目录
        frame_count: 抽取帧数，None则用配置

    返回:
        list of dict: [{"path": 帧图片路径, "timestamp": 时间点秒, "index": 0}, ...]
        如果失败返回空列表
    """
    if frame_count is None:
        frame_count = video_config.FRAME_COUNT

    if output_dir is None:
        output_dir = video_config.FRAME_DIR

    os.makedirs(output_dir, exist_ok=True)

    # 获取视频时长
    duration = get_video_duration(video_path)
    if duration <= 0:
        # 无法获取时长，默认30秒
        duration = 30.0

    # 视频文件名（不含扩展名）
    video_name = os.path.splitext(os.path.basename(video_path))[0]

    # 计算每个帧的时间点（均匀分布）
    # 比如30秒抽6帧：第0、6、12、18、24、29秒（避开最末尾）
    timestamps = []
    if frame_count == 1:
        timestamps = [duration * 0.5]
    else:
        for i in range(frame_count):
            t = duration * i / (frame_count - 1) if frame_count > 1 else 0
            # 避开最末尾，最多取到 duration * 0.98
            t = min(t, duration * 0.98)
            timestamps.append(t)

    frames = []
    for i, ts in enumerate(timestamps):
        # 帧文件名：{视频名}_frame{i}_{timestamp}.jpg
        frame_filename = f"{video_name}_frame{i}_{ts:.1f}s.{video_config.FRAME_FORMAT}"
        frame_path = os.path.join(output_dir, frame_filename)

        # 如果帧已存在（重新运行时跳过重复抽取），直接用
        if os.path.exists(frame_path) and os.path.getsize(frame_path) > 0:
            frames.append({"path": frame_path, "timestamp": ts, "index": i})
            continue

        # 用ffmpeg抽帧
        # -ss 跳转到时间点, -i 输入文件, -frames:v 1 只取1帧
        cmd = [
            video_config.FFMPEG_PATH,
            "-y",  # 覆盖输出
            "-ss", f"{ts}",
            "-i", video_path,
            "-frames:v", "1",
            "-vf", f"scale='min({video_config.FRAME_MAX_SIZE},iw)':-2",  # 压缩长边
            "-q:v", "2",  # JPEG质量（2=高质量）
            frame_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0 and os.path.exists(frame_path):
                frames.append({"path": frame_path, "timestamp": ts, "index": i})
            # 失败的帧跳过，不中断
        except Exception:
            # 超时或出错，跳过这帧
            pass

    return frames


def cleanup_frames(frames):
    """
    清理帧图片文件（审核完成后可选调用）
    """
    for f in frames:
        path = f.get("path", "")
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def generate_frame_thumbnail(frame_path, output_path, size=None):
    """生成帧缩略图"""
    if size is None:
        size = video_config.THUMBNAIL_SIZE
    from PIL import Image
    img = Image.open(frame_path)
    img.thumbnail((size, size), Image.LANCZOS)
    # 保存为PNG
    out_path = os.path.splitext(output_path)[0] + ".png"
    img.save(out_path, format="PNG")
    return out_path


if __name__ == "__main__":
    # 测试：从命令行接收视频路径
    import sys

    if len(sys.argv) < 2:
        print("用法: python frame_extractor.py <视频路径>")
        print("示例: python frame_extractor.py /path/to/video.mp4")
        sys.exit(1)

    video_path = sys.argv[1]
    if not os.path.exists(video_path):
        print(f"文件不存在: {video_path}")
        sys.exit(1)

    duration = get_video_duration(video_path)
    print(f"视频时长: {duration:.1f}秒 ({duration/60:.1f}分钟)")

    print(f"开始抽帧（{video_config.FRAME_COUNT}帧）...")
    frames = extract_frames(video_path)

    print(f"\n抽取了 {len(frames)} 帧:")
    for f in frames:
        size = os.path.getsize(f["path"]) / 1024
        print(f"  帧{f['index']} @ {f['timestamp']:.1f}s -> {f['path']} ({size:.0f}KB)")
