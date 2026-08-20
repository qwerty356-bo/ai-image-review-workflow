"""
AI视频审核工作流 - 6维度单帧审核逻辑
在图片审核5维度基础上增加"史实准确性"维度

单帧审核：读帧图片 -> base64 -> 调API -> 解析6维度JSON -> 返回结构化结果
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

import video_config
from poems_data import get_poem_keywords

# ============ 6维度审核Prompt（v4 - 视频版，加史实准确性） ============

VIDEO_REVIEW_PROMPT_TEMPLATE = """你是一位专业的AI生成视频审核专家，正在审核一个AI生成的古诗词教学视频中的某一帧画面。
请从以下6个维度对这帧画面进行评估。

## 帧信息
- 诗词名称：《{poem_name}》
- 意境关键词：{poem_keywords}
- 本帧时间点：视频第 {timestamp:.1f} 秒
- 本帧编号：第 {frame_index}/{frame_count} 帧

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
在quality_detail中用一句话说明扣分原因，必须具体指出问题所在。

### 3. 内容合规性（compliant）
判断画面是否包含以下内容：暴力血腥、色情低俗、政治敏感、明显侵权元素。
- compliant: true表示合规，false表示不合规
- compliance_detail: 不合规时说明原因，合规则填空字符串

### 4. 诗词契合度（poem_match_score，0.00-10.00分，精确到小数点后两位）
根据诗词名称和意境关键词，判断画面内容与诗词意境的匹配程度：
- 9.00-10.00：高度契合，画面完美呈现诗词意境
- 7.00-8.99：较好契合，主要意境元素到位
- 5.00-6.99：部分契合，有相关元素但不够典型
- 0.00-4.99：不契合，画面与诗词意境无关
在poem_match_detail中说明匹配的具体元素或缺失的内容。

### 5. 史实准确性（history_score，0.00-10.00分，精确到小数点后两位）★视频特有维度★
判断画面中是否存在史实性错误（面向中小学教研场景，知识准确性要求极高）：
重点检查以下史实错误类型：
- 古代场景出现现代物品（电灯、手机、塑料、现代建筑等穿越元素）
- 服饰朝代穿越（如唐代场景出现明清服饰）
- 建筑风格不符（如汉代场景出现故宫式建筑）
- 器物道具错位（如石器时代出现铁器、宋代场景出现玉米/番茄等美洲作物）
- 军事装备错误（如战国场景出现火枪、唐代出现火药武器）
- 文化符号错误（如用错朝代的图腾、纹样、书法字体）

评分标准：
- 9.00-10.00：无任何史实错误，器物服饰建筑符合时代背景
- 7.00-8.99：有轻微时代混淆（如不同朝代风格混用，但不严重）
- 5.00-6.99：存在明显史实错误（至少1处穿越或错位）
- 0.00-4.99：严重史实错误（多处穿越，明显误导学生）
在history_detail中具体说明发现的问题，无问题则说明"未发现明显史实错误"。

### 6. AI文字检测（has_text, text_correct）
检测画面中是否有文字（包括字幕、书法、印章、题字等）：
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
  "history_score": 0.00,
  "history_detail": "史实准确性说明",
  "has_text": false,
  "text_correct": null
}}"""


def parse_video_filename(filename):
    """
    从视频文件名解析诗名
    视频文件名格式可能多样，尝试提取诗名
    """
    name_no_ext = os.path.splitext(filename)[0]
    # 如果有 _bg3_ 后缀，按图片审核的规则解析
    if "_bg3_" in name_no_ext:
        parts = name_no_ext.rsplit("_bg3_", 1)
        return parts[0], int(parts[1]) if parts[1].isdigit() else 0
    # 如果有 _v 数字 后缀
    match = re.match(r"^(.+?)_v(\d+)$", name_no_ext)
    if match:
        return match.group(1), int(match.group(2))
    # 默认：整个文件名作为诗名，变体0
    return name_no_ext, 0


def load_and_compress_frame(frame_path):
    """读取帧图片并压缩到合理大小"""
    img = Image.open(frame_path)
    if img.mode in ("RGBA", "P", "LA"):
        pass
    elif img.mode != "RGB":
        img = img.convert("RGB")

    max_size = video_config.FRAME_MAX_SIZE
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    return img


def frame_to_base64(img, fmt="JPEG"):
    """将帧图片转为base64编码"""
    buf = io.BytesIO()
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


def call_api_for_frame(image_b64_url, poem_name, timestamp, frame_index, frame_count):
    """调用API进行单帧审核"""
    keywords = get_poem_keywords(poem_name)
    prompt = VIDEO_REVIEW_PROMPT_TEMPLATE.format(
        poem_name=poem_name,
        poem_keywords=keywords,
        timestamp=timestamp,
        frame_index=frame_index,
        frame_count=frame_count,
    )

    url = video_config.API_BASE_URL + video_config.API_ENDPOINT
    payload = {
        "model": video_config.MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_b64_url}},
                ],
            }
        ],
        "temperature": 0.3,
    }

    start_time = time.time()
    resp = requests.post(
        url,
        headers=video_config.HEADERS,
        json=payload,
        timeout=video_config.API_TIMEOUT,
    )
    latency_ms = int((time.time() - start_time) * 1000)

    if resp.status_code != 200:
        raise Exception(f"API返回 {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    tokens_used = data.get("usage", {}).get("total_tokens", 0)

    return content, tokens_used, latency_ms


def parse_review_result(content):
    """解析API返回的JSON结果，带容错（复用图片审核的逻辑）"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    raise Exception(f"JSON解析失败，原始内容: {content[:300]}")


