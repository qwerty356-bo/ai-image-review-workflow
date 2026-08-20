"""
AI视频审核工作流 - 批量执行入口
遍历视频 -> 抽帧 -> 逐帧审核 -> 聚合 -> 增量保存

两级进度条 + 断点续跑 + 错误重试
输出到 output/video/ 目录，完全不影响图片审核
"""

import os
import sys
import json
import time
import glob

import video_config
from frame_extractor import extract_frames, get_video_duration
from video_review import review_single_frame
from aggregation import aggregate_frames
from review import generate_thumbnail  # 复用图片审核的缩略图函数

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 终端下打印特殊字符时崩溃
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============ 结果文件路径（独立于图片审核） ============
RESULTS_FILE = os.path.join(video_config.OUTPUT_DIR, "results.json")
FRAME_RESULTS_DIR = os.path.join(video_config.OUTPUT_DIR, "frame_results")


def scan_videos():
    """扫描视频目录，返回所有视频文件路径列表"""
    files = []
    for ext in video_config.VIDEO_EXTENSIONS:
        # 大小写都匹配
        pattern = os.path.join(video_config.VIDEO_DIR, f"*{ext}")
        files.extend(glob.glob(pattern))
        pattern_upper = os.path.join(video_config.VIDEO_DIR, f"*{ext.upper()}")
        files.extend(glob.glob(pattern_upper))
    # 去重
    files = list(set(files))
    files.sort()
    return files


