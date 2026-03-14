# 代码结构与逻辑通俗解释

> 本文档面向没有太多编程经验的读者，用最通俗的语言解释这个项目的每个文件做了什么、为什么这样设计。

---

## 一、项目整体比喻

把这个项目想象成一条**工厂流水线**：

```
原材料（网络上的评论）
    → 采购部门（爬虫 crawler/）：从各平台"买"原材料
    → 质检部门（清洗 pipeline/cleaning.py）：剔除残次品
    → 分析部门（情感分析 pipeline/sentiment.py）：给每件产品打标签
    → 仓库（data/output/）：存放最终成品
    → 报表（summary.json）：统计生产数量和质量分布
```

---

## 二、文件结构逐一解释

### 📁 `configs/` — 配置文件夹

#### `configs/keywords.txt` — 关键词清单

```
手机
耳机
护肤品
# 这是注释，程序会自动忽略
```

**用途**：告诉程序"你要搜索什么词"。就像去超市购物前列的清单。
- 每行一个词
- `#` 开头的行是注释（备注），程序会跳过
- 可以随时修改，不需要改代码

---

#### `configs/platforms.yaml` — 平台参数配置

这是一个 YAML 格式的配置文件。YAML 是一种非常接近自然语言的配置格式，用缩进表示层次关系。

```yaml
platforms:
  xhs:                      ← 平台名称（小红书）
    enabled: true           ← true = 开启, false = 关闭
    max_pages: 3            ← 最多抓几页
    page_size: 20           ← 每页抓几条
    throttle_min: 1.5       ← 每次请求最少等待1.5秒（防止被封）
    throttle_max: 3.0       ← 每次请求最多等待3.0秒
    retry_times: 3          ← 失败后重试3次
```

**用途**：就像给每个"采购员"下达工作指令——你去小红书，每次最多搜3页，每次请求后休息1.5~3秒，别抓太快被平台封了。

**常用调整**：
- 遇到 429 错误（被限速）→ 增大 `throttle_min` 和 `throttle_max`
- 想抓更多数据 → 增大 `max_pages` 或运行时加 `--limit-per-platform 100`
- 暂时不想爬某个平台 → 把 `enabled` 改为 `false`

---

### 📁 `crawler/` — 爬虫文件夹

这里有 4 个爬虫，各自负责一个平台。它们长得很像，都遵循同一套"合同"：

> **对外承诺**：给我一个关键词和一个数量上限，我还给你一个评论列表，列表里每条评论都包含固定的字段。

#### 每条评论的统一字段格式

所有爬虫返回的评论都包含以下字段（就像统一格式的表格）：

| 字段名 | 含义 | 例子 |
|--------|------|------|
| `platform` | 来源平台 | `"bilibili"` |
| `keyword` | 搜索关键词 | `"手机"` |
| `content` | 评论正文 | `"这款手机摄像头真的超好！"` |
| `like_count` | 点赞数 | `128` |
| `publish_time` | 发布时间 | `"2024-01-15T10:30:00"` |
| `source_url` | 原始链接 | `"https://..."` |
| `meta` | 额外信息 | `{"video_id": "BV1234", "user": "用户名"}` |
| `crawl_time` | 本次爬取时间 | `"2024-03-01T08:00:00"` |

#### `crawler/xhs.py` — 小红书爬虫

**原理**：
1. 检查 `XHS_COOKIE` 环境变量是否存在
2. 若存在：带着 Cookie 调用小红书搜索 API（`/api/sns/web/v1/search/notes`）
3. 解析返回的 JSON，提取笔记标题/描述、点赞数、发布时间等
4. 若失败（401、471 签名错误等）：返回内置示例数据

**为什么小红书最难**：小红书的 API 需要动态签名（`X-S`、`X-T` 请求头），签名算法每隔一段时间就更新，是一场持续的"猫鼠游戏"。

#### `crawler/jd.py` — 京东爬虫

**原理（两步走）**：
1. **第一步**：搜索商品
   - 访问京东搜索接口，找到关键词对应的商品 ID（`skuId`）
2. **第二步**：获取评论
   - 用商品 ID 调用评论接口（`/comment/skuProductPageComments.action`）

**为什么分两步**：京东的评论是挂在商品下面的，必须先知道商品编号，才能查评论。

