# Audio × Video AI Radar

[![Daily Audio AI Radar](https://github.com/hkkky81-cpu/audio-tech-radar/actions/workflows/daily-radar.yml/badge.svg)](https://github.com/hkkky81-cpu/audio-tech-radar/actions/workflows/daily-radar.yml)

在线页面：<https://hkkky81-cpu.github.io/audio-tech-radar/>

一个可直接部署到 GitHub Pages 的音视频 AI 技术与创意玩法情报站。每天自动抓取并整理：

- 最新论文：arXiv 的语音/音频组与视频/多媒体组分别抓取，避免 `cs.CV` 的体量挤掉音频条目
- GitHub 项目：音频/音乐生成、视频生成、数字人、口型、编辑、跨模态创作与安全评测
- 产品与玩法：厂商博客、Product Hunt、Google News、Hacker News / Show HN
- 中文提炼：可选接入 OpenAI，生成技术中文标题、准确摘要、定位关键词与可验证的创意玩法

页面支持按内容类型、技术方向筛选和全文搜索，同时保留每日 Markdown 报告与 JSON 数据，便于二次分析。首页还提供：

- **本期精选**：在论文、GitHub 与产品/玩法中各选高价值条目，优先呈现；
- **方向热度**：自动统计本期最活跃的音视频技术方向；
- **多维排序**：支持综合推荐、最新发布、GitHub Stars 与最近收录；
- **研究身份信息**：论文显示作者，开源项目显示项目方，产品显示公司/来源，并自动标注模型、数据集、基准、工具等资源类型；
- **资源入口与收藏**：直接进入 Paper、Code 或产品原文，并可在浏览器本地收藏。

## 最终效果

GitHub Pages 首页：`https://<你的用户名>.github.io/audio-tech-radar/`

每日更新后的仓库结构：

```text
docs/index.html              # 最新一期可视化首页
docs/data/latest.json        # 最新结构化数据
docs/data/YYYY-MM-DD.json    # 历史结构化数据
docs/data/history.json       # 跨日期去重后的累计历史库
reports/YYYY-MM-DD.md        # 每日 Markdown 简报
config/topics.yml            # 方向、关键词、抓取源与阈值
```

## 更新机制

`.github/workflows/daily-radar.yml` 在首次推送及代码/配置变更时执行，并于每天 23:30 UTC 自动执行，对应次日北京时间 07:30、韩国时间 08:30。报告日期使用项目时区计算，不会再出现本地已到第二天、页面仍显示前一天的问题。流水线会：

1. 抓取各数据源，单个源失败不会中断整份报告；
2. 标题高权重、摘要低权重地匹配音频、视频与跨模态受控标签；
3. 按时效性、相关性、Stars 和项目新鲜度综合评分；
4. URL/标题去重，生成本期精选、方向热度、当日网页、Markdown 与 JSON；
5. 将本期条目增量合并到累计历史库，保留首次收录和最近出现日期；
6. 复用上一期翻译缓存，避免为未变化条目重复调用模型；
7. 自动提交当日报告并部署 GitHub Pages。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m audio_radar
```

离线验证完整链路：

```bash
python -m audio_radar --demo
python -m unittest discover -s tests -v
```

## GitHub Pages 首次设置

仓库创建后进入 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。然后在 **Actions** 中手动运行一次 `Daily Audio AI Radar`；之后将按计划每日执行。

建议将仓库设为 public，GitHub Free 即可直接使用 Pages。采集使用仓库自带的 `GITHUB_TOKEN`，不需要额外创建 Personal Access Token。

## 启用高质量中文摘要

页面在没有模型密钥时也能正常更新，并使用本地受控标签与规则生成创意玩法。若要启用技术翻译和摘要：

1. 打开仓库 **Settings → Secrets and variables → Actions**；
2. 点击 **New repository secret**；
3. 名称填写 `OPENAI_API_KEY`，值填写你的 OpenAI API Key；
4. 到 **Actions** 手动运行一次工作流。

密钥只放在 GitHub Actions Secret 中，不要写入代码或发在聊天里。默认模型是 `gpt-5.6-luna`，适合每日批量处理；可通过工作流中的 `ENRICHMENT_MODEL` 调整。模型输出受 JSON Schema 约束，并要求保留技术名、模型名、数据集名和公司名，避免“翻译得很顺但技术含义变了”。

## 调整调研范围

编辑 `config/topics.yml`：

- `lookback_hours`：默认 72 小时，仅控制每次向外部数据源抓取的时间范围，不会删除历史内容；
- `keywords`：每个技术方向的匹配词；标题命中权重高于摘要命中；
- `product_min_topic_score`：产品源的最低相关度阈值；
- `github_sources.min_stars`：GitHub 最低 Stars；
- `max_items_per_section`：每类最多展示数量；
- `feeds` / `news_queries` / `hacker_news_queries`：产品、新闻与独立创意项目来源；
- `enrichment`：翻译模型、批大小和每日最多处理条数。

## 摘要与关键词策略

- 先用受控关键词筛选和分类，避免让模型决定“收不收”；
- 再用模型做忠实技术翻译、3–6 个定位关键词和一句可执行玩法；
- 未配置密钥、接口超时或单批失败时自动降级，不影响日报发布；
- 用条目 ID 与内容指纹缓存结果，只有内容变化时才重新处理。

## 注意事项

- “最新”按抓取时间窗口判断，不等于质量结论；重要条目仍需阅读原文。
- Google News 条目可能存在转载，系统会按规范化标题和 URL 去重。
- GitHub Search API 有速率限制；Action 内置 Token 能显著提升可用额度。
- 厂商 RSS 地址若变更，只会影响该来源，错误会记录在当日报告中。
