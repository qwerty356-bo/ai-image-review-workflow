"""
AI图片审核工作流 - 核心审核逻辑
单张审核：读图 -> 压缩 -> 调API -> 解析5维度JSON(小数评分) -> 返回结构化结果
"""

import os
import io
import base64
import json
import re
import time
from datetime import datetime

import requests
from PIL import Image

import config
from poems_data import get_poem_keywords

# ============ Prompt 设计（v3 - 小数评分 + 5维度） ============

REVIEW_PROMPT_TEMPLATE = """你是一位专业的AI生成图片审核专家。请审核这张AI生成的古诗词背景图片，从以下5个维度进行评估。

## 图片信息
- 诗词名称：《{poem_name}》
- 意境关键词：{poem_keywords}
- 变体编号：第{variant}版

## 审核维度与评分标准

### 1. 画风分类（style）
从以下选项中选择最匹配的：国风水墨、工笔重彩、写实融合、扁平插画、二次元动漫、水彩、油画、像素风、其他
给出0.00-1.00的置信度。

### 2. 画面质量（quality_score，0.00-10.00分，精确到小数点后两位）
评分标准（严格执行，区分度是关键）：
- 9.50-10.00：顶级质量，笔触干净、色彩和谐、构图完美、无明显AI痕迹
- 8.50-9.49：优秀质量，轻微AI痕迹但不影响整体观感
- 7.50-8.49：良好质量，有一些AI痕迹（如结构错乱、光影不自然）
- 6.00-7.49：及格质量，明显AI痕迹，部分元素模糊或错乱
- 0.00-5.99：不及格，严重质量问题（主体崩坏、大面积模糊、色彩混乱）
评分必须有区分度，不要随意给整数分。每张图都应该给出精确到小数点后两位的分数。
在quality_detail中用一句话说明扣分原因，必须具体指出问题所在。

### 3. 内容合规性（compliant）
判断图片是否包含以下内容：暴力血腥、色情低俗、政治敏感、明显侵权元素。
- compliant: true表示合规，false表示不合规
- compliance_detail: 不合规时说明原因，合规则填空字符串

### 4. 诗词契合度（poem_match_score，0.00-10.00分，精确到小数点后两位）
根据诗词名称和意境关键词，判断图片内容与诗词意境的匹配程度：
- 9.00-10.00：高度契合，画面完美呈现诗词意境
- 7.00-8.99：较好契合，主要意境元素到位
- 5.00-6.99：部分契合，有相关元素但不够典型
- 0.00-4.99：不契合，画面与诗词意境无关
在poem_match_detail中说明匹配的具体元素或缺失的内容。

### 5. AI文字检测（has_text, text_correct）
检测图片中是否有文字（包括书法、印章、题字等）：
- has_text: true/false
- text_correct: 如果有文字，判断为"正确"（文字清晰可辨、无乱码）或"有乱码"（文字模糊、错字、无意义符号）。如果无文字则填null。

## 返回格式
严格返回以下JSON格式，不要添加任何其他文字：
{{
  "style": "画风类型",
  "style_confidence": 0.00,
  "quality_score": 0.00,
  "quality_detail": "一句话说明扣分原因",
  "compliant": true,
  "compliance_detail": "",
  "poem_match_score": 0.00,
  "poem_match_detail": "匹配说明",
  "has_text": false,
  "text_correct": null
}}"""


def parse_filename(filename):
    """从文件名解析诗名和变体号
    兼容两种命名格式：
      第3批: {诗名}_bg3_{变体号}.png
      第4批: {诗人}_{诗名}_bg4_{变体号}.png
    """
    name_no_ext = os.path.splitext(filename)[0]
    if config.FILE_PATTERN_SUFFIX in name_no_ext:
        parts = name_no_ext.rsplit(config.FILE_PATTERN_SUFFIX, 1)
        poem_name = parts[0]
        variant = int(parts[1]) if parts[1].isdigit() else 0
    else:
        poem_name = name_no_ext
        variant = 0
    # 去掉可能的"诗人_"前缀，便于匹配意境关键词表
    # 如 王维_山居秋暝 -> 山居秋暝（第3批诗名本身不含下划线，不受影响）
    # 先剥掉首尾的下划线（兼容 双下划线 等命名不规范的情况，如 秋词其一__bg3_1）
    poem_name = poem_name.strip("_")
    if "_" in poem_name:
        poem_name = poem_name.split("_", 1)[1]
    return poem_name, variant


def load_and_compress_image(file_path):
    """读取图片并压缩到合理大小"""
    img = Image.open(file_path)
    # 转RGB（如果是RGBA或P模式）
    if img.mode in ("RGBA", "P", "LA"):
        # 保持RGBA用于透明背景
        pass
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # 压缩到长边不超过IMAGE_MAX_SIZE
    max_size = config.IMAGE_MAX_SIZE
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    return img


def image_to_base64(img, fmt="PNG"):
    """将PIL图片转为base64编码"""
    buf = io.BytesIO()
    # PNG保留透明通道
    if img.mode == "RGBA":
        img.save(buf, format="PNG")
        mime = "image/png"
    elif fmt == "JPEG":
        img.save(buf, format="JPEG", quality=85)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG")
        mime = "image/png"
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:{mime};base64,{b64}"


