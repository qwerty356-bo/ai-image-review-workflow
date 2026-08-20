# AI 图片 / 视频审核工作流

批量审核 AI 生成的**古诗词背景图片**和**古诗词教学视频**的自动化工具。基于视觉大模型 API，从多个维度自动打分、分级，并生成可视化报告与可分发表格。

支持图片审核（5 维度）和视频审核（6 维度，比图片多了「史实准确性」），两者相互独立、互不影响。

---

## 功能特性

- **图片审核 5 维度**：画风、画面质量、内容合规、诗词契合度、AI 文字检测
- **视频审核 6 维度**：在图片 5 维度基础上增加「史实准确性」
- **小数评分 + 加权总分 + A/B/C/D 分级**（D 级 = 不合规 / 史实错误，一票否决）
- **断点续跑**：中途中断后重新运行会自动跳过已审核的素材
- **失败重试**：`--retry-failed` 只重试之前报错的素材
- **可视化 HTML 报告**：统计概览 + 缩略图网格（可筛选、点击放大）+ 明细表
- **Excel / CSV 导出**：格式化数据，可分发
- **视频自动抽帧**：ffmpeg 均匀抽 6 帧 → 逐帧审核 → 聚合为视频级评分

---

## 目录结构

```
image-review/
├── config.py               # 图片审核配置（API / 路径 / 权重 / 分级阈值）
├── video_config.py         # 视频审核配置（独立，不影响图片）
├── poems_data.py           # 119 首诗名 → 意境关键词映射表
│
├── # ---- 图片审核 ----
├── review.py               # 单张图片审核逻辑（读图→调API→解析5维度JSON）
├── batch_run.py            # 图片批量执行入口 ★
├── generate_report.py      # 生成图片 HTML 报告
├── export_excel.py         # 导出图片 Excel/CSV
│
├── # ---- 视频审核 ----
├── frame_extractor.py      # ffmpeg 抽帧
├── video_review.py         # 单帧 6 维度审核
├── aggregation.py          # 帧结果聚合成视频级评分
├── video_batch_run.py      # 视频批量执行入口 ★
├── generate_video_report.py# 生成视频 HTML 报告
├── export_video_excel.py   # 导出视频 Excel/CSV
├── gen_thumbnails.py       # 补生成缩略图（工具）
│
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量配置模板（复制为 .env）
├── .gitignore              # 忽略密钥 / 素材 / 输出 / 缓存
└── 使用说明.md              # 详细图文使用说明
```

---

## 环境准备（只需做一次）

### 1. 安装 Python（3.8+）与依赖

```bash
pip install -r requirements.txt
```

依赖：`requests`、`Pillow`、`openpyxl`

### 2. 配置 API 网关与 Key（二选一）

**方式 A：环境变量（推荐，不会泄露密钥，也不暴露网关地址）**

复制 `.env.example` 为 `.env`，填入你的真实 **API 网关地址（`API_BASE_URL`）** 与 **API Key**，以及素材路径。程序会自动读取。

**方式 B：直接改配置**

打开 `config.py`（图片）和 `video_config.py`（视频），把 `API_BASE_URL` 改成你的真实网关地址、`API_KEY` 改成你的真实密钥，`IMAGE_DIR` / `VIDEO_DIR` 改成素材文件夹路径。

> ⚠️ 若直接改配置，请勿把 `config.py` / `video_config.py` 提交到**公开**仓库，否则密钥和网关地址会泄露。

### 3. 视频审核额外需要 ffmpeg

下载 ffmpeg（full build）并解压，把 `video_config.py` 中的 `FFMPEG_PATH` / `FFPROBE_PATH` 改成你电脑上的实际路径。

---

## 运行流程

### 图片审核

```bash
# 1. 批量审核（把图片放进 IMAGE_DIR 指向的文件夹）
python batch_run.py

# 2. 生成 HTML 报告
python generate_report.py

# 3. 导出 Excel/CSV
python export_excel.py
```

### 视频审核

