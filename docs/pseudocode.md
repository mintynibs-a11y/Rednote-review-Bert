# 项目伪代码说明

> **什么是伪代码？**
> 伪代码是一种介于"自然语言"和"真实代码"之间的描述方式。
> 它用接近人类语言的方式描述程序逻辑，不必关心语法细节，任何人都能看懂。

---

## 一、整体流程图

```
用户输入关键词（比如"手机"）
        │
        ▼
┌───────────────────┐
│  爬虫模块          │  →  从 4 个平台抓取评论
│  crawler/          │     小红书 / 京东 / B站 / 知乎
└────────┬──────────┘
         │ 原始评论（可能含垃圾数据）
         ▼
┌───────────────────┐
│  清洗模块          │  →  去掉重复、太短、非中文的评论
│  pipeline/cleaning │
└────────┬──────────┘
         │ 干净的评论
         ▼
┌───────────────────┐
│  情感分析模块      │  →  用 BERT 判断每条评论是正面/负面/中性
│  pipeline/sentiment│
└────────┬──────────┘
         │ 带情感标签的评论
         ▼
┌───────────────────┐
│  统计汇总模块      │  →  统计各平台、各关键词的情感分布
│  scripts/run_all  │
└────────┬──────────┘
         │
         ▼
保存结果到 data/output/ 目录
```

---

## 二、主程序伪代码（`scripts/run_all.py`）

```
程序开始

【第一步：读取配置】
    从 configs/keywords.txt 读取所有关键词，存入列表
    从 configs/platforms.yaml 读取平台配置（哪些平台开启、每页抓多少条等）
    从命令行读取用户参数（如 --limit-per-platform 50）

【第二步：爬取评论】
    创建空列表 all_records = []

    对每个平台（小红书、京东、B站、知乎）循环：
        对每个关键词循环：
            调用该平台的爬虫函数（如 xhs.crawl("手机", limit=50)）
            
            如果爬取成功：
                把抓到的评论加入 all_records
            如果失败（网络错误、Cookie 过期等）：
                记录错误到日志
                继续下一个，不中断整体流程

    把 all_records 保存到 data/raw/raw_时间戳.json

【第三步：清洗评论】
    调用 pipeline.cleaning.clean(all_records)
    
    清洗过程会：
        → 删除重复评论
        → 删除没有中文的评论
        → 删除太短（<5字）或太长（>1000字）的评论
        → 清除表情符号、HTML标签等噪声
    
    把清洗后的评论保存到 data/clean/clean_时间戳.json

【第四步：情感分析】
    如果用户加了 --skip-sentiment 参数：
        跳过此步骤
    否则：
        加载 BERT 情感分析模型
        对每条清洗后的评论调用模型预测
        为每条评论添加两个字段：
            sentiment_label = "positive" 或 "negative" 或 "neutral"
            sentiment_score = 置信度（0~1 之间的小数）

【第五步：保存结果】
    把所有结果保存为 data/output/sentiment_results.csv

【第六步：生成统计报告】
    按平台统计：各情感标签的数量和占比
    按关键词统计：各情感标签的数量和占比
    保存到 data/output/summary.json 和 summary.csv

【第七步：打印总结】
    在终端显示：共处理 X 条，各平台情感分布

程序结束
```

---

## 三、爬虫模块伪代码（以 B站 `crawler/bilibili.py` 为例）

```
函数 crawl(关键词, 最大条数=50, 最大页数=3, ...):

    如果 BILI_SESSDATA 环境变量已设置：
        在请求头中加入登录凭证
    否则：
        匿名访问（有频率限制）

    创建空列表 results = []

    循环（第1页 到 第3页）：
        如果 results 条数已达到最大条数：退出循环
        
        【搜索视频】
        发送请求到 Bilibili 搜索 API，搜索关键词相关视频
        
        如果请求失败（网络错误）：
            等待几秒后重试（最多重试3次）
            如果3次都失败：跳过这一页，继续下一页
        
        取出前3个视频的 ID（不需要太多，避免被封）

        对每个视频：
            如果 results 条数已达到最大条数：退出循环
            
            【获取评论】
            发送请求到 Bilibili 评论 API
            
            对每条评论：
                取出评论文字、点赞数、发布时间、用户名
                打包成统一格式的字典：
                    {
                        platform: "bilibili",
                        keyword: 关键词,
                        content: 评论内容,
                        like_count: 点赞数,
                        publish_time: 发布时间,
                        source_url: 视频链接,
                        meta: { video_id, comment_id, user },
                        crawl_time: 当前时间
                    }
                加入 results
            
            等待 0.5~1.5 秒（模拟人工操作，避免被封）

    如果 results 为空（所有请求都失败了）：
        返回内置的示例数据（确保程序不崩溃）

    返回 results（最多 最大条数 条）
```