#### `crawler/bilibili.py` — B站爬虫

**原理（两步走）**：
1. **第一步**：搜索视频
   - 调用 B站搜索 API，找到关键词相关的视频 ID（`bvid`）
2. **第二步**：获取评论
   - 用视频 ID 调用评论接口（`/x/v2/reply`）

**为什么 B站最友好**：B站的 API 大部分无需登录就能访问，设计也比较规范，返回标准 JSON 格式。

#### `crawler/zhihu.py` — 知乎爬虫

**原理**：
1. 调用知乎搜索 API（`/api/v4/search_v3`），搜索关键词相关的问答
2. 解析回答内容（去除 HTML 标签）
3. 若无 Cookie，自动将 `throttle_min` 调高（请求间隔延长），避免被封

---

### 📁 `pipeline/` — 数据处理流水线

#### `pipeline/cleaning.py` — 清洗模块

**核心问题**：爬虫抓回来的原始数据"很脏"——可能有广告、纯表情、英文评论、重复评论等。情感分析模型只能处理干净的中文文本，所以需要先清洗。

**清洗步骤详解**：

```
1. 删除 HTML 标签
   "这款产品<br>真的很好" → "这款产品真的很好"

2. 删除表情符号（需要安装 emoji 库）
   "超级好用😍🎉" → "超级好用"

3. 删除控制字符（看不见但会干扰模型的特殊字符）

4. Unicode 规范化
   "１２３" → "123"（全角数字转半角）

5. 合并多余空格
   "这款  产品  好用" → "这款 产品 好用"

6. 长度过滤
   "好" → 删除（太短，只有1个字，没有分析价值）
   [超过1000字的文本] → 删除（可能是爬取错误或广告）

7. 语言过滤
   "nice product!" → 删除（英文，BERT 中文模型分析不准）

8. 去重（最关键）
   计算 MD5 指纹 = hash("平台名" + "评论内容")
   如果同一平台出现完全相同的两条评论，只保留第一条
```

**为什么用 MD5 而不是直接比较字符串**：MD5 是一种"摘要算法"，可以把任意长度的文字压缩成一个固定长度的字符串（如 `a3f2b1c4...`）。比较 MD5 比比较完整字符串快得多，而且节省内存。

---

#### `pipeline/sentiment.py` — 情感分析模块

**核心问题**：如何让计算机理解一段文字是"正面"还是"负面"？

**BERT 是什么**：
BERT（Bidirectional Encoder Representations from Transformers）是一种深度学习模型，由 Google 在 2018 年发布。
- 它已经"读"了数十亿网页的文字，学会了中文语言的规律
- 我们使用的是别人已经在中文评论数据集上"微调"好的版本
- 输入一段文字，它输出"这句话是正面/负面的概率"

**置信度阈值（NEUTRAL_THRESHOLD = 0.70）的含义**：

```
假设模型预测"这款手机还不错"：
  positive 概率 = 0.65
  negative 概率 = 0.35

因为 0.65 < 0.70（阈值），模型"不够确定"这是正面的
所以我们标记为 neutral（中性），而不是强行选 positive
```

这个设计避免了"强制分类"带来的误差——当模型拿不准时，诚实地说"不确定"。

**批量推理（batch_size）的含义**：
- 一条条处理：每次处理1条，处理100条需要100次
- 批量处理（batch=32）：每次处理32条，处理100条只需要4次
- 批量处理快得多，因为 GPU/CPU 可以并行计算

---

### 📁 `scripts/` — 脚本文件夹

#### `scripts/run_all.py` — 主程序（入口）

这是整个项目的"指挥官"，负责：
1. 读取命令行参数（`--platforms`、`--limit-per-platform` 等）
2. 加载关键词和配置
3. 按顺序调用爬虫 → 清洗 → 情感分析
4. 保存所有结果
5. 生成统计报告

**命令行参数是什么**：就是运行程序时在命令后面加的选项，比如：
```bash
python scripts/run_all.py --platforms xhs,bilibili --limit-per-platform 30
```
这里 `--platforms xhs,bilibili` 就是一个参数，告诉程序"只抓小红书和B站"。

---

### 📁 `data/` — 数据目录