def calculate_frame_total_score(result):
    """计算单帧加权总分（6维度，0.00-10.00）"""
    quality = float(result.get("quality_score", 0))
    poem_match = float(result.get("poem_match_score", 0))
    history = float(result.get("history_score", 0))
    style_conf = float(result.get("style_confidence", 0)) * 10
    compliant = 10.0 if result.get("compliant", True) else 0.0

    text_ok = 0.0
    if result.get("has_text") is False:
        text_ok = 10.0
    elif result.get("text_correct") == "正确":
        text_ok = 10.0
    elif result.get("text_correct") == "有乱码":
        text_ok = 3.0

    w = video_config.WEIGHTS
    total = (
        quality * w["quality_score"]
        + poem_match * w["poem_match_score"]
        + history * w["history_score"]
        + style_conf * w["style_confidence"]
        + compliant * w["compliance"]
        + text_ok * w["text"]
    )

    return round(total, 2)


def review_single_frame(frame_info, poem_name, frame_count):
    """
    审核单帧，返回完整的帧审核记录

    参数:
        frame_info: {"path": 帧路径, "timestamp": 时间点, "index": 帧编号}
        poem_name: 诗名
        frame_count: 总帧数

    返回: 帧审核记录dict
    """
    frame_path = frame_info["path"]
    timestamp = frame_info["timestamp"]
    frame_index = frame_info["index"]

    # 读帧压缩
    img = load_and_compress_frame(frame_path)
    image_b64_url = frame_to_base64(img)

    # 调API
    content, tokens_used, latency_ms = call_api_for_frame(
        image_b64_url, poem_name, timestamp, frame_index, frame_count
    )

    # 解析结果
    result = parse_review_result(content)

    # 计算帧总分
    frame_total = calculate_frame_total_score(result)

    # 组装帧记录
    frame_record = {
        "frame_index": frame_index,
        "timestamp": round(timestamp, 1),
        "frame_path": frame_path,
        "style": result.get("style", "未知"),
        "style_confidence": float(result.get("style_confidence", 0)),
        "quality_score": float(result.get("quality_score", 0)),
        "quality_detail": result.get("quality_detail", ""),
        "compliant": result.get("compliant", True),
        "compliance_detail": result.get("compliance_detail", ""),
        "poem_match_score": float(result.get("poem_match_score", 0)),
        "poem_match_detail": result.get("poem_match_detail", ""),
        "history_score": float(result.get("history_score", 0)),
        "history_detail": result.get("history_detail", ""),
        "has_text": result.get("has_text", False),
        "text_correct": result.get("text_correct", None),
        "frame_total_score": frame_total,
        "tokens_used": tokens_used,
        "latency_ms": latency_ms,
        "review_status": "success",
    }

    return frame_record


if __name__ == "__main__":
    # 单帧测试
    test_frame = os.path.join(video_config.FRAME_DIR, "test_frame.jpg")
    if os.path.exists(test_frame):
        print(f"测试审核帧: {test_frame}")
        record = review_single_frame(
            {"path": test_frame, "timestamp": 0, "index": 0},
            "春晓",
            1,
        )
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print(f"测试帧不存在: {test_frame}")
        print("请先运行 frame_extractor.py 抽取帧")
