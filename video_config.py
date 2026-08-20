"""
AI视频审核工作流 - 配置文件（独立于图片审核，互不影响）
修改这里的参数来适配你的视频审核环境

⚠️ 本文件只管视频审核，图片审核的 config.py 完全不受影响

安全说明：
- API_KEY 优先从环境变量读取（推荐），或直接填入真实 Key（勿提交公开仓库）
- ffmpeg 路径请改成你电脑上实际的安装位置
"""

import os

# ============ API 配置（与图片审核共用同一个API） ============
# API 网关地址：优先取环境变量 API_BASE_URL，否则用通用占位符（请填入你自己的网关地址）
API_BASE_URL = os.environ.get("API_BASE_URL", "YOUR_API_GATEWAY_URL")
API_ENDPOINT = "/chat/completions"

# 读取 API Key：优先取环境变量 VIDEO_API_KEY（若未设置则回退到 IMAGE_API_KEY），否则用占位符
API_KEY = os.environ.get("VIDEO_API_KEY") or os.environ.get("IMAGE_API_KEY", "YOUR_API_KEY_HERE")
MODEL_NAME = os.environ.get("VIDEO_MODEL", "doubao-seed-evolving")

# 请求 header
# User-Agent 从环境变量读取（默认占位符），避免暴露内部工具标识；网关如有校验请按需填写
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "User-Agent": os.environ.get("API_USER_AGENT", "Python/requests"),
}

# ============ 视频目录 ============
# ★★★ 改成你的视频文件夹路径 ★★★
# 优先取环境变量 VIDEO_DIR，否则用当前目录下的 videos 文件夹
VIDEO_DIR = os.environ.get("VIDEO_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos"))

# 支持的视频格式
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm"}

# ============ ffmpeg 路径 ============
# 建议填写完整路径，不依赖系统PATH（venv环境下PATH不一定包含ffmpeg）
# ★★★ 改成你电脑上 ffmpeg 的实际安装路径，或通过环境变量 FFMPEG_PATH 配置 ★★★
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = os.environ.get("FFPROBE_PATH", "ffprobe")

# ============ 抽帧参数 ============
# 每个视频均匀抽取的帧数（6-8帧覆盖几十秒短视频足够）
FRAME_COUNT = 6

# 抽出的帧图片长边最大像素（压缩，减少base64体积）
FRAME_MAX_SIZE = 1024

# 抽出的帧格式（JPG省体积，PNG无损但大）
FRAME_FORMAT = "jpg"

# ============ 输出目录（独立目录，不影响图片审核的output） ============
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "video"))
THUMBNAIL_DIR = OUTPUT_DIR + "/thumbnails"
FRAME_DIR = OUTPUT_DIR + "/frames"  # 抽出的帧临时存放

# ============ 审核参数 ============
# API并发数（视频审核每个视频要跑N帧，并发要低于图片审核）
MAX_WORKERS = 2

# 帧审核的API超时（秒）
API_TIMEOUT = 60

# 最大重试次数
MAX_RETRIES = 3

# 重试间隔（秒）
RETRY_DELAY = 5

# 缩略图尺寸（用于HTML报告预览）
THUMBNAIL_SIZE = 200

# ============ 6维度评分权重（总分 = 各维度加权平均） ============
# 比图片多了"史实准确性"维度
WEIGHTS = {
    "quality_score": 0.25,        # 画面质量
    "poem_match_score": 0.25,     # 诗词契合度
    "history_score": 0.20,        # 史实准确性（视频特有）
    "style_confidence": 0.10,     # 画风置信度
    "compliance": 0.10,           # 合规性
    "text": 0.10,                 # AI文字检测
}

# 分级标准（总分）
GRADE_THRESHOLDS = {
    "A": 8.0,   # >= 8.0
    "B": 6.0,   # >= 6.0
    "C": 0.0,   # < 6.0
}
# D级：不合规 或 史实错误（一票否决，不论总分）
