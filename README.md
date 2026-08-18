# Audio AI Radar

[![Daily Audio AI Radar](https://github.com/hkkky81-cpu/audio-tech-radar/actions/workflows/daily-radar.yml/badge.svg)](https://github.com/hkkky81-cpu/audio-tech-radar/actions/workflows/daily-radar.yml)

在线页面：<https://hkkky81-cpu.github.io/audio-tech-radar/>

一个可直接部署到 GitHub Pages 的音频技术情报站。每天自动抓取并整理：

- 最新论文：arXiv 的 `cs.SD`、`eess.AS`、`cs.CL`
- GitHub 项目：TTS、VC、ASR、音频生成、音乐生成、分离、Deepfake 检测等
- 产品动态：音频 AI 厂商博客、技术博客与 Google News RSS

页面支持按内容类型、技术方向筛选和全文搜索，同时保留每日 Markdown 报告与 JSON 数据，便于二次分析。

## 最终效果

GitHub Pages 首页：`https://<你的用户名>.github.io/audio-tech-radar/`

每日更新后的仓库结构：

```text
docs/index.html              # 最新一期可视化首页
docs/data/latest.json        # 最新结构化数据
docs/data/YYYY-MM-DD.json    # 历史结构化数据
reports/YYYY-MM-DD.md        # 每日 Markdown 简报
config/topics.yml            # 方向、关键词、抓取源与阈值
```

## 更新机制

`.github/workflows/daily-radar.yml` 在首次推送及代码/配置变更时执行，并于每天 00:30 UTC 自动执行，对应北京时间 08:30、韩国时间 09:30。流水线会：

1. 抓取各数据源，单个源失败不会中断整份报告；
2. 依据关键词过滤并映射到 7 个音频技术方向；
3. 按时效性、相关性、Stars 和项目新鲜度综合评分；
4. URL/标题去重，生成网页、Markdown 与 JSON；
5. 自动提交当日报告并部署 GitHub Pages。

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

建议将仓库设为 public，GitHub Free 即可直接使用 Pages。工作流使用仓库自带的 `GITHUB_TOKEN`，不需要额外创建 Personal Access Token。

## 调整调研范围

编辑 `config/topics.yml`：

- `lookback_hours`：默认 72 小时，避免周末或源延迟导致漏项；
- `keywords`：每个技术方向的匹配词；
- `github_sources.min_stars`：GitHub 最低 Stars；
- `max_items_per_section`：每类最多展示数量；
- `feeds` / `news_queries`：产品与新闻来源。

## 当前筛选策略

本项目优先保证“可解释、无需额外密钥、持续可运行”。中文的“关注理由”由规则生成；论文摘要保留原文，以避免机器翻译造成技术误差。后续如需要高质量中文摘要，可以在现有 JSON 生成前加入任意 LLM 总结步骤，并把密钥放入 GitHub Actions Secrets，切勿写入仓库。

## 注意事项

- “最新”按抓取时间窗口判断，不等于质量结论；重要条目仍需阅读原文。
- Google News 条目可能存在转载，系统会按规范化标题和 URL 去重。
- GitHub Search API 有速率限制；Action 内置 Token 能显著提升可用额度。
- 厂商 RSS 地址若变更，只会影响该来源，错误会记录在当日报告中。
