"""
AI视频审核工作流 - 帧结果聚合模块
职责：把一个视频的N帧审核结果聚合成一个视频级总分和评级

聚合策略：
- 合规性：任一帧不合规 -> 整体D（一票否决）
- 史实准确性：任一帧史实严重错误 -> 整体D（一票否决）
- 质量分：去掉最高分和最低分，其余取平均（防单帧异常拉偏）
- 诗词契合度：取最低分（内容跑题是全局问题）
- 史实分：取最低分
- 画风：取众数（出现最多的分类）
"""

from collections import Counter

import video_config


def aggregate_frames(frame_records):
    """
    把一个视频的多帧审核结果聚合成视频级结果

    参数:
        frame_records: 单帧审核记录列表

    返回:
        视频级聚合结果dict
    """
    if not frame_records:
        return {
            "review_status": "error",
            "error_message": "无帧审核结果",
        }

    success_frames = [f for f in frame_records if f.get("review_status") == "success"]
    if not success_frames:
        return {
            "review_status": "error",
            "error_message": "所有帧审核均失败",
        }

    # ---- 一票否决检查 ----
    # 合规性：任一帧不合规 -> D
    non_compliant_frames = [f for f in success_frames if not f.get("compliant", True)]
    if non_compliant_frames:
        grade = "D"
        veto_reason = "合规"
        veto_detail = non_compliant_frames[0].get("compliance_detail", "不合规")
    else:
        # 史实准确性：任一帧史实分 < 5 -> D（严重史实错误）
        history_fail_frames = [f for f in success_frames if float(f.get("history_score", 10)) < 5.0]
        if history_fail_frames:
            grade = "D"
            veto_reason = "史实"
            veto_detail = history_fail_frames[0].get("history_detail", "严重史实错误")
        else:
            grade = None  # 未定，后续按总分决定
            veto_reason = None
            veto_detail = ""

    # ---- 各维度聚合 ----
    # 质量分：去掉最高最低，取平均
    quality_scores = [f.get("quality_score", 0) for f in success_frames]
    if len(quality_scores) >= 3:
        quality_scores_sorted = sorted(quality_scores)
        quality_avg = sum(quality_scores_sorted[1:-1]) / len(quality_scores_sorted[1:-1])
    else:
        quality_avg = sum(quality_scores) / len(quality_scores) if quality_scores else 0

    # 诗词契合度：取最低分
    poem_scores = [f.get("poem_match_score", 0) for f in success_frames]
    poem_match_min = min(poem_scores) if poem_scores else 0

    # 史实分：取最低分
    history_scores = [f.get("history_score", 0) for f in success_frames]
    history_min = min(history_scores) if history_scores else 0

    # 画风：取众数
    styles = [f.get("style", "未知") for f in success_frames]
    style_counter = Counter(styles)
    style_majority = style_counter.most_common(1)[0][0] if style_counter else "未知"
    # 画风置信度：取众数对应的置信度，或平均
    style_confidences = [f.get("style_confidence", 0) for f in success_frames]
    style_conf_avg = sum(style_confidences) / len(style_confidences) if style_confidences else 0

    # 合规性：全部合规才算合规
    all_compliant = all(f.get("compliant", True) for f in success_frames)

    # 文字：如果有任何一帧有乱码，标记为有乱码
    has_any_text = any(f.get("has_text", False) for f in success_frames)
    has_garbled = any(f.get("text_correct") == "有乱码" for f in success_frames)
    if has_garbled:
        text_status = "有乱码"
    elif has_any_text:
        text_status = "正确"
    else:
        text_status = "无文字"

    # ---- 计算视频级总分 ----
    w = video_config.WEIGHTS
    text_ok = 0.0
    if not has_any_text:
        text_ok = 10.0
    elif text_status == "正确":
        text_ok = 10.0
    elif text_status == "有乱码":
        text_ok = 3.0

    total_score = (
        quality_avg * w["quality_score"]
        + poem_match_min * w["poem_match_score"]
        + history_min * w["history_score"]
        + style_conf_avg * 10 * w["style_confidence"]
        + (10.0 if all_compliant else 0.0) * w["compliance"]
        + text_ok * w["text"]
    )
    total_score = round(total_score, 2)

    # ---- 确定评级 ----
    if grade is None:
        if total_score >= video_config.GRADE_THRESHOLDS["A"]:
            grade = "A"
        elif total_score >= video_config.GRADE_THRESHOLDS["B"]:
            grade = "B"
        else:
            grade = "C"

    # ---- 汇总说明 ----
    quality_details = [f.get("quality_detail", "") for f in success_frames if f.get("quality_detail")]
    poem_details = [f.get("poem_match_detail", "") for f in success_frames if f.get("poem_match_detail")]
    history_details = [f.get("history_detail", "") for f in success_frames if f.get("history_detail")]

    # 统计
    total_tokens = sum(f.get("tokens_used", 0) for f in success_frames)
    total_latency = sum(f.get("latency_ms", 0) for f in success_frames)

    return {
        "total_score": total_score,
        "grade": grade,
        "veto_reason": veto_reason,
        "veto_detail": veto_detail,
        "quality_score": round(quality_avg, 2),
        "poem_match_score": round(poem_match_min, 2),
        "history_score": round(history_min, 2),
        "style": style_majority,
        "style_confidence": round(style_conf_avg, 2),
        "compliant": all_compliant,
        "text_status": text_status,
        "quality_summary": " | ".join(quality_details[:3]),
        "poem_match_summary": " | ".join(poem_details[:3]),
        "history_summary": " | ".join(history_details[:3]),
        "frame_count": len(success_frames),
        "total_tokens": total_tokens,
        "total_latency_ms": total_latency,
        "review_status": "success",
    }


if __name__ == "__main__":
    # 测试聚合逻辑
    test_frames = [
        {"quality_score": 8.5, "poem_match_score": 9.0, "history_score": 9.5,
         "style": "写实融合", "style_confidence": 0.9, "compliant": True,
         "has_text": False, "text_correct": None,
         "quality_detail": "轻微AI痕迹", "poem_match_detail": "意境到位",
         "history_detail": "未发现史实错误",
         "tokens_used": 1500, "latency_ms": 3000, "review_status": "success"},
        {"quality_score": 9.0, "poem_match_score": 8.5, "history_score": 8.0,
         "style": "写实融合", "style_confidence": 0.92, "compliant": True,
         "has_text": True, "text_correct": "正确",
         "quality_detail": "光影自然", "poem_match_detail": "有春晨元素",
         "history_detail": "服饰基本符合",
         "tokens_used": 1600, "latency_ms": 3500, "review_status": "success"},
        {"quality_score": 7.5, "poem_match_score": 8.0, "history_score": 7.0,
         "style": "国风水墨", "style_confidence": 0.85, "compliant": True,
         "has_text": False, "text_correct": None,
         "quality_detail": "远景模糊", "poem_match_detail": "部分契合",
         "history_detail": "建筑有宋式特征",
         "tokens_used": 1400, "latency_ms": 2800, "review_status": "success"},
    ]

    result = aggregate_frames(test_frames)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
