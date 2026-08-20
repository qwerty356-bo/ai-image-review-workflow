"""
AI视频审核工作流 - HTML报告生成
统计概览 + 6维度分布 + 帧序列缩略图条 + 明细表 + 史实错误清单
独立于图片审核报告，输出到 output/video/report.html
"""

import os
import json
from datetime import datetime

import video_config


def load_results():
    """加载视频审核结果"""
    results_file = os.path.join(video_config.OUTPUT_DIR, "results.json")
    if not os.path.exists(results_file):
        print(f"结果文件不存在: {results_file}")
        print("请先运行 python video_batch_run.py 完成视频审核")
        return []
    with open(results_file, "r", encoding="utf-8") as f:
        return json.load(f)


def get_frame_thumbnail_path(frame_record):
    """获取帧缩略图相对路径"""
    frame_path = frame_record.get("frame_path", "")
    if not frame_path:
        return ""
    basename = os.path.splitext(os.path.basename(frame_path))[0]
    return os.path.join("thumbnails", basename + "_thumb.png")


def calculate_stats(results):
    """计算统计数据"""
    success = [r for r in results if r.get("review_status") == "success"]
    errors = [r for r in results if r.get("review_status") == "error"]

    total = len(success)
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    style_counts = {}
    total_tokens = 0
    non_compliant = 0
    history_issues = 0
    veto_compliance = 0
    veto_history = 0

    for r in success:
        g = r.get("grade", "C")
        grade_counts[g] = grade_counts.get(g, 0) + 1

        style = r.get("style", "未知")
        style_counts[style] = style_counts.get(style, 0) + 1

        total_tokens += r.get("total_tokens", 0)

        if not r.get("compliant", True):
            non_compliant += 1
        if r.get("history_score", 10) < 7.0:
            history_issues += 1

        veto = r.get("veto_reason")
        if veto == "合规":
            veto_compliance += 1
        elif veto == "史实":
            veto_history += 1

    avg_quality = sum(r.get("quality_score", 0) for r in success) / total if total else 0
    avg_poem = sum(r.get("poem_match_score", 0) for r in success) / total if total else 0
    avg_history = sum(r.get("history_score", 0) for r in success) / total if total else 0
    avg_total = sum(r.get("total_score", 0) for r in success) / total if total else 0

    return {
        "total": len(results),
        "success": total,
        "errors": len(errors),
        "grade_counts": grade_counts,
        "style_counts": style_counts,
        "avg_quality": round(avg_quality, 2),
        "avg_poem": round(avg_poem, 2),
        "avg_history": round(avg_history, 2),
        "avg_total": round(avg_total, 2),
        "total_tokens": total_tokens,
        "non_compliant": non_compliant,
        "history_issues": history_issues,
        "veto_compliance": veto_compliance,
        "veto_history": veto_history,
        "compliant_rate": round((total - non_compliant) / total * 100, 1) if total else 0,
    }


