"""
AI图片审核工作流 - 配置文件
修改这里的参数来适配你的环境

安全说明：
- API_KEY 优先从环境变量读取（推荐，避免提交到 Git 泄露）
- 也可直接在这里填入真实 Key（但请勿把本文件提交到公开仓库）
"""

import os

# ============ API 配置 ============
# API 网关地址：优先取环境变量 API_BASE_URL，否则用通用占位符（请填入你自己的网关地址）
API_BASE_URL = os.environ.get("API_BASE_URL", "YOUR_API_GATEWAY_URL")
API_ENDPOINT = "/chat/completions"

# 读取 API Key：优先取环境变量 IMAGE_API_KEY，否则用占位符
API_KEY = os.environ.get("IMAGE_API_KEY", "YOUR_API_KEY_HERE")
MODEL_NAME = os.environ.get("IMAGE_MODEL", "doubao-seed-evolving")

# 请求 header
# User-Agent 从环境变量读取（默认占位符），避免暴露内部工具标识；网关如有校验请按需填写
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "User-Agent": os.environ.get("API_USER_AGENT", "Python/requests"),
}

# ============ 图片目录 ============
# 优先取环境变量 IMAGE_DIR，否则用当前目录下的 images 文件夹
IMAGE_DIR = os.environ.get("IMAGE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "images"))

# 支持的图片格式
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# ============ 输出目录 ============
# 默认输出到当前目录下的 output 文件夹（与代码同目录，方便迁移）
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
THUMBNAIL_DIR = OUTPUT_DIR + "/thumbnails"

# ============ 审核参数 ============
# 图片压缩：长边超过此值则缩放，减少base64体积和token消耗
IMAGE_MAX_SIZE = 1024

# 缩略图尺寸（用于HTML报告预览）
THUMBNAIL_SIZE = 200

# API并发数（控制QPS）
MAX_WORKERS = 3

# API超时（秒）
API_TIMEOUT = 60

# 最大重试次数
MAX_RETRIES = 3

# 重试间隔（秒）
RETRY_DELAY = 5

# ============ 评分标准 ============
# 各维度权重（总分 = 各维度加权平均）
WEIGHTS = {
    "quality_score": 0.35,
    "poem_match_score": 0.35,
    "style_confidence": 0.10,
    "compliance": 0.10,
    "text": 0.10,
}

# 分级标准（总分）
GRADE_THRESHOLDS = {
    "A": 8.0,   # >= 8.0
    "B": 6.0,   # >= 6.0
    "C": 0.0,   # < 6.0
}
# D级：不合规（一票否决，不论总分）

# ============ 文件名解析 ============
# 文件名格式：第3批 {诗名}_bg3_{变体号}.png / 第4批 {诗人}_{诗名}_bg4_{变体号}.png
FILE_PATTERN_SUFFIX = "_bg3_"
