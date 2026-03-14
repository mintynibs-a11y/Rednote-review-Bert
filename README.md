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

> 💡 **什么是"环境变量"？**
>
> 把它想象成一张**贴在电脑桌面上的便利贴**，上面写着你的账号 Cookie。
> 程序运行时会自动去读这张便利贴——这样你就不需要把敏感信息直接写进代码里。
> 设置过一次后，每次打开新终端都需要重新设置（除非写入配置文件，见下文）。

#### 4.1 各平台需要哪个环境变量？

| 环境变量名 | 对应平台 | 是否必须 | 不设置会怎样 |
|-----------|---------|---------|------------|
| `XHS_COOKIE` | 小红书 | **必须** | 程序返回内置示例数据，不抓取真实评论 |
| `JD_COOKIE` | 京东 | 可选 | 不登录也能抓部分公开评论 |
| `BILI_SESSDATA` | B站 | 可选 | 匿名访问，配额较低 |
| `ZHIHU_COOKIE` | 知乎 | 可选 | 不登录时自动降低请求频率 |

---

#### 4.2 如何设置环境变量？

##### ▶ 方法一：命令行临时设置（推荐新手先用这个）

**Windows 命令提示符（CMD）：**
```cmd
set XHS_COOKIE=web_session=xxxx; xsecappid=xxxx
set JD_COOKIE=pin=xxx; pt_key=xxx
set BILI_SESSDATA=xxxxxxxx
set ZHIHU_COOKIE=z_c0=xxxx
```
> ⚠️ 注意：CMD 里等号两边**不要加空格**，且不需要引号。

**Windows PowerShell：**
```powershell
$env:XHS_COOKIE = "web_session=xxxx; xsecappid=xxxx"
$env:JD_COOKIE  = "pin=xxx; pt_key=xxx"
$env:BILI_SESSDATA = "xxxxxxxx"
$env:ZHIHU_COOKIE  = "z_c0=xxxx"
```

**Mac / Linux（Terminal / Bash）：**
```bash
export XHS_COOKIE="web_session=xxxx; xsecappid=xxxx"
export JD_COOKIE="pin=xxx; pt_key=xxx"
export BILI_SESSDATA="xxxxxxxx"
export ZHIHU_COOKIE="z_c0=xxxx"
```
> 💡 `export` 的意思就是"把这个变量公开给子进程（即 Python 脚本）使用"。

---

##### ▶ 方法二：写入 `.env` 文件（永久生效，推荐）

在项目根目录新建一个名为 `.env` 的文本文件，内容如下：

```
XHS_COOKIE=web_session=xxxx; xsecappid=xxxx
JD_COOKIE=pin=xxx; pt_key=xxx
BILI_SESSDATA=xxxxxxxx
ZHIHU_COOKIE=z_c0=xxxx
```

然后在每次运行前，先执行（Mac / Linux）：
```bash
source .env      # 或者：set -a; source .env; set +a
```

Windows PowerShell：
```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match "^([^#][^=]+)=(.+)$") {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
    }
}
```

> ⚠️ **安全提示**：`.env` 文件包含账号信息，已在 `.gitignore` 中排除，**千万不要上传到 GitHub**！

---

##### ▶ 方法三：GitHub Codespaces 中设置（推荐在 Codespaces 运行时使用）

1. 打开 GitHub 仓库页面
2. 点击 **Settings**（设置）→ 左侧 **Secrets and variables** → **Codespaces**
3. 点击 **New repository secret**（新建仓库密钥）
4. 依次添加 `XHS_COOKIE`、`JD_COOKIE`、`BILI_SESSDATA`、`ZHIHU_COOKIE`
5. 重新启动 Codespaces，环境变量会自动注入

---

#### 4.3 如何获取 Cookie？（以 Microsoft Edge 为例）

> **Cookie 是什么？** 登录网站后，网站会给你浏览器发一张"通行证"，存储在浏览器里，这就是 Cookie。
> 我们需要把这张通行证复制给爬虫程序，让它"冒充"你去访问数据。

---

**📖 通用步骤（所有平台相同）**

**第一步：登录目标平台**
1. 打开 Edge 浏览器，访问对应网站并**完成登录**
   - 小红书：https://www.xiaohongshu.com
   - 京东：https://www.jd.com
   - B站：https://www.bilibili.com
   - 知乎：https://www.zhihu.com

**第二步：打开开发者工具**
1. 按键盘上的 **`F12`** 键（或右键页面 → 点击"检查"）
2. 弹出的面板就是"开发者工具"