def generate_html(results, stats):
    """生成视频审核HTML报告"""

    # 视频卡片HTML（含帧序列缩略图条）
    cards_html = ""
    for r in results:
        if r.get("review_status") == "error":
            continue

        grade = r.get("grade", "C")
        grade_color = {"A": "#4CAF50", "B": "#2196F3", "C": "#FF9800", "D": "#f44336"}.get(grade, "#999")
        total_score = r.get("total_score", 0)
        quality = r.get("quality_score", 0)
        poem_match = r.get("poem_match_score", 0)
        history = r.get("history_score", 0)
        style = r.get("style", "未知")
        compliant = "合规" if r.get("compliant", True) else "不合规"
        poem_name = r.get("poem_name", "")
        duration = r.get("duration_sec", 0)
        quality_detail = r.get("quality_summary", "")
        poem_detail = r.get("poem_match_summary", "")
        history_detail = r.get("history_summary", "")
        veto = r.get("veto_reason")
        veto_badge = ""
        if veto:
            veto_badge = f'<span class="veto-badge">一票否决:{veto}</span>'

        # 帧序列缩略图条
        frame_thumbs = ""
        frame_records = r.get("frame_records", [])
        for fr in frame_records:
            if fr.get("review_status") != "success":
                continue
            thumb_path = get_frame_thumbnail_path(fr)
            ts = fr.get("timestamp", 0)
            fr_quality = fr.get("quality_score", 0)
            fr_history = fr.get("history_score", 0)
            frame_thumbs += f"""
            <div class="frame-thumb" title="帧{fr.get('frame_index',0)} @ {ts:.1f}s 质量:{fr_quality:.1f} 史实:{fr_history:.1f}">
                <img src="{thumb_path}" alt="frame" loading="lazy"
                     onerror="this.src='data:image/svg+xml,<svg xmlns=\\"http://www.w3.org/2000/svg\\" width=\\"80\\" height=\\"50\\"><rect width=\\"100%\\" height=\\"100%\\" fill=\\"#eee\\"/><text x=\\"50%\\" y=\\"50%\\" text-anchor=\\"middle\\" dy=\\".3em\\" fill=\\"#999\\">无图</text></svg>'"/>
                <span class="frame-ts">{ts:.1f}s</span>
            </div>"""

        cards_html += f"""
        <div class="video-card grade-{grade}" data-grade="{grade}" data-style="{style}">
            <div class="video-card-header" style="border-left: 4px solid {grade_color}">
                <div class="video-title">{poem_name}</div>
                <div class="video-meta">
                    <span class="grade-badge" style="background:{grade_color}">{grade}</span>
                    <span class="score">{total_score:.2f}</span>
                    {veto_badge}
                </div>
            </div>
            <div class="video-scores">
                <span title="质量分">Q:{quality:.2f}</span>
                <span title="诗词契合度">P:{poem_match:.2f}</span>
                <span title="史实准确性">H:{history:.2f}</span>
                <span class="video-style">{style}</span>
            </div>
            <div class="frame-strip">
                {frame_thumbs}
            </div>
            <div class="video-detail">
                <div class="detail-row" title="{quality_detail}"><strong>质量:</strong> {quality_detail[:80]}</div>
                <div class="detail-row" title="{poem_detail}"><strong>契合:</strong> {poem_detail[:80]}</div>
                <div class="detail-row" title="{history_detail}"><strong>史实:</strong> {history_detail[:80]}</div>
            </div>
        </div>"""

    # 明细表
    table_rows = ""
    for r in results:
        if r.get("review_status") == "error":
            table_rows += f"""
            <tr class="error-row">
                <td>{r.get('file_name','')}</td>
                <td colspan="13" class="error-msg">错误: {r.get('error_message','')}</td>
            </tr>"""
            continue

        grade = r.get("grade", "C")
        grade_color = {"A": "#4CAF50", "B": "#2196F3", "C": "#FF9800", "D": "#f44336"}.get(grade, "#999")
        compliant = '<span class="tag-ok">合规</span>' if r.get("compliant", True) else '<span class="tag-err">不合规</span>'
        text_status = r.get("text_status", "-")
        veto = r.get("veto_reason", "")
        veto_text = f'<span class="tag-err">{veto}否决</span>' if veto else "-"

        table_rows += f"""
        <tr>
            <td>{r.get('poem_name','')}</td>
            <td>{r.get('duration_sec',0):.1f}s</td>
            <td>{r.get('style','')}</td>
            <td>{r.get('style_confidence',0):.2f}</td>
            <td><strong>{r.get('quality_score',0):.2f}</strong></td>
            <td>{r.get('poem_match_score',0):.2f}</td>
            <td>{r.get('history_score',0):.2f}</td>
            <td>{compliant}</td>
            <td>{text_status}</td>
            <td>{veto_text}</td>
            <td><strong style="color:{grade_color}">{r.get('total_score',0):.2f}</strong></td>
            <td><span class="grade-badge-sm" style="background:{grade_color}">{grade}</span></td>
            <td>{r.get('history_summary','')[:50]}</td>
        </tr>"""

    # 分级统计条
    grade_bars = ""
    for g in ["A", "B", "C", "D"]:
        count = stats["grade_counts"].get(g, 0)
        pct = count / stats["success"] * 100 if stats["success"] > 0 else 0
        color = {"A": "#4CAF50", "B": "#2196F3", "C": "#FF9800", "D": "#f44336"}.get(g, "#999")
        grade_bars += f"""
        <div class="stat-bar-row">
            <span class="stat-label grade-badge" style="background:{color}">{g}</span>
            <div class="stat-bar-bg"><div class="stat-bar-fill" style="width:{pct}%;background:{color}"></div></div>
            <span class="stat-count">{count}</span>
            <span class="stat-pct">({pct:.1f}%)</span>
        </div>"""

    # 史实问题清单
    history_issues_html = ""
    success_results = [r for r in results if r.get("review_status") == "success"]
    history_issues = [r for r in success_results if r.get("history_score", 10) < 7.0]
    if history_issues:
        history_issues_html = '<div class="section"><h2>⚠ 史实准确性问题清单</h2><table class="issue-table"><thead><tr><th>视频</th><th>史实分</th><th>问题说明</th></tr></thead><tbody>'
        for r in history_issues:
            history_issues_html += f"""
            <tr>
                <td>{r.get('poem_name','')}</td>
                <td><strong style="color:#f44336">{r.get('history_score',0):.2f}</strong></td>
                <td>{r.get('history_summary','')}</td>
            </tr>"""
        history_issues_html += '</tbody></table></div>'

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI视频审核报告 - {now}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "Microsoft YaHei", "Segoe UI", sans-serif; background: #f5f5f5; color: #333; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}