> 🔑 **关键设计思路**：每个爬虫都有"备用示例数据"兜底。
> 即使网络不通、Cookie 失效，程序也能跑完整个流程，不会报错崩溃。

---

## 四、清洗模块伪代码（`pipeline/cleaning.py`）

```
函数 clean(原始评论列表):

    已见过的评论指纹集合 seen = 空集合
    清洗后的列表 cleaned = []
    
    对每条评论循环：
        取出评论文字 text 和 platform（来源平台）
        
        【步骤1：清理噪声】
        删除 HTML 标签（如 <br>、<p> 等）
        替换 HTML 转义字符（&amp; → & 等）
        删除不可见的控制字符
        删除表情符号（😊🎉 等）
        规范化 Unicode（全角转半角等）
        合并多余的空格和换行

        【步骤2：长度过滤】
        如果清理后的文字长度 < 5 个字符：
            跳过（太短没有意义）
        如果清理后的文字长度 > 1000 个字符：
            跳过（太长可能是广告或爬取错误）

        【步骤3：语言过滤】
        数一数文字中汉字的数量
        如果汉字数量 < 2：
            跳过（不是中文评论，无法用中文情感模型分析）

        【步骤4：去重】
        计算"平台 + 文字内容"的 MD5 指纹
        如果这个指纹已经出现过（seen 集合中已有）：
            跳过（重复评论）
        否则：
            把指纹加入 seen 集合

        【通过所有过滤】
        把清洗后的文字替换到评论字典中
        加入 cleaned 列表

    打印统计：共处理X条，保留Y条，去重Z条，语言过滤W条

    返回 cleaned
```

---

## 五、情感分析模块伪代码（`pipeline/sentiment.py`）

```
函数 run_sentiment(评论列表, 模型名称, 批次大小=32):

    如果评论列表为空：
        直接返回空列表

    【加载模型】
    从 HuggingFace 下载并加载 BERT 情感分析模型
    （首次运行需要联网下载，约 400MB，之后会缓存）

    【提取文本】
    从每条评论中取出 content 字段，组成文本列表

    【批量推理】
    把文本列表按批次（默认32条一批）喂给模型
    模型返回每条文本的：
        - 原始标签（如 "LABEL_1" 或 "positive"）
        - 置信度分数（0~1 的小数，越接近1越确定）

    【标签映射】
    对每条预测结果：
        如果置信度 < 0.70：
            情感标签 = "neutral"（模型不确定，归为中性）
        否则如果原始标签含有"正面/好评/positive"等字样：
            情感标签 = "positive"（正面评价）
        否则如果原始标签含有"负面/差评/negative"等字样：
            情感标签 = "negative"（负面评价）
        否则：
            情感标签 = "neutral"（中性）

    【合并结果】
    把 sentiment_label 和 sentiment_score 加入原评论字典

    打印统计：正面X条、负面Y条、中性Z条

    返回带情感标签的评论列表
```

---

## 六、各平台爬虫差异对比

| 平台 | 需要登录？ | 主要接口类型 | 特殊注意 |
|------|-----------|------------|--------|
| 小红书 | 必须（XHS_COOKIE） | REST API（需要签名） | Cookie 每天过期，签名算法可能变化 |
| 京东 | 可选（JD_COOKIE） | HTML 搜索 + REST 评论 API | 先搜索商品ID，再抓评论 |
| B站 | 可选（BILI_SESSDATA） | REST API（公开可访问） | 匿名也能用，加 SESSDATA 提升上限 |
| 知乎 | 可选（ZHIHU_COOKIE） | REST API（半公开） | 无 Cookie 时自动降速，避免被封 |

---

## 七、数据流向图（完整版）

```
configs/keywords.txt          configs/platforms.yaml
       │                              │
       │ 读取关键词                    │ 读取平台参数
       └──────────────┬───────────────┘
                      │
                      ▼
             scripts/run_all.py
                      │
          ┌───────────┼───────────┬──────────┐
          ▼           ▼           ▼          ▼
     crawler/    crawler/    crawler/   crawler/
      xhs.py      jd.py    bilibili.py  zhihu.py
          │           │           │          │
          └───────────┴───────────┴──────────┘
                      │
                      │ 原始评论 (JSON)
                      ▼
              data/raw/raw_*.json
                      │
                      ▼
          pipeline/cleaning.py
                      │
                      │ 清洗后评论 (JSON)
                      ▼
            data/clean/clean_*.json
                      │
                      ▼
          pipeline/sentiment.py
          （BERT 模型推理）
                      │
                      │ 带情感标签的评论
                      ▼
       data/output/sentiment_results.csv
       data/output/summary.json
       data/output/summary.csv
                      │
                      ▼
                logs/app.log
```
