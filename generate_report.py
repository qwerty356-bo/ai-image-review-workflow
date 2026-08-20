"""
AI图片审核工作流 - HTML报告生成
统计概览 + 图表 + 缩略图网格(按级别筛选) + 明细表 + 诗词契合度展示
"""

import os
import json
import base64
import urllib.parse
from datetime import datetime

import config


def load_results():
    """加载审核结果"""
    results_file = os.path.join(config.OUTPUT_DIR, "results.json")
    if not os.path.exists(results_file):
        print(f"结果文件不存在: {results_file}")
        print("请先运行 python batch_run.py 完成审核")
        return []
    with open(results_file, "r", encoding="utf-8") as f:
        return json.load(f)


def get_thumbnail_path(record):
    """获取缩略图相对路径
    强制使用正斜杠：浏览器在 file:// 下不识别反斜杠
    """
    filename = record.get("file_name", "")
    thumb_name = os.path.splitext(filename)[0] + "_thumb.png"
    return "thumbnails/" + thumb_name


def get_thumbnail_data_uri(record):
    """把缩略图内联为 base64 data URI，彻底避免 file:// 下中文路径加载失败的问题"""
    filename = record.get("file_name", "")
    thumb_name = os.path.splitext(filename)[0] + "_thumb.png"
    thumb_path = os.path.join(config.THUMBNAIL_DIR, thumb_name)
    try:
        with open(thumb_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


def get_file_url(record):
    """把原图绝对路径转成 file:// URL，并对中文做 URL 编码（file:// 下裸中文路径常加载失败）"""
    abs_path = record.get("file_path", "").replace("\\", "/")
    if not abs_path:
        return ""
    encoded = urllib.parse.quote(abs_path, safe="/")
    return "file:///" + encoded


def calculate_stats(results):
    """计算统计数据"""
    success = [r for r in results if r.get("review_status") == "success"]
    errors = [r for r in results if r.get("review_status") == "error"]

    total = len(success)
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    style_counts = {}
    avg_quality = 0
    avg_poem = 0
    avg_total = 0
    total_tokens = 0
    non_compliant = 0
    has_text_count = 0
    text_garbled_count = 0

    for r in success:
        g = r.get("grade", "C")
        grade_counts[g] = grade_counts.get(g, 0) + 1

        style = r.get("style", "未知")
        style_counts[style] = style_counts.get(style, 0) + 1

        avg_quality += r.get("quality_score", 0)
        avg_poem += r.get("poem_match_score", 0)
        avg_total += r.get("total_score", 0)
        total_tokens += r.get("tokens_used", 0)

        if not r.get("compliant", True):
            non_compliant += 1
        if r.get("has_text"):
            has_text_count += 1
            if r.get("text_correct") == "有乱码":
                text_garbled_count += 1

    if total > 0:
        avg_quality /= total
        avg_poem /= total
        avg_total /= total

    return {
        "total": len(results),
        "success": total,
        "errors": len(errors),
        "grade_counts": grade_counts,
        "style_counts": style_counts,
        "avg_quality": round(avg_quality, 2),
        "avg_poem": round(avg_poem, 2),
        "avg_total": round(avg_total, 2),
        "total_tokens": total_tokens,
        "non_compliant": non_compliant,
        "has_text_count": has_text_count,
        "text_garbled_count": text_garbled_count,
        "compliant_rate": round((total - non_compliant) / total * 100, 1) if total > 0 else 0,
    }


def generate_html(results, stats):
    """生成完整HTML报告"""

    # 缩略图卡片HTML
    cards_html = ""
    for r in results:
        if r.get("review_status") == "error":
            continue

        grade = r.get("grade", "C")
        grade_color = {"A": "#4CAF50", "B": "#2196F3", "C": "#FF9800", "D": "#f44336"}.get(grade, "#999")
        thumb_path = get_thumbnail_path(r)
        thumb_data_uri = get_thumbnail_data_uri(r)
        file_url = get_file_url(r)
        total_score = r.get("total_score", 0)
        quality = r.get("quality_score", 0)
        poem_match = r.get("poem_match_score", 0)
        style = r.get("style", "未知")
        compliant = "合规" if r.get("compliant", True) else "不合规"
        poem_name = r.get("poem_name", "")
        variant = r.get("variant", 0)
        quality_detail = r.get("quality_detail", "")
        poem_detail = r.get("poem_match_detail", "")
        has_text = r.get("has_text", False)
        text_status = ""
        if has_text:
            tc = r.get("text_correct", "")
            text_status = f"文字: {tc}" if tc else "文字: 有"
        else:
            text_status = "无文字"

        cards_html += f"""
        <div class="card grade-{grade}" data-grade="{grade}" data-style="{style}" data-score="{total_score}"
             onclick="openModal('{file_url}', '{r.get('file_name','')}')">
            <div class="card-img" style="border-color: {grade_color}">
                <img src="{thumb_data_uri}" alt="{r.get('file_name','')}" loading="lazy"
                     onerror="this.src='data:image/svg+xml,<svg xmlns=\\"http://www.w3.org/2000/svg\\" width=\\"200\\" height=\\"150\\"><rect width=\\"100%\\" height=\\"100%\\" fill=\\"#eee\\"/><text x=\\"50%\\" y=\\"50%\\" text-anchor=\\"middle\\" dy=\\".3em\\" fill=\\"#999\\">无缩略图</text></svg>'"/>
            </div>
            <div class="card-info">
                <div class="card-title">{poem_name}</div>
                <div class="card-meta">
                    <span class="grade-badge" style="background:{grade_color}">{grade}</span>
                    <span class="score">{total_score:.2f}</span>
                </div>
                <div class="card-scores">
                    <span title="质量分">Q:{quality:.2f}</span>
                    <span title="诗词契合度">P:{poem_match:.2f}</span>
                </div>
                <div class="card-style">{style}</div>
                <div class="card-detail" title="点击展开/收起" onclick="event.stopPropagation(); this.classList.toggle('expanded');">{quality_detail}</div>
            </div>
        </div>"""

    # 明细表HTML
    table_rows = ""
    for r in results:
        if r.get("review_status") == "error":
            table_rows += f"""
            <tr class="error-row">
                <td>{r.get('file_name','')}</td>
                <td colspan="10" class="error-msg">错误: {r.get('error_message','')}</td>
            </tr>"""
            continue

        grade = r.get("grade", "C")
        grade_color = {"A": "#4CAF50", "B": "#2196F3", "C": "#FF9800", "D": "#f44336"}.get(grade, "#999")
        compliant = '<span class="tag-ok">合规</span>' if r.get("compliant", True) else '<span class="tag-err">不合规</span>'
        text_status = "-"
        if r.get("has_text"):
            tc = r.get("text_correct", "")
            if tc == "正确":
                text_status = '<span class="tag-ok">正确</span>'
            elif tc == "有乱码":
                text_status = '<span class="tag-err">有乱码</span>'
            else:
                text_status = "有文字"
        else:
            text_status = "无文字"

        table_rows += f"""
        <tr>
            <td>{r.get('poem_name','')}</td>
            <td>v{r.get('variant',0)}</td>
            <td>{r.get('style','')}</td>
            <td>{r.get('style_confidence',0):.2f}</td>
            <td><strong>{r.get('quality_score',0):.2f}</strong></td>
            <td>{r.get('poem_match_score',0):.2f}</td>
            <td>{compliant}</td>
            <td>{text_status}</td>
            <td><strong style="color:{grade_color}">{r.get('total_score',0):.2f}</strong></td>
            <td><span class="grade-badge-sm" style="background:{grade_color}">{grade}</span></td>
            <td>{r.get('quality_detail','')}</td>
            <td>{r.get('poem_match_detail','')}</td>
        </tr>"""

    # 错误列表
    error_list_html = ""
    error_results = [r for r in results if r.get("review_status") == "error"]
    if error_results:
        error_list_html = '<div class="error-section"><h3>异常图片清单</h3><ul>'
        for r in error_results:
            error_list_html += f'<li><strong>{r.get("file_name","")}</strong>: {r.get("error_message","")}</li>'
        error_list_html += '</ul></div>'

    # 画风分布
    style_bars = ""
    max_style_count = max(stats["style_counts"].values()) if stats["style_counts"] else 1
    for style, count in sorted(stats["style_counts"].items(), key=lambda x: -x[1]):
        pct = count / stats["success"] * 100 if stats["success"] > 0 else 0
        bar_width = count / max_style_count * 100
        style_bars += f"""
        <div class="stat-bar-row">
            <span class="stat-label">{style}</span>
            <div class="stat-bar-bg"><div class="stat-bar-fill" style="width:{bar_width}%"></div></div>
            <span class="stat-count">{count}</span>
            <span class="stat-pct">({pct:.1f}%)</span>
        </div>"""

    # 分级统计
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

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI图片审核报告 - {now}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "Microsoft YaHei", "Segoe UI", sans-serif; background: #f5f5f5; color: #333; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}

/* Header */
.header {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
.header h1 {{ font-size: 24px; margin-bottom: 8px; }}
.header .subtitle {{ opacity: 0.9; font-size: 14px; }}
.header .meta {{ margin-top: 12px; display: flex; gap: 20px; font-size: 13px; opacity: 0.85; }}

/* Stats overview */
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }}
.stat-card {{ background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
.stat-card .num {{ font-size: 28px; font-weight: bold; color: #333; }}
.stat-card .label {{ font-size: 12px; color: #888; margin-top: 4px; }}
.stat-card.green .num {{ color: #4CAF50; }}
.stat-card.blue .num {{ color: #2196F3; }}
.stat-card.orange .num {{ color: #FF9800; }}
.stat-card.red .num {{ color: #f44336; }}

/* Section */
.section {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.section h2 {{ font-size: 18px; margin-bottom: 16px; border-bottom: 2px solid #eee; padding-bottom: 8px; }}

/* Stat bars */
.stat-bar-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.stat-label {{ min-width: 100px; font-size: 13px; }}
.stat-bar-bg {{ flex: 1; height: 24px; background: #f0f0f0; border-radius: 4px; overflow: hidden; }}
.stat-bar-fill {{ height: 100%; background: #667eea; border-radius: 4px; transition: width 0.3s; }}
.stat-count {{ min-width: 30px; text-align: right; font-weight: bold; font-size: 14px; }}
.stat-pct {{ min-width: 50px; text-align: right; font-size: 12px; color: #888; }}

/* Filter buttons */
.filters {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
.filter-btn {{ padding: 6px 16px; border: 1px solid #ddd; background: white; border-radius: 20px; cursor: pointer; font-size: 13px; transition: all 0.2s; }}
.filter-btn:hover {{ background: #f0f0f0; }}
.filter-btn.active {{ background: #667eea; color: white; border-color: #667eea; }}

/* Card grid */
.card-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }}
.card {{ background: white; border-radius: 8px; overflow: hidden; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; border: 2px solid transparent; }}
.card:hover {{ transform: translateY(-4px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
.card-img {{ width: 100%; height: 140px; overflow: hidden; border-top: 4px solid; }}
.card-img img {{ width: 100%; height: 100%; object-fit: cover; }}
.card-info {{ padding: 8px; }}
.card-title {{ font-size: 14px; font-weight: bold; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.card-meta {{ display: flex; align-items: center; gap: 6px; margin: 4px 0; }}
.card-scores {{ font-size: 11px; color: #888; display: flex; gap: 8px; }}
.card-style {{ font-size: 11px; color: #667eea; margin: 2px 0; }}
.card-detail {{ font-size: 11px; color: #999; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; word-break: break-word; cursor: pointer; }}
.card-detail.expanded {{ display: block; -webkit-line-clamp: unset; overflow: visible; }}
.grade-badge {{ display: inline-block; width: 20px; height: 20px; line-height: 20px; text-align: center; border-radius: 50%; color: white; font-size: 12px; font-weight: bold; }}
.score {{ font-size: 16px; font-weight: bold; }}

/* Table */
.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #f5f5f5; padding: 10px 8px; text-align: left; position: sticky; top: 0; border-bottom: 2px solid #ddd; }}
td {{ padding: 8px; border-bottom: 1px solid #eee; }}
tr:hover {{ background: #f9f9f9; }}
.error-row {{ background: #fff3e0; }}
.error-msg {{ color: #f44336; }}
.tag-ok {{ background: #4CAF50; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
.tag-err {{ background: #f44336; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
.grade-badge-sm {{ display: inline-block; width: 18px; height: 18px; line-height: 18px; text-align: center; border-radius: 50%; color: white; font-size: 11px; font-weight: bold; }}

/* Error section */
.error-section {{ margin-top: 20px; }}
.error-section ul {{ list-style: none; }}
.error-section li {{ padding: 8px; background: #fff3e0; border-radius: 4px; margin-bottom: 4px; font-size: 13px; }}

/* Modal */
.modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 1000; justify-content: center; align-items: center; }}
.modal-overlay.active {{ display: flex; }}
.modal-img {{ max-width: 90%; max-height: 90%; border-radius: 8px; }}
.modal-close {{ position: fixed; top: 20px; right: 30px; color: white; font-size: 36px; cursor: pointer; }}
.modal-title {{ position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); color: white; font-size: 14px; }}

/* Export buttons */
.export-btns {{ display: flex; gap: 8px; margin-bottom: 16px; }}
.export-btn {{ padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; text-decoration: none; display: inline-block; }}
.export-btn.excel {{ background: #4CAF50; color: white; }}
.export-btn.csv {{ background: #FF9800; color: white; }}
.export-btn.json {{ background: #2196F3; color: white; }}
</style>
</head>
<body>
<div class="container">

<!-- Header -->
<div class="header">
    <h1>AI图片审核报告</h1>
    <div class="subtitle">古诗词AI生成背景图 - 多维度智能审核</div>
    <div class="meta">
        <span>审核时间: {now}</span>
        <span>模型: {config.MODEL_NAME}</span>
        <span>总数: {stats['total']} 张</span>
        <span>成功: {stats['success']} 张</span>
        <span>失败: {stats['errors']} 张</span>
    </div>
</div>

<!-- Export buttons -->
<div class="export-btns">
    <a class="export-btn excel" href="report.xlsx">导出 Excel</a>
    <a class="export-btn csv" href="report.csv">导出 CSV</a>
    <a class="export-btn json" href="results.json">导出 JSON</a>
</div>

<!-- Stats Overview -->
<div class="stats-grid">
    <div class="stat-card green"><div class="num">{stats['success']}</div><div class="label">审核成功</div></div>
    <div class="stat-card red"><div class="num">{stats['errors']}</div><div class="label">审核失败</div></div>
    <div class="stat-card green"><div class="num">{stats['compliant_rate']}%</div><div class="label">合规率</div></div>
    <div class="stat-card blue"><div class="num">{stats['avg_quality']}</div><div class="label">平均质量分</div></div>
    <div class="stat-card blue"><div class="num">{stats['avg_poem']}</div><div class="label">平均契合度</div></div>
    <div class="stat-card"><div class="num">{stats['avg_total']}</div><div class="label">平均总分</div></div>
    <div class="stat-card orange"><div class="num">{stats['non_compliant']}</div><div class="label">不合规数</div></div>
    <div class="stat-card orange"><div class="num">{stats['text_garbled_count']}</div><div class="label">文字乱码数</div></div>
    <div class="stat-card"><div class="num">{stats['total_tokens']:,}</div><div class="label">总Token消耗</div></div>
</div>

<!-- Grade Distribution -->
<div class="section">
    <h2>分级统计</h2>
    {grade_bars}
    <div style="margin-top:12px;font-size:12px;color:#888">
        A级(优秀 ≥8.0) | B级(良好 ≥6.0) | C级(及格 <6.0) | D级(不合规 一票否决)
    </div>
</div>

<!-- Style Distribution -->
<div class="section">
    <h2>画风分布</h2>
    {style_bars}
</div>

<!-- Thumbnail Grid -->
<div class="section">
    <h2>图片预览</h2>
    <div class="filters">
        <button class="filter-btn active" onclick="filterCards('ALL')">全部 ({stats['success']})</button>
        <button class="filter-btn" onclick="filterCards('A')">A级 ({stats['grade_counts'].get('A',0)})</button>
        <button class="filter-btn" onclick="filterCards('B')">B级 ({stats['grade_counts'].get('B',0)})</button>
        <button class="filter-btn" onclick="filterCards('C')">C级 ({stats['grade_counts'].get('C',0)})</button>
        <button class="filter-btn" onclick="filterCards('D')">D级 ({stats['grade_counts'].get('D',0)})</button>
    </div>
    <div class="card-grid" id="cardGrid">
        {cards_html}
    </div>
</div>

<!-- Detail Table -->
<div class="section">
    <h2>审核明细</h2>
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>诗名</th>
                    <th>变体</th>
                    <th>画风</th>
                    <th>置信度</th>
                    <th>质量分</th>
                    <th>契合度</th>
                    <th>合规</th>
                    <th>文字</th>
                    <th>总分</th>
                    <th>等级</th>
                    <th>质量说明</th>
                    <th>契合说明</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
</div>

<!-- Error list -->
{error_list_html}

</div>

<!-- Modal -->
<div class="modal-overlay" id="modal" onclick="closeModal()">
    <span class="modal-close" onclick="closeModal()">&times;</span>
    <img class="modal-img" id="modalImg" src="">
    <div class="modal-title" id="modalTitle"></div>
</div>

<script>
// 筛选
function filterCards(grade) {{
    const cards = document.querySelectorAll('.card');
    cards.forEach(c => {{
        if (grade === 'ALL' || c.dataset.grade === grade) {{
            c.style.display = '';
        }} else {{
            c.style.display = 'none';
        }}
    }});
    // 更新按钮状态
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
}}

// 模态框
function openModal(url, name) {{
    // url 已是完整 file:// URL（原图路径已做 URL 编码），直接赋值即可
    const modal = document.getElementById('modal');
    const img = document.getElementById('modalImg');
    const title = document.getElementById('modalTitle');
    img.src = url;
    title.textContent = name;
    modal.classList.add('active');
}}
function closeModal() {{
    document.getElementById('modal').classList.remove('active');
}}
// ESC关闭
document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') closeModal();
}});
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

    output_path = os.path.join(config.OUTPUT_DIR, "report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML报告已生成: {output_path}")
    print(f"用浏览器打开即可查看")


if __name__ == "__main__":
    main()