.header {{ background: linear-gradient(135deg, #e74c3c, #8e44ad); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
.header h1 {{ font-size: 24px; margin-bottom: 8px; }}
.header .subtitle {{ opacity: 0.9; font-size: 14px; }}
.header .meta {{ margin-top: 12px; display: flex; gap: 20px; font-size: 13px; opacity: 0.85; flex-wrap: wrap; }}

.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }}
.stat-card {{ background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
.stat-card .num {{ font-size: 28px; font-weight: bold; color: #333; }}
.stat-card .label {{ font-size: 12px; color: #888; margin-top: 4px; }}
.stat-card.green .num {{ color: #4CAF50; }}
.stat-card.blue .num {{ color: #2196F3; }}
.stat-card.orange .num {{ color: #FF9800; }}
.stat-card.red .num {{ color: #f44336; }}

.section {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.section h2 {{ font-size: 18px; margin-bottom: 16px; border-bottom: 2px solid #eee; padding-bottom: 8px; }}

.stat-bar-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.stat-label {{ min-width: 100px; font-size: 13px; }}
.stat-bar-bg {{ flex: 1; height: 24px; background: #f0f0f0; border-radius: 4px; overflow: hidden; }}
.stat-bar-fill {{ height: 100%; background: #8e44ad; border-radius: 4px; transition: width 0.3s; }}
.stat-count {{ min-width: 30px; text-align: right; font-weight: bold; font-size: 14px; }}
.stat-pct {{ min-width: 50px; text-align: right; font-size: 12px; color: #888; }}

.filters {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
.filter-btn {{ padding: 6px 16px; border: 1px solid #ddd; background: white; border-radius: 20px; cursor: pointer; font-size: 13px; transition: all 0.2s; }}
.filter-btn:hover {{ background: #f0f0f0; }}
.filter-btn.active {{ background: #8e44ad; color: white; border-color: #8e44ad; }}

/* 视频卡片 */
.video-card {{ background: white; border-radius: 8px; overflow: hidden; margin-bottom: 16px; border: 1px solid #e0e0e0; transition: box-shadow 0.2s; }}
.video-card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.12); }}
.video-card-header {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #fafafa; }}
.video-title {{ font-size: 16px; font-weight: bold; }}
.video-meta {{ display: flex; align-items: center; gap: 8px; }}
.video-scores {{ padding: 8px 16px; font-size: 13px; color: #666; display: flex; gap: 16px; align-items: center; }}
.video-style {{ color: #8e44ad; margin-left: auto; font-size: 12px; }}
.veto-badge {{ background: #f44336; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}

/* 帧序列缩略图条 */
.frame-strip {{ display: flex; gap: 6px; padding: 8px 16px; overflow-x: auto; background: #f9f9f9; }}
.frame-thumb {{ position: relative; flex-shrink: 0; width: 100px; }}
.frame-thumb img {{ width: 100px; height: 60px; object-fit: cover; border-radius: 4px; border: 1px solid #ddd; }}
.frame-ts {{ position: absolute; bottom: 2px; right: 4px; background: rgba(0,0,0,0.6); color: white; font-size: 10px; padding: 1px 4px; border-radius: 2px; }}

.video-detail {{ padding: 8px 16px 12px; font-size: 13px; }}
.detail-row {{ margin-bottom: 4px; color: #555; line-height: 1.5; }}
.detail-row strong {{ color: #333; }}

/* 表格 */
.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #f5f5f5; padding: 10px 8px; text-align: left; position: sticky; top: 0; border-bottom: 2px solid #ddd; }}
td {{ padding: 8px; border-bottom: 1px solid #eee; }}
tr:hover {{ background: #f9f9f9; }}
.error-row {{ background: #fff3e0; }}
.error-msg {{ color: #f44336; }}
.tag-ok {{ background: #4CAF50; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
.tag-err {{ background: #f44336; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
.grade-badge {{ display: inline-block; width: 20px; height: 20px; line-height: 20px; text-align: center; border-radius: 50%; color: white; font-size: 12px; font-weight: bold; }}
.grade-badge-sm {{ display: inline-block; width: 18px; height: 18px; line-height: 18px; text-align: center; border-radius: 50%; color: white; font-size: 11px; font-weight: bold; }}
.score {{ font-size: 16px; font-weight: bold; }}

/* 问题表格 */
.issue-table {{ width: 100%; border-collapse: collapse; }}
.issue-table th {{ background: #fff3e0; padding: 10px; text-align: left; }}
.issue-table td {{ padding: 10px; border-bottom: 1px solid #eee; }}

/* 导出按钮 */
.export-btns {{ display: flex; gap: 8px; margin-bottom: 16px; }}
.export-btn {{ padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; text-decoration: none; display: inline-block; }}
.export-btn.excel {{ background: #4CAF50; color: white; }}
.export-btn.csv {{ background: #FF9800; color: white; }}
.export-btn.json {{ background: #2196F3; color: white; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>AI视频审核报告</h1>
    <div class="subtitle">古诗词AI生成教学视频 - 6维度智能审核（含史实准确性）</div>
    <div class="meta">
        <span>审核时间: {now}</span>
        <span>模型: {video_config.MODEL_NAME}</span>
        <span>总数: {stats['total']} 个</span>
        <span>成功: {stats['success']} 个</span>
        <span>失败: {stats['errors']} 个</span>
    </div>
</div>

<div class="export-btns">
    <a class="export-btn excel" href="report.xlsx">导出 Excel</a>
    <a class="export-btn csv" href="report.csv">导出 CSV</a>
    <a class="export-btn json" href="results.json">导出 JSON</a>
</div>

<div class="stats-grid">
    <div class="stat-card green"><div class="num">{stats['success']}</div><div class="label">审核成功</div></div>
    <div class="stat-card red"><div class="num">{stats['errors']}</div><div class="label">审核失败</div></div>
    <div class="stat-card green"><div class="num">{stats['compliant_rate']}%</div><div class="label">合规率</div></div>
    <div class="stat-card blue"><div class="num">{stats['avg_quality']}</div><div class="label">平均质量分</div></div>
    <div class="stat-card blue"><div class="num">{stats['avg_poem']}</div><div class="label">平均契合度</div></div>
    <div class="stat-card blue"><div class="num">{stats['avg_history']}</div><div class="label">平均史实分</div></div>
    <div class="stat-card"><div class="num">{stats['avg_total']}</div><div class="label">平均总分</div></div>
    <div class="stat-card orange"><div class="num">{stats['history_issues']}</div><div class="label">史实问题数</div></div>
    <div class="stat-card red"><div class="num">{stats['veto_compliance']}</div><div class="label">合规否决</div></div>
    <div class="stat-card red"><div class="num">{stats['veto_history']}</div><div class="label">史实否决</div></div>
    <div class="stat-card"><div class="num">{stats['total_tokens']:,}</div><div class="label">总Token消耗</div></div>
</div>

<div class="section">
    <h2>分级统计</h2>
    {grade_bars}
    <div style="margin-top:12px;font-size:12px;color:#888">
        A级(优秀 ≥8.0) | B级(良好 ≥6.0) | C级(及格 <6.0) | D级(不合规或严重史实错误 一票否决)
    </div>
</div>

{history_issues_html}

<div class="section">
    <h2>视频预览（帧序列）</h2>
    <div class="filters">
        <button class="filter-btn active" onclick="filterCards('ALL')">全部 ({stats['success']})</button>
        <button class="filter-btn" onclick="filterCards('A')">A级 ({stats['grade_counts'].get('A',0)})</button>
        <button class="filter-btn" onclick="filterCards('B')">B级 ({stats['grade_counts'].get('B',0)})</button>
        <button class="filter-btn" onclick="filterCards('C')">C级 ({stats['grade_counts'].get('C',0)})</button>
        <button class="filter-btn" onclick="filterCards('D')">D级 ({stats['grade_counts'].get('D',0)})</button>
    </div>
    {cards_html}
</div>

<div class="section">
    <h2>审核明细</h2>
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>诗名</th>
                    <th>时长</th>
                    <th>画风</th>
                    <th>置信度</th>
                    <th>质量分</th>
                    <th>契合度</th>
                    <th>史实分</th>
                    <th>合规</th>
                    <th>文字</th>
                    <th>否决</th>
                    <th>总分</th>
                    <th>等级</th>
                    <th>史实说明</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
</div>

</div>

<script>
function filterCards(grade) {{
    const cards = document.querySelectorAll('.video-card');
    cards.forEach(c => {{
        if (grade === 'ALL' || c.dataset.grade === grade) {{
            c.style.display = '';
        }} else {{
            c.style.display = 'none';
        }}
    }});
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
}}
</script>
</body>
</html>"""

    return html


def main():
    """主入口"""
    results = load_results()
    if not results:
        return

    stats = calculate_stats(results)
    html = generate_html(results, stats)

    output_path = os.path.join(video_config.OUTPUT_DIR, "report.html")
    os.makedirs(video_config.OUTPUT_DIR, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML报告已生成: {output_path}")
    print(f"用浏览器打开即可查看")


if __name__ == "__main__":
    main()
