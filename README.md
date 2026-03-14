# 多平台评论爬取与 BERT 情感分析流水线

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)

本项目提供一套可在 **GitHub Codespaces** 一键运行的流程：

> 按关键词抓取多平台评论 (小红书 / 京东 / B站 / 知乎)  →  清洗  →  BERT 三分类情感分析  →  输出汇总与简单统计

---

## 目录结构

```
├── crawler/
│   ├── __init__.py
│   ├── xhs.py          # 小红书
│   ├── jd.py           # 京东商品评论
│   ├── bilibili.py     # B站视频评论
│   └── zhihu.py        # 知乎回答 / 文章
├── pipeline/
│   ├── __init__.py
│   ├── cleaning.py     # 清洗与去重
│   └── sentiment.py    # BERT 情感推理
├── configs/
│   ├── keywords.txt    # 一行一个关键词
│   └── platforms.yaml  # 平台启用/参数配置
├── scripts/
│   └── run_all.py      # 端到端入口
├── data/
│   ├── raw/            # 爬取原始数据 (JSON)
│   ├── clean/          # 清洗后数据 (JSON)
│   └── output/         # 情感结果 (CSV) + 汇总统计
├── logs/
│   └── app.log         # 运行日志
├── requirements.txt
├── Makefile
└── README.md
```

---

## 快速开始（Codespaces / 本地）

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 如果使用 Playwright（小红书 / 知乎可选增强）:
playwright install chromium
```

或直接用 Makefile：

```bash
make setup
```

### 2. 配置关键词

编辑 `configs/keywords.txt`，每行一个关键词，`#` 开头为注释：

```
手机
耳机
护肤品
```

### 3. 配置平台参数

编辑 `configs/platforms.yaml`，可启用/禁用平台并调整抓取页数、频率等参数。

### 4. 设置环境变量（可选，用于登录鉴权）

| 变量 | 平台 | 说明 |
|------|------|------|
| `XHS_COOKIE` | 小红书 | 必须；未设置时返回示例数据 |
| `JD_COOKIE` | 京东 | 可选；不登录也可抓公开评论 |
| `BILI_SESSDATA` | B站 | 可选；提升 API 配额 |
| `ZHIHU_COOKIE` | 知乎 | 可选；未设置时降低请求频率 |

**获取 Cookie 方法（以 Chrome 为例）**：
1. 登录对应平台网站
2. 按 `F12` → Application → Cookies
3. 将完整的 Cookie 字符串复制为环境变量

**设置方式**：

```bash
# Bash
export XHS_COOKIE="web_session=xxxx; ..."
export JD_COOKIE="pin=xxx; pt_key=xxx; ..."
export BILI_SESSDATA="xxxxxxxx"
export ZHIHU_COOKIE="z_c0=xxxx; ..."
```

在 Codespaces 中可在 **Repository secrets** 或 `.env` 文件中设置。

### 5. 运行

```bash
# 使用所有平台，每平台每关键词最多 50 条
python scripts/run_all.py

# 自定义参数
python scripts/run_all.py \
  --keywords-file configs/keywords.txt \
  --platforms xhs,jd,bilibili,zhihu \
  --limit-per-platform 30 \
  --model-name uer/roberta-base-finetuned-jd-binary-chinese

# 只爬取，跳过情感分析
python scripts/run_all.py --skip-sentiment

# 使用 Makefile
make run
```

---

## CLI 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--keywords-file` | `configs/keywords.txt` | 关键词文件路径 |
| `--platforms` | `xhs,jd,bilibili,zhihu` | 启用的平台（逗号分隔） |
| `--limit-per-platform` | `50` | 每平台每关键词最大条数 |
| `--model-name` | `uer/roberta-base-finetuned-jd-binary-chinese` | HuggingFace 情感分析模型 |
| `--batch-size` | `32` | 推理 batch size |
| `--skip-sentiment` | `False` | 跳过情感分析 |
| `--verbose` | `False` | 输出 DEBUG 日志 |

---

## 推荐情感分析模型

| 模型 | 说明 |
|------|------|
| `uer/roberta-base-finetuned-jd-binary-chinese` | 京东评论二分类，中文效果好（**默认**） |
| `hfl/chinese-roberta-wwm-ext` | 基础语言模型，需自行 fine-tune 后使用 |
| `IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment` | 中文三分类情感模型 |

---

## 输出文件

| 文件 | 说明 |
|------|------|
| `data/raw/raw_<timestamp>.json` | 各平台爬取的原始数据 |
| `data/clean/clean_<timestamp>.json` | 清洗去重后的数据 |
| `data/output/sentiment_results.csv` | 完整情感分析结果 |
| `data/output/summary.json` | 各平台/关键词情感分布统计（JSON） |
| `data/output/summary.csv` | 同上（CSV 格式） |
| `logs/app.log` | 运行日志 |

### `sentiment_results.csv` 字段说明

| 字段 | 说明 |
|------|------|
| `platform` | 来源平台（xhs/jd/bilibili/zhihu） |
| `keyword` | 关键词 |
| `content` | 清洗后的评论内容 |
| `like_count` | 点赞数（无则 0） |
| `publish_time` | 发布时间（ISO 格式，未知则空） |
| `source_url` | 原始链接 |
| `meta` | 附加元数据（JSON 字符串） |
| `crawl_time` | 爬取时间 |
| `sentiment_label` | 情感标签（positive/negative/neutral） |
| `sentiment_score` | 预测置信度 |

---

## 常见问题

### 登录失效 / Cookie 过期

重新获取 Cookie 并更新环境变量。小红书 Cookie 有效期较短（约 1 天），建议在运行前刷新。

### 429 频率限制

各平台的 `throttle_min` / `throttle_max` 参数控制请求间隔。在 `configs/platforms.yaml` 中适当增大这两个值。

### 小红书签名问题

小红书 API 需要动态签名（`X-S` / `X-T` 请求头），如遇 401/471 错误，说明签名算法已更新，需参考最新的逆向工程方案或改用 Playwright 自动化方案。

### 无法抓取真实数据

如果 Cookie 未配置或 API 返回错误，每个爬虫会自动回退到**内置示例数据**，保证流水线能完整运行。

### GPU 加速

`run_all.py` 默认使用 CPU。若有 GPU，安装对应版本的 `torch` 并在代码中将 `device=-1` 改为 `device=0`。

---

## 开发

```bash
# 单独测试某个爬虫
python -c "from crawler.bilibili import crawl; print(crawl('手机', limit=5))"

# 单独测试清洗
python -c "
from pipeline.cleaning import clean
records = [{'platform':'test','content':'这是一条测试评论，很好用！','keyword':'test','like_count':0,'publish_time':'','source_url':'','meta':{},'crawl_time':''}]
print(clean(records))
"

# 单独测试情感分析
python -c "
from pipeline.sentiment import run_sentiment
records = [{'platform':'test','content':'这个产品真的很好！','keyword':'test','like_count':0,'publish_time':'','source_url':'','meta':{},'crawl_time':''}]
print(run_sentiment(records))
"
```