```bash
python video_batch_run.py          # 批量审核（自动抽帧+逐帧审核+聚合）
python generate_video_report.py    # 生成 HTML 报告
python export_video_excel.py       # 导出 Excel/CSV
```

### 常用参数（batch_run / video_batch_run）

| 参数 | 作用 |
| --- | --- |
| `--test 10` | 只跑前 10 张/个，用于快速验证 |
| `--retry-failed` | 只重试之前报错的素材 |

---

## 结果输出

所有结果输出到 `output/`（图片）和 `output/video/`（视频）：

| 文件 | 说明 |
| --- | --- |
| `results.json` | 审核原始数据（增量保存，断点续跑依据） |
| `report.html` | 可视化报告（浏览器直接打开，需用 Chrome/Edge） |
| `report.xlsx` | Excel 导出（多 Sheet） |
| `report.csv` | CSV 导出 |
| `thumbnails/` | 缩略图 |
| `frames/` | 视频抽出的帧（仅视频） |
| `frame_results/` | 单帧审核结果（仅视频） |

---

## 评分规则（如何修改审核规则）

### 权重调整

打开 `config.py` / `video_config.py` 中的 `WEIGHTS` 字典，改各维度的比重（需加起来接近 1）：

```python
WEIGHTS = {
    "quality_score": 0.35,      # 画面质量
    "poem_match_score": 0.35,   # 诗词契合度
    "style_confidence": 0.10,   # 画风
    "compliance": 0.10,         # 合规
    "text": 0.10,               # AI文字
}
```

### 分级阈值调整

`GRADE_THRESHOLDS` 字典控制 A/B/C 的分数门槛：

```python
GRADE_THRESHOLDS = {
    "A": 8.0,   # >= 8.0 为 A
    "B": 6.0,   # >= 6.0 为 B
    "C": 0.0,   # < 6.0 为 C
}
```

### 修改审核维度 / 提示词

- 图片审核维度与 Prompt 在 `review.py` 顶部的 `REVIEW_PROMPT_TEMPLATE`
- 视频审核维度与 Prompt 在 `video_review.py` 顶部的 `VIDEO_REVIEW_PROMPT_TEMPLATE`
- 若新增/删除维度，需同步修改：`WEIGHTS`、`review.py` / `video_review.py` 的结果解析逻辑、`generate_report.py` / `export_excel.py` 的展示与导出字段

### 一票否决（D 级）

- 图片：`compliance` 不合规 → D
- 视频：任一帧 `compliance` 不合规，或 `history_score` 史实严重错误 → D（见 `aggregation.py`）

### 意境关键词表

`poems_data.py` 中维护 119 首诗名 → 意境关键词的映射，用于审核时给模型提供参考意境。

---

## 迁移到其他电脑

1. **拉取代码**：`git clone` 或拷贝本项目
2. **装依赖**：`pip install -r requirements.txt`
3. **配置**：复制 `.env.example` 为 `.env`，填 API Key 与素材路径；或直接改 `config.py` / `video_config.py`
4. **视频审核**：装好 ffmpeg 并改 `video_config.py` 中的路径
5. **运行**：按上文运行流程执行

代码中**不包含**绝对路径（已全部改为相对 `__file__` 或环境变量），所以拿到任何电脑都能直接跑。

---

## 安全说明

- `.gitignore` 已排除 `.env`、`config_local.py`、`images/`、`videos/`、`output/`、`__pycache__/` 等
- 请勿把真实 API Key 提交到公开仓库
- 待审核素材与输出结果体积大且可能含隐私，默认不入库

---

## 说明

- 本项目为个人工作流工具，基于视觉大模型 API 网关，模型默认 `doubao-seed-evolving`
- API 网关地址通过环境变量 `API_BASE_URL` 配置（不写入代码），避免暴露私有地址
- API 调用的 `User-Agent` 也可通过环境变量 `API_USER_AGENT` 配置，避免暴露工具标识
- 详细图文操作见 `使用说明.md`
