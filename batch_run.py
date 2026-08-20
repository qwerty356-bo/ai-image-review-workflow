"""
AI图片审核工作流 - 批量执行入口
进度条 + 断点续跑 + 错误重试 + 增量保存 + 缩略图生成
"""

import os
import sys
import json
import time
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from review import review_single_image, generate_thumbnail

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 终端下打印特殊字符（如进度条方块）时崩溃
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============ 结果文件路径 ============
RESULTS_FILE = os.path.join(config.OUTPUT_DIR, "results.json")


def scan_images():
    """扫描图片目录，返回所有图片文件路径列表"""
    files = []
    for ext in config.IMAGE_EXTENSIONS:
        pattern = os.path.join(config.IMAGE_DIR, f"*{ext}")
        files.extend(glob.glob(pattern))
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
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def format_progress_bar(current, total, width=30):
    """生成进度条"""
    ratio = current / total if total > 0 else 0
    filled = int(width * ratio)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    percent = ratio * 100
    return f"\r{bar} {current}/{total} {percent:.1f}%"


def review_with_retry(file_path, max_retries=None):
    """带重试的审核"""
    if max_retries is None:
        max_retries = config.MAX_RETRIES

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            record = review_single_image(file_path)
            return record
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = config.RETRY_DELAY * attempt  # 指数退避
                print(f"\n  [重试 {attempt}/{max_retries}] {os.path.basename(file_path)} - {e} - 等待{wait}s...")
                time.sleep(wait)

    # 所有重试失败
    filename = os.path.basename(file_path)
    return {
        "file_name": filename,
        "file_path": file_path,
        "review_status": "error",
        "error_message": str(last_error),
        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def run_batch(image_files=None, max_workers=None):
    """
    批量审核
    image_files: 指定文件列表，None则扫描全部
    max_workers: 并发数
    """
    if max_workers is None:
        max_workers = config.MAX_WORKERS

    # 扫描图片
    if image_files is None:
        image_files = scan_images()

    total = len(image_files)
    if total == 0:
        print("未找到任何图片文件！")
        print(f"请检查 config.py 中 IMAGE_DIR 的配置: {config.IMAGE_DIR}")
        return []

    print("=" * 60)
    print("AI图片审核工作流 - 批量执行")
    print("=" * 60)
    print(f"图片目录:   {config.IMAGE_DIR}")
    print(f"图片总数:   {total} 张")
    print(f"使用模型:   {config.MODEL_NAME}")
    print(f"API端点:    {config.API_BASE_URL}{config.API_ENDPOINT}")
    print(f"并发数:     {max_workers}")
    print(f"输出目录:   {config.OUTPUT_DIR}")
    print(f"评分精度:   小数点后两位")
    print(f"审核维度:   画风/质量/合规/诗词契合度/AI文字")
    print("=" * 60)

    # 加载已有结果（断点续跑）
    existing_results = load_existing_results()
    done_files = {r["file_name"] for r in existing_results if r.get("review_status") == "success"}

    # 过滤掉已完成的
    todo_files = [f for f in image_files if os.path.basename(f) not in done_files]
    skipped = total - len(todo_files)

    if skipped > 0:
        print(f"\n断点续跑: 跳过已完成的 {skipped} 张，剩余 {len(todo_files)} 张待审核\n")
    else:
        print(f"\n全部 {total} 张需要审核\n")

    if not todo_files:
        print("所有图片已审核完成！")
        # 确保缩略图都生成了
        ensure_thumbnails(existing_results)
        return existing_results

    # 并发审核
    results = list(existing_results)  # 复制已有结果
    completed = skipped
    failed = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_file = {
            executor.submit(review_with_retry, f): f for f in todo_files
        }

        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            filename = os.path.basename(file_path)

            try:
                record = future.result()
            except Exception as e:
                record = {
                    "file_name": filename,
                    "file_path": file_path,
                    "review_status": "error",
                    "error_message": str(e),
                    "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }

            results.append(record)

            # 更新进度
            completed += 1
            if record.get("review_status") == "success":
                grade = record.get("grade", "?")
                score = record.get("total_score", 0)
                status_icon = "[OK] "
            else:
                grade = "ERR"
                score = 0
                status_icon = "[ERR]"
                failed += 1

            elapsed = time.time() - start_time
            speed = (completed - skipped) / elapsed if elapsed > 0 else 0
            eta = (total - completed) / speed if speed > 0 else 0

            sys.stdout.write(
                f"\r{status_icon} {format_progress_bar(completed, total)} "
                f"| {filename[:20]:<20s} | {grade} | {score:.2f} | "
                f"{speed:.1f}张/s | ETA:{eta:.0f}s"
            )
            sys.stdout.flush()

            # 每10张保存一次
            if (completed - skipped) % 10 == 0:
                save_results(results)

    # 最终保存
    save_results(results)

    print()  # 换行
    print("\n" + "=" * 60)
    print("审核完成!")
    print("=" * 60)
    print(f"总数: {total} | 成功: {total - failed} | 失败: {failed}")
    print(f"耗时: {time.time() - start_time:.1f}s")

    # 统计分级
    success_results = [r for r in results if r.get("review_status") == "success"]
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for r in success_results:
        g = r.get("grade", "C")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    print(f"\n分级统计:")
    for g in ["A", "B", "C", "D"]:
        count = grade_counts.get(g, 0)
        percent = count / max(len(success_results), 1) * 100
        bar = "\u2588" * int(percent / 2)
        print(f"  {g}级: {count:>3d} ({percent:5.1f}%) {bar}")

    # 统计平均分
    if success_results:
        avg_quality = sum(r.get("quality_score", 0) for r in success_results) / len(success_results)
        avg_poem = sum(r.get("poem_match_score", 0) for r in success_results) / len(success_results)
        avg_total = sum(r.get("total_score", 0) for r in success_results) / len(success_results)
        total_tokens = sum(r.get("tokens_used", 0) for r in success_results)
        print(f"\n平均分:")
        print(f"  质量: {avg_quality:.2f} | 契合度: {avg_poem:.2f} | 总分: {avg_total:.2f}")
        print(f"  总消耗Token: {total_tokens:,}")

    print(f"\n结果文件: {RESULTS_FILE}")
    print(f"缩略图目录: {config.THUMBNAIL_DIR}")
    print(f"\n下一步: 运行 python generate_report.py 生成HTML报告")
    print(f"        运行 python export_excel.py 导出Excel")

    return results


def ensure_thumbnails(results):
    """确保所有成功审核的图片都有缩略图"""
    os.makedirs(config.THUMBNAIL_DIR, exist_ok=True)
    for r in results:
        if r.get("review_status") != "success":
            continue
        filename = r.get("file_name", "")
        file_path = r.get("file_path", "")
        if not file_path or not os.path.exists(file_path):
            continue
        thumb_name = os.path.splitext(filename)[0] + "_thumb.png"
        thumb_path = os.path.join(config.THUMBNAIL_DIR, thumb_name)
        if not os.path.exists(thumb_path):
            try:
                generate_thumbnail(file_path, thumb_path)
            except Exception:
                pass


def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description="AI图片批量审核")
    parser.add_argument("--test", type=int, default=0, help="只跑前N张测试")
    parser.add_argument("--workers", type=int, default=None, help="并发数")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败的")
    args = parser.parse_args()

    # 获取所有图片
    all_files = scan_images()

    if args.test > 0:
        # 测试模式：只跑前N张
        test_files = all_files[:args.test]
        print(f"测试模式：只跑前 {args.test} 张")
        run_batch(image_files=test_files, max_workers=args.workers or 2)
    elif args.retry_failed:
        # 重试失败的模式
        existing = load_existing_results()
        failed_names = {r["file_name"] for r in existing if r.get("review_status") == "error"}
        retry_files = [f for f in all_files if os.path.basename(f) in failed_names]
        if retry_files:
            print(f"重试 {len(retry_files)} 张失败的图片")
            # 从results中移除失败的记录
            existing = [r for r in existing if r.get("review_status") == "success"]
            save_results(existing)
            run_batch(image_files=retry_files, max_workers=args.workers)
        else:
            print("没有失败的图片需要重试")
    else:
        # 全量模式
        run_batch(image_files=all_files, max_workers=args.workers)


if __name__ == "__main__":
    main()