**第三步：找到 Cookie**
1. 在顶部标签栏中点击 **`应用程序`**（英文版：**`Application`**）
   - 如果没看到，点击顶部标签栏最右边的 **`>>`** 展开更多选项
2. 在左侧面板中，展开 **`存储`** → **`Cookie`**
3. 点击当前网站的域名（例如 `https://www.xiaohongshu.com`）
4. 右侧会出现一个表格，里面每一行就是一个 Cookie 条目

**第四步：复制 Cookie 字符串**

方法 A（推荐）：使用网络请求一键复制
1. 切换到顶部标签的 **`网络`**（英文：**`Network`**）选项卡
2. 按 **`Ctrl+R`** 刷新页面（让请求重新发出）
3. 在左侧请求列表里，点击任意一个请求（通常是域名本身，如 `www.xiaohongshu.com`）
4. 在右侧点击 **`标头`**（英文：**`Headers`**）
5. 找到 **`请求标头`** 下的 **`Cookie`** 字段
6. 单击 Cookie 的值，全选（`Ctrl+A`），复制（`Ctrl+C`）
7. 这就是完整的 Cookie 字符串 ✅

方法 B：手动拼接（仅当方法 A 不可用时）
1. 回到 `应用程序 → Cookie → 域名`
2. 逐行记录重要 Cookie 的名称和值（见下方各平台说明）
3. 按 `名称=值; 名称=值; ...` 的格式拼接成字符串

---

**🔴 小红书（XHS）— 必须登录**

关键 Cookie 字段（缺少任一都可能导致请求被拒绝）：

| Cookie 名称 | 说明 |
|------------|------|
| `web_session` | 登录会话 ID，**最重要** |
| `xsecappid` | 应用 ID |
| `a1` | 设备标识 |
| `webId` | Web 用户 ID |

完整 Cookie 示例（格式）：
```
XHS_COOKIE=web_session=040069b3xxxx; xsecappid=xhs-pc-web; a1=190xxxxxx; webId=xxxxxxxx
```

> ⚠️ 小红书 Cookie **有效期约 1 天**，建议每天运行前刷新。
> 若遇到 401 错误，说明 Cookie 已过期，需重新获取。

---

**🟠 京东（JD）— 可选**

关键 Cookie 字段：

| Cookie 名称 | 说明 |
|------------|------|
| `pt_key` | 登录凭证，**最重要** |
| `pt_pin` | 用户名（URL 编码后的中文） |

完整 Cookie 示例：
```
JD_COOKIE=pt_key=AAxxxxxxxxxx; pt_pin=xxxxxxxx
```

> 💡 不设置 `JD_COOKIE` 时，程序仍能抓取部分公开评论（无需登录）。

---

**🔵 B站（Bilibili）— 可选，只需 SESSDATA**

B站只需要一个特殊值 `SESSDATA`，**不是整个 Cookie 字符串**：

1. 打开开发者工具 → `应用程序` → `Cookie` → `https://www.bilibili.com`
2. 在表格中找到名为 **`SESSDATA`** 的行
3. 复制该行的 **`值`** 列（不是整行，只是值本身）

```
BILI_SESSDATA=xxxxxxxx%2Cxxxxxxxxxx%2Cxxxxxxxx
```

> 💡 不设置也可以运行，只是匿名请求的频率上限较低。

---

**🟢 知乎（Zhihu）— 可选**

关键 Cookie 字段：

| Cookie 名称 | 说明 |
|------------|------|
| `z_c0` | 登录凭证，**最重要** |
| `_zap` | 用户标识 |

完整 Cookie 示例：
```
ZHIHU_COOKIE=z_c0=xxxxxxxx; _zap=xxxxxxxx
```

---

#### 4.4 验证环境变量是否设置成功

设置完毕后，在终端运行以下命令验证：

**Mac / Linux：**
```bash
echo $XHS_COOKIE       # 应该输出你设置的 Cookie 字符串
echo $JD_COOKIE
echo $BILI_SESSDATA
echo $ZHIHU_COOKIE
```

**Windows CMD：**
```cmd
echo %XHS_COOKIE%
echo %JD_COOKIE%
```

**Windows PowerShell：**
```powershell
echo $env:XHS_COOKIE
echo $env:JD_COOKIE
```

如果输出了 Cookie 值，说明设置成功！如果输出空白，说明设置失败，请重新检查步骤。

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

---

## 扩展阅读文档

对代码结构感兴趣？查看以下文档：

- 📄 [docs/pseudocode.md](docs/pseudocode.md) — 整个项目的伪代码，帮助理解程序运行逻辑
- 📄 [docs/code_explanation.md](docs/code_explanation.md) — 每个文件和关键概念的通俗解释，适合初学者