def load_existing_results():
    """加载已有结果（断点续跑）"""
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_results(results):
    """增量保存结果"""
    os.makedirs(video_config.OUTPUT_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def save_frame_results(video_name, frame_records):
    """保存单个视频的帧级审核结果"""
    os.makedirs(FRAME_RESULTS_DIR, exist_ok=True)
    frame_file = os.path.join(FRAME_RESULTS_DIR, f"{video_name}_frames.json")
    with open(frame_file, "w", encoding="utf-8") as f:
        json.dump(frame_records, f, ensure_ascii=False, indent=2)


def load_frame_results(video_name):
    """加载已有的帧级结果（断点续跑）"""
    frame_file = os.path.join(FRAME_RESULTS_DIR, f"{video_name}_frames.json")
    if os.path.exists(frame_file):
        with open(frame_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def review_video_frames_with_retry(frame_info, poem_name, frame_count, max_retries=None):
    """带重试的单帧审核"""
    if max_retries is None:
        max_retries = video_config.MAX_RETRIES

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            record = review_single_frame(frame_info, poem_name, frame_count)
            return record
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = video_config.RETRY_DELAY * attempt
                print(f"\n  [重试 {attempt}/{max_retries}] 帧{frame_info['index']} - {e} - 等待{wait}s...")
                time.sleep(wait)

    return {
        "frame_index": frame_info["index"],
        "timestamp": frame_info["timestamp"],
        "frame_path": frame_info["path"],
        "review_status": "error",
        "error_message": str(last_error),
    }


def review_single_video(video_path):
    """
    完整审核单个视频：抽帧 -> 逐帧审核 -> 聚合
    返回视频级审核记录
    """
    filename = os.path.basename(video_path)
    video_name = os.path.splitext(filename)[0]
    poem_name, variant = parse_video_filename_safe(filename)

    file_size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 2)
    duration = get_video_duration(video_path)

    print(f"\n{'='*60}")
    print(f"审核视频: {filename}")
    print(f"时长: {duration:.1f}s | 大小: {file_size_mb}MB | 诗名: 《{poem_name}》")
    print(f"{'='*60}")

    # 检查是否有已保存的帧结果（断点续跑）
    existing_frames = load_frame_results(video_name)
    if existing_frames:
        # 过滤出成功的帧
        success_existing = [f for f in existing_frames if f.get("review_status") == "success"]
        if success_existing:
            print(f"断点续跑: 已有 {len(success_existing)} 帧结果，跳过审核")
            frame_records = existing_frames
            # 聚合
            video_result = aggregate_frames(success_existing)
            video_result.update({
                "file_name": filename,
                "video_name": video_name,
                "poem_name": poem_name,
                "variant": variant,
                "file_path": video_path,
                "file_size_mb": file_size_mb,
                "duration_sec": round(duration, 1),
                "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "model_name": video_config.MODEL_NAME,
            })
            return video_result

    # 抽帧
    print(f"正在抽取 {video_config.FRAME_COUNT} 帧...")
    frames = extract_frames(video_path)

    if not frames:
        return {
            "file_name": filename,
            "video_name": video_name,
            "poem_name": poem_name,
            "file_path": video_path,
            "review_status": "error",
            "error_message": "抽帧失败，未获取到任何帧",
            "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    print(f"成功抽取 {len(frames)} 帧")

    # 逐帧审核
    frame_records = []
    for i, frame_info in enumerate(frames):
        sys.stdout.write(f"\r  帧审核: [{i+1}/{len(frames)}] 帧{frame_info['index']} @ {frame_info['timestamp']:.1f}s...")
        sys.stdout.flush()

        record = review_video_frames_with_retry(
            frame_info, poem_name, len(frames)
        )
        frame_records.append(record)

        # 每帧审核完立即保存帧结果
        save_frame_results(video_name, frame_records)

    print()  # 换行

    # 聚合
    print("正在聚合帧结果...")
    success_frames = [f for f in frame_records if f.get("review_status") == "success"]
    video_result = aggregate_frames(success_frames)

    # 生成帧缩略图
    os.makedirs(video_config.THUMBNAIL_DIR, exist_ok=True)
    for f in frame_records:
        if f.get("review_status") != "success":
            continue
        frame_path = f.get("frame_path", "")
        if frame_path and os.path.exists(frame_path):
            thumb_name = os.path.splitext(os.path.basename(frame_path))[0] + "_thumb.png"
            thumb_path = os.path.join(video_config.THUMBNAIL_DIR, thumb_name)
            if not os.path.exists(thumb_path):
                try:
                    generate_thumbnail(frame_path, thumb_path)
                except Exception:
                    pass

    # 组装完整视频记录
    video_result.update({
        "file_name": filename,
        "video_name": video_name,
        "poem_name": poem_name,
        "variant": variant,
        "file_path": video_path,
        "file_size_mb": file_size_mb,
        "duration_sec": round(duration, 1),
        "frame_records": frame_records,  # 保留帧级详情
        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model_name": video_config.MODEL_NAME,
    })

    return video_result


def parse_video_filename_safe(filename):
    """安全解析视频文件名"""
    from video_review import parse_video_filename
    try:
        return parse_video_filename(filename)
    except Exception:
        return os.path.splitext(filename)[0], 0


def run_batch(video_files=None):
    """批量审核视频"""
    if video_files is None:
        video_files = scan_videos()

    total = len(video_files)
    if total == 0:
        print("未找到任何视频文件！")
        print(f"请检查 video_config.py 中 VIDEO_DIR 的配置: {video_config.VIDEO_DIR}")
        print(f"支持格式: {video_config.VIDEO_EXTENSIONS}")
        return []

    print("=" * 60)
    print("AI视频审核工作流 - 批量执行")
    print("=" * 60)
    print(f"视频目录:   {video_config.VIDEO_DIR}")
    print(f"视频总数:   {total} 个")
    print(f"使用模型:   {video_config.MODEL_NAME}")
    print(f"每视频抽帧: {video_config.FRAME_COUNT} 帧")
    print(f"审核维度:   画风/质量/合规/诗词契合度/史实准确性/AI文字")
    print(f"输出目录:   {video_config.OUTPUT_DIR}")
    print("=" * 60)

    # 加载已有结果
    existing_results = load_existing_results()
    done_files = {r["file_name"] for r in existing_results if r.get("review_status") == "success"}

    todo_files = [f for f in video_files if os.path.basename(f) not in done_files]
    skipped = total - len(todo_files)

    if skipped > 0:
        print(f"\n断点续跑: 跳过已完成的 {skipped} 个视频，剩余 {len(todo_files)} 个待审核")
    else:
        print(f"\n全部 {total} 个视频需要审核")

    if not todo_files:
        print("所有视频已审核完成！")
        return existing_results

    results = list(existing_results)
    completed = skipped
    start_time = time.time()

    for video_path in todo_files:
        filename = os.path.basename(video_path)
        completed += 1

        print(f"\n[{completed}/{total}] ", end="")

        try:
            record = review_single_video(video_path)
        except Exception as e:
            record = {
                "file_name": filename,
                "file_path": video_path,
                "review_status": "error",
                "error_message": str(e),
                "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }

        results.append(record)

        # 每个视频审核完立即保存
        save_results(results)

        # 打印本视频结果
        if record.get("review_status") == "success":
            grade = record.get("grade", "?")
            score = record.get("total_score", 0)
            quality = record.get("quality_score", 0)
            poem = record.get("poem_match_score", 0)
            history = record.get("history_score", 0)
            veto = record.get("veto_reason")
            status = f"{'[OK] '}" if not veto else f"[VETO:{veto}] "
            print(f"  {status}等级={grade} 总分={score:.2f} 质量={quality:.2f} 契合={poem:.2f} 史实={history:.2f}")
            if veto:
                print(f"        一票否决原因: {record.get('veto_detail', '')}")
        else:
            print(f"  [ERR] {record.get('error_message', '')[:200]}")

        # 进度估算
        elapsed = time.time() - start_time
        done_in_batch = completed - skipped
        if done_in_batch > 0 and elapsed > 0:
            avg_per_video = elapsed / done_in_batch
            eta = (total - completed) * avg_per_video
            print(f"        进度: {completed}/{total} ({completed/total*100:.0f}%) | 已用: {elapsed:.0f}s | 预计剩余: {eta:.0f}s")

    # 最终保存
    save_results(results)

    print("\n" + "=" * 60)
    print("视频审核完成!")
    print("=" * 60)

    success_results = [r for r in results if r.get("review_status") == "success"]
    error_results = [r for r in results if r.get("review_status") == "error"]

    print(f"总数: {len(results)} | 成功: {len(success_results)} | 失败: {len(error_results)}")

    if success_results:
        grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        for r in success_results:
            g = r.get("grade", "C")
            grade_counts[g] = grade_counts.get(g, 0) + 1

        print(f"\n分级统计:")
        for g in ["A", "B", "C", "D"]:
            count = grade_counts.get(g, 0)
            percent = count / len(success_results) * 100
            bar = "\u2588" * int(percent / 2)
            print(f"  {g}级: {count:>3d} ({percent:5.1f}%) {bar}")

        avg_quality = sum(r.get("quality_score", 0) for r in success_results) / len(success_results)
        avg_poem = sum(r.get("poem_match_score", 0) for r in success_results) / len(success_results)
        avg_history = sum(r.get("history_score", 0) for r in success_results) / len(success_results)
        avg_total = sum(r.get("total_score", 0) for r in success_results) / len(success_results)
        total_tokens = sum(r.get("total_tokens", 0) for r in success_results)

        print(f"\n平均分:")
        print(f"  质量: {avg_quality:.2f} | 契合度: {avg_poem:.2f} | 史实: {avg_history:.2f} | 总分: {avg_total:.2f}")
        print(f"  总消耗Token: {total_tokens:,}")

        # 史实问题清单
        history_issues = [r for r in success_results if r.get("history_score", 10) < 7.0]
        if history_issues:
            print(f"\n[!] 史实准确性问题清单 ({len(history_issues)}个):")
            for r in history_issues:
                print(f"  - {r.get('file_name','')}: {r.get('history_summary','')[:100]}")

    if error_results:
        print(f"\n[X] 审核失败 ({len(error_results)}个):")
        for r in error_results:
            print(f"  - {r.get('file_name','')}: {r.get('error_message','')[:100]}")

    print(f"\n结果文件: {RESULTS_FILE}")
    print(f"帧级结果: {FRAME_RESULTS_DIR}/")
    print(f"\n下一步: 运行 python generate_video_report.py 生成HTML报告")
    print(f"        运行 python export_video_excel.py 导出Excel")

    return results


def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description="AI视频批量审核")
    parser.add_argument("--test", type=int, default=0, help="只跑前N个视频测试")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败的")
    args = parser.parse_args()

    all_files = scan_videos()

    if args.test > 0:
        test_files = all_files[:args.test]
        print(f"测试模式：只跑前 {args.test} 个视频")
        run_batch(video_files=test_files)
    elif args.retry_failed:
        existing = load_existing_results()
        failed_names = {r["file_name"] for r in existing if r.get("review_status") == "error"}
        retry_files = [f for f in all_files if os.path.basename(f) in failed_names]
        if retry_files:
            print(f"重试 {len(retry_files)} 个失败的视频")
            existing = [r for r in existing if r.get("review_status") == "success"]
            save_results(existing)
            # 同时清理帧结果
            for f in retry_files:
                vn = os.path.splitext(os.path.basename(f))[0]
                ff = os.path.join(FRAME_RESULTS_DIR, f"{vn}_frames.json")
                if os.path.exists(ff):
                    os.remove(ff)
            run_batch(video_files=retry_files)
        else:
            print("没有失败的视频需要重试")
    else:
        run_batch(video_files=all_files)


if __name__ == "__main__":
    main()