| 子目录 | 存什么 | 何时生成 |
|--------|--------|---------|
| `raw/` | 爬虫抓到的原始 JSON，未经任何处理 | 爬取完成后 |
| `clean/` | 清洗后的 JSON | 清洗完成后 |
| `output/` | 最终 CSV 结果 + 统计 JSON/CSV | 全部流程完成后 |

**为什么保存中间结果**：
- 如果情感分析中途失败，不用重新爬取，直接从 `clean/` 目录重新开始
- 原始数据和清洗数据都保留，方便调试问题

---

### 📁 `logs/` — 日志目录

`logs/app.log` 记录了程序运行的"流水账"：

```
2024-03-01 08:00:01 [INFO] 开始爬取 xhs 平台，关键词="手机"
2024-03-01 08:00:05 [WARNING] xhs: Cookie 未设置，返回示例数据
2024-03-01 08:00:06 [INFO] 清洗完成：共100条 → 保留92条
2024-03-01 08:05:30 [INFO] 情感分析完成：正面45条，负面30条，中性17条
```

**日志级别**：
- `INFO`：正常流程信息（"我现在在做X"）
- `WARNING`：有问题但不影响继续运行（"Cookie 没设置，用示例数据代替"）
- `ERROR`：严重问题，但程序尽量继续（"这个平台抓取失败，跳过继续其他平台"）

---

## 三、关键技术概念解释

### 什么是 JSON？

JSON（JavaScript Object Notation）是一种数据格式，就像"结构化的文本"。

```json
{
  "platform": "bilibili",
  "keyword": "手机",
  "content": "这款手机超级好！",
  "like_count": 128
}
```

你可以把它理解为一个表格的一行，用大括号 `{}` 包起来，里面是"字段名: 值"的对。

### 什么是 CSV？

CSV（Comma-Separated Values，逗号分隔值）是一种表格格式，可以用 Excel 直接打开：

```
platform,keyword,content,sentiment_label
bilibili,手机,这款手机超级好！,positive
xhs,耳机,音质一般般,negative
```

### 什么是 API？

API（Application Programming Interface）就是网站提供的"数据接口"。
就像餐厅的"菜单"——你按菜单点菜（发送请求），餐厅给你上菜（返回数据）。

### 什么是 Cookie？

你登录网站后，网站给你浏览器"盖的章"，表示"这个人已经登录了"。
爬虫拿着这个"章"去访问网站，网站就以为是你本人在浏览，会返回需要登录才能看到的数据。

### 什么是节流（Throttle）？

就是"人为放慢速度"。
爬虫每抓一次数据后，主动等待 1~3 秒，模拟正常用户的浏览速度，避免被平台识别为机器人并封锁。

---

## 四、常见报错与原因

| 报错 | 原因 | 解决方法 |
|------|------|---------|
| `XHS_COOKIE not set` | 小红书 Cookie 未配置 | 设置 `XHS_COOKIE` 环境变量（见 README 第4节） |
| `401 Unauthorized` | Cookie 过期或无效 | 重新获取 Cookie |
| `429 Too Many Requests` | 请求太频繁被限速 | 增大 `throttle_min/throttle_max` |
| `No records collected` | 所有平台都没抓到数据 | 检查 Cookie、网络连接 |
| `transformers not installed` | 未安装 Python 依赖 | 运行 `pip install -r requirements.txt` |
| `CUDA out of memory` | GPU 显存不足 | 减小 `--batch-size` 或改用 CPU |

---

## 五、扩展与自定义

### 换一个情感分析模型

在运行命令中加上 `--model-name` 参数：

```bash
# 使用三分类模型（正/负/中性更准确）
python scripts/run_all.py --model-name IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment

# 使用二分类模型（更快）
python scripts/run_all.py --model-name uer/roberta-base-finetuned-jd-binary-chinese
```

### 只爬取特定平台

```bash
python scripts/run_all.py --platforms bilibili,zhihu
```

### 添加新关键词

直接编辑 `configs/keywords.txt`，每行加一个词即可，不需要修改任何代码。

### 关闭某个平台

编辑 `configs/platforms.yaml`，把对应平台的 `enabled` 改为 `false`：

```yaml
  xhs:
    enabled: false   ← 改这里
```