def generate_thumbnail(file_path, output_path, size=None):
    """生成缩略图"""
    if size is None:
        size = config.THUMBNAIL_SIZE
    img = Image.open(file_path)
    img.thumbnail((size, size), Image.LANCZOS)
    img.save(output_path, format="PNG")


def call_api(image_b64_url, poem_name, variant):
    """调用API进行图片审核"""
    keywords = get_poem_keywords(poem_name)
    prompt = REVIEW_PROMPT_TEMPLATE.format(
        poem_name=poem_name,
        poem_keywords=keywords,
        variant=variant,
    )

    url = config.API_BASE_URL + config.API_ENDPOINT
    payload = {
        "model": config.MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_b64_url}},
                ],
            }
        ],
        "temperature": 0.3,  # 低温度保证输出稳定性
    }

    start_time = time.time()
    resp = requests.post(
        url,
        headers=config.HEADERS,
        json=payload,
        timeout=config.API_TIMEOUT,
    )
    latency_ms = int((time.time() - start_time) * 1000)

    if resp.status_code != 200:
        raise Exception(f"API返回 {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    tokens_used = data.get("usage", {}).get("total_tokens", 0)

    return content, tokens_used, latency_ms


def parse_review_result(content):
    """解析API返回的JSON结果，带容错"""
    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取JSON块
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # 尝试修复常见问题（多余的逗号、缺失的引号等）
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    raise Exception(f"JSON解析失败，原始内容: {content[:300]}")


def calculate_total_score(result):
    """计算加权总分（0.00-10.00）"""
    # 质量分（0-10）-> 权重0.35
    quality = float(result.get("quality_score", 0))
    # 诗词契合度（0-10）-> 权重0.35
    poem_match = float(result.get("poem_match_score", 0))
    # 画风置信度（0-1）* 10 -> 权重0.10
    style_conf = float(result.get("style_confidence", 0)) * 10
    # 合规（0或10）-> 权重0.10
    compliant = 10.0 if result.get("compliant", True) else 0.0
    # 文字（0或10）-> 权重0.10
    text_ok = 0.0
    if result.get("has_text") is False:
        text_ok = 10.0  # 无文字也算满分
    elif result.get("text_correct") == "正确":
        text_ok = 10.0
    elif result.get("text_correct") == "有乱码":
        text_ok = 3.0

    total = (
        quality * config.WEIGHTS["quality_score"]
        + poem_match * config.WEIGHTS["poem_match_score"]
        + style_conf * config.WEIGHTS["style_confidence"]
        + compliant * config.WEIGHTS["compliance"]
        + text_ok * config.WEIGHTS["text"]
    )

    return round(total, 2)


def determine_grade(result, total_score):
    """确定评级 A/B/C/D"""
    # D级：不合规一票否决
    if not result.get("compliant", True):
        return "D"
    # A/B/C 按总分
    if total_score >= config.GRADE_THRESHOLDS["A"]:
        return "A"
    elif total_score >= config.GRADE_THRESHOLDS["B"]:
        return "B"
    else:
        return "C"


def review_single_image(file_path, skip_thumbnail=False):
    """
    审核单张图片，返回完整的审核记录
    """
    filename = os.path.basename(file_path)
    poem_name, variant = parse_filename(filename)

    # 文件信息
    file_size_bytes = os.path.getsize(file_path)
    file_size_mb = round(file_size_bytes / (1024 * 1024), 2)

    # 读图压缩
    img = load_and_compress_image(file_path)
    image_b64_url = image_to_base64(img)

    # 调API
    content, tokens_used, latency_ms = call_api(image_b64_url, poem_name, variant)

    # 解析结果
    result = parse_review_result(content)

    # 计算总分和评级
    total_score = calculate_total_score(result)
    grade = determine_grade(result, total_score)

    # 生成缩略图
    thumbnail_path = None
    if not skip_thumbnail:
        os.makedirs(config.THUMBNAIL_DIR, exist_ok=True)
        thumb_name = os.path.splitext(filename)[0] + "_thumb.png"
        thumbnail_path = os.path.join(config.THUMBNAIL_DIR, thumb_name)
        generate_thumbnail(file_path, thumbnail_path)

    # 组装完整记录
    record = {
        "file_name": filename,
        "poem_name": poem_name,
        "variant": variant,
        "file_path": file_path,
        "file_size_mb": file_size_mb,
        # 审核结果
        "style": result.get("style", "未知"),
        "style_confidence": float(result.get("style_confidence", 0)),
        "quality_score": float(result.get("quality_score", 0)),
        "quality_detail": result.get("quality_detail", ""),
        "compliant": result.get("compliant", True),
        "compliance_detail": result.get("compliance_detail", ""),
        "poem_match_score": float(result.get("poem_match_score", 0)),
        "poem_match_detail": result.get("poem_match_detail", ""),
        "has_text": result.get("has_text", False),
        "text_correct": result.get("text_correct", None),
        # 综合
        "total_score": total_score,
        "grade": grade,
        # 元信息
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "model_name": config.MODEL_NAME,
        "tokens_used": tokens_used,
        "latency_ms": latency_ms,
        "review_status": "success",
    }

    return record


if __name__ == "__main__":
    # 单张测试
    test_file = os.path.join(config.IMAGE_DIR, "春晓_bg3_2.png")
    if os.path.exists(test_file):
        print(f"测试审核: {test_file}")
        record = review_single_image(test_file)
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print(f"测试文件不存在: {test_file}")
