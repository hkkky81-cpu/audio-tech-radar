from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus

import yaml

try:  # Kept optional so the offline demo and tests work before dependency install.
    import feedparser
    import requests
except ImportError:  # pragma: no cover - exercised only in minimal local runtimes
    feedparser = None
    requests = None


USER_AGENT = "audio-tech-radar/0.1 (+https://github.com/)"


@dataclass
class Item:
    kind: str
    title: str
    url: str
    summary: str
    source: str
    published_at: str
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    why_cn: str = ""
    item_id: str = ""

    def finalize(self) -> "Item":
        self.title = clean_text(self.title)
        self.summary = clean_text(self.summary)
        self.item_id = hashlib.sha1(self.url.encode("utf-8")).hexdigest()[:12]
        return self


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                dt = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def request(session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(url, headers=headers, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"request failed: {url}: {last_error}")


def topic_catalog(config: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, str]]:
    keywords = {key: [word.lower() for word in value["keywords"]] for key, value in config["topics"].items()}
    labels = {key: value["label"] for key, value in config["topics"].items()}
    return keywords, labels


def match_topics(text: str, catalog: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    return [topic for topic, words in catalog.items() if any(word in lowered for word in words)]


def fetch_arxiv(config: dict[str, Any], session: requests.Session) -> list[Item]:
    settings = config["paper_sources"]
    categories = " OR ".join(f"cat:{category}" for category in settings["arxiv_categories"])
    url = (
        "https://export.arxiv.org/api/query?"
        f"search_query={quote_plus('(' + categories + ')')}&start=0&"
        f"max_results={int(settings['max_results'])}&sortBy=submittedDate&sortOrder=descending"
    )
    root = ET.fromstring(request(session, url).content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items: list[Item] = []
    for entry in root.findall("a:entry", ns):
        title = entry.findtext("a:title", default="", namespaces=ns)
        summary = entry.findtext("a:summary", default="", namespaces=ns)
        published = entry.findtext("a:published", default="", namespaces=ns)
        authors = [node.findtext("a:name", default="", namespaces=ns) for node in entry.findall("a:author", ns)]
        link = ""
        for node in entry.findall("a:link", ns):
            if node.attrib.get("rel") == "alternate":
                link = node.attrib.get("href", "")
                break
        if not link:
            link = entry.findtext("a:id", default="", namespaces=ns)
        items.append(Item("paper", title, link, summary, "arXiv", iso(parse_dt(published)), authors).finalize())
    return items


def fetch_github(config: dict[str, Any], session: requests.Session, cutoff: datetime) -> list[Item]:
    settings = config["github_sources"]
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    collected: dict[str, Item] = {}
    since = (cutoff - timedelta(days=21)).date().isoformat()
    for base_query in settings["queries"]:
        query = f"{base_query} stars:>={int(settings['min_stars'])} pushed:>={since} archived:false fork:false"
        params = {"q": query, "sort": "updated", "order": "desc", "per_page": int(settings["max_results_per_query"])}
        try:
            payload = request(session, "https://api.github.com/search/repositories", params=params, headers=headers).json()
        except RuntimeError as exc:
            print(f"warning: GitHub query failed ({base_query}): {exc}", file=sys.stderr)
            continue
        for repo in payload.get("items", []):
            description = repo.get("description") or ""
            topics = repo.get("topics") or []
            summary = description + (f" Topics: {', '.join(topics)}." if topics else "")
            item = Item(
                "github",
                repo["full_name"],
                repo["html_url"],
                summary,
                "GitHub",
                iso(parse_dt(repo.get("pushed_at") or repo.get("updated_at"))),
                metrics={
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "language": repo.get("language") or "",
                    "created_at": repo.get("created_at") or "",
                },
            ).finalize()
            collected[item.url] = item
    return list(collected.values())


def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


def fetch_feed(name: str, url: str, session: requests.Session) -> list[Item]:
    if feedparser is None:
        raise RuntimeError("feedparser is not installed; run: pip install -r requirements.txt")
    try:
        content = request(session, url).content
    except RuntimeError as exc:
        print(f"warning: feed failed ({name}): {exc}", file=sys.stderr)
        return []
    parsed = feedparser.parse(content)
    items: list[Item] = []
    for entry in parsed.entries[:40]:
        published = entry.get("published") or entry.get("updated") or ""
        summary = entry.get("summary") or entry.get("description") or ""
        summary = re.sub(r"<[^>]+>", " ", summary)
        link = entry.get("link") or ""
        if not link:
            continue
        items.append(Item("product", entry.get("title", ""), link, summary, name, iso(parse_dt(published))).finalize())
    return items


def fetch_products(config: dict[str, Any], session: requests.Session) -> list[Item]:
    settings = config["product_sources"]
    items: list[Item] = []
    for feed in settings.get("feeds", []):
        items.extend(fetch_feed(feed["name"], feed["url"], session))
    for query in settings.get("news_queries", []):
        items.extend(fetch_feed("Google News", google_news_url(query), session))
    return items


def score_item(item: Item, now: datetime, labels: dict[str, str]) -> None:
    age_hours = max(0.0, (now - parse_dt(item.published_at)).total_seconds() / 3600)
    recency = max(0.0, 35.0 - age_hours / 8.0)
    specificity = min(35.0, 12.0 + 8.0 * len(item.tags))
    popularity = 0.0
    if item.kind == "github":
        popularity = min(20.0, 4.5 * math.log10(1 + int(item.metrics.get("stars", 0))))
        created = parse_dt(item.metrics.get("created_at"))
        if (now - created).days <= 90:
            popularity += 8.0
    source_bonus = 8.0 if item.kind == "paper" else 5.0
    item.score = round(recency + specificity + popularity + source_bonus, 1)
    topic_text = "、".join(labels[tag] for tag in item.tags[:3])
    if item.kind == "paper":
        item.why_cn = f"研究方向：{topic_text}。建议重点查看方法创新、数据集与客观/主观评测设置。"
    elif item.kind == "github":
        stars = int(item.metrics.get("stars", 0))
        item.why_cn = f"开源方向：{topic_text}；当前约 {stars:,} Stars，可优先判断许可证、推理显存和 Demo 完整度。"
    else:
        item.why_cn = f"产品方向：{topic_text}。建议关注开放范围、API/定价、实时性与可集成程度。"


def deduplicate(items: Iterable[Item]) -> list[Item]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    output: list[Item] = []
    for item in sorted(items, key=lambda value: (value.score, value.published_at), reverse=True):
        title_key = re.sub(r"[^a-z0-9]+", "", item.title.lower())
        canonical_url = re.sub(r"[?#].*$", "", item.url).rstrip("/")
        if not title_key or canonical_url in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(canonical_url)
        seen_titles.add(title_key)
        output.append(item)
    return output


def process(items: Iterable[Item], config: dict[str, Any], now: datetime) -> list[Item]:
    catalog, labels = topic_catalog(config)
    cutoff = now - timedelta(hours=int(config["project"]["lookback_hours"]))
    selected: list[Item] = []
    for item in items:
        item.tags = match_topics(f"{item.title} {item.summary}", catalog)
        if not item.tags or parse_dt(item.published_at) < cutoff:
            continue
        score_item(item, now, labels)
        selected.append(item)
    return deduplicate(selected)


def demo_items(now: datetime) -> list[Item]:
    samples = [
        Item("paper", "Demo: Controllable Speech Editing with Flow Matching", "https://arxiv.org/abs/demo-audio-radar", "A placeholder paper used to verify the complete report pipeline.", "Demo", iso(now - timedelta(hours=3)), ["Audio Radar"]).finalize(),
        Item("github", "demo/audio-generation-toolkit", "https://github.com/demo/audio-generation-toolkit", "A placeholder audio generation repository for offline validation.", "Demo", iso(now - timedelta(hours=6)), metrics={"stars": 128, "forks": 12, "language": "Python", "created_at": iso(now - timedelta(days=20))}).finalize(),
        Item("product", "Demo: Realtime Voice API Update", "https://example.com/audio-radar-demo", "A placeholder realtime speech API product update.", "Demo", iso(now - timedelta(hours=9))).finalize(),
    ]
    return samples


def short_summary(value: str, limit: int = 360) -> str:
    value = clean_text(value)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def render_markdown(items: list[Item], date_text: str, labels: dict[str, str], errors: list[str]) -> str:
    counts = {kind: sum(item.kind == kind for item in items) for kind in ("paper", "github", "product")}
    lines = [
        f"# Audio AI Radar · {date_text}",
        "",
        f"> 今日收录：论文 {counts['paper']} 篇 · GitHub 项目 {counts['github']} 个 · 产品动态 {counts['product']} 条",
        "",
    ]
    names = {"paper": "最新论文", "github": "GitHub 项目", "product": "产品动态"}
    for kind in ("paper", "github", "product"):
        lines.extend([f"## {names[kind]}", ""])
        section = [item for item in items if item.kind == kind]
        if not section:
            lines.extend(["今日时间窗口内暂无高相关新增。", ""])
            continue
        for index, item in enumerate(section, 1):
            tags = " / ".join(labels[tag] for tag in item.tags)
            metric = ""
            if kind == "github":
                metric = f" · ⭐ {int(item.metrics.get('stars', 0)):,} · {item.metrics.get('language') or '未标注语言'}"
            lines.extend([
                f"### {index}. [{item.title}]({item.url})",
                "",
                f"- **来源/时间**：{item.source} · {item.published_at[:10]}{metric}",
                f"- **方向**：{tags}",
                f"- **关注理由**：{item.why_cn}",
                f"- **摘要**：{short_summary(item.summary)}",
                "",
            ])
    if errors:
        lines.extend(["## 抓取状态", "", *[f"- {error}" for error in errors], ""])
    lines.extend(["---", "", "由 GitHub Actions 每日自动生成。条目按相关性、时效性与开源热度综合排序；建议进入原始链接复核。", ""])
    return "\n".join(lines)


def render_html(items: list[Item], date_text: str, config: dict[str, Any], labels: dict[str, str]) -> str:
    counts = {kind: sum(item.kind == kind for item in items) for kind in ("paper", "github", "product")}
    payload = json.dumps([asdict(item) for item in items], ensure_ascii=False).replace("</", "<\\/")
    topic_options = "".join(f'<option value="{html.escape(key)}">{html.escape(label)}</option>' for key, label in labels.items())
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="每日追踪音频 AI 最新论文、GitHub 项目和产品动态">
  <title>{html.escape(config['project']['title'])}</title>
  <style>
    :root{{--ink:#132238;--muted:#64748b;--line:#dbe4ee;--paper:#f5f7fb;--brand:#1769e0;--teal:#0d9488;--violet:#7c3aed;--card:#fff}}
    *{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 Inter,"PingFang SC","Microsoft YaHei",sans-serif}}
    a{{color:inherit}} .hero{{background:radial-gradient(circle at 75% 15%,#2dd4bf33,transparent 30%),linear-gradient(135deg,#071a35,#123b76 68%,#0f766e);color:#fff;padding:54px 22px 68px}}
    .wrap{{width:min(1160px,calc(100% - 36px));margin:auto}} .eyebrow{{letter-spacing:.14em;text-transform:uppercase;color:#93c5fd;font-weight:700;font-size:12px}}
    h1{{font-size:clamp(32px,6vw,58px);line-height:1.05;margin:10px 0 14px;letter-spacing:-.035em}} .lead{{font-size:18px;color:#dbeafe;max-width:660px;margin:0}}
    .stats{{display:flex;gap:14px;flex-wrap:wrap;margin-top:30px}} .stat{{min-width:134px;background:#ffffff12;border:1px solid #ffffff25;border-radius:16px;padding:12px 16px}}
    .stat b{{display:block;font-size:25px}} .stat span{{color:#bfdbfe;font-size:13px}}
    main{{margin-top:-28px;padding-bottom:64px}} .toolbar{{display:grid;grid-template-columns:1fr 190px;gap:12px;padding:16px;background:#fff;border:1px solid var(--line);box-shadow:0 12px 35px #14213d12;border-radius:18px}}
    input,select{{width:100%;border:1px solid var(--line);border-radius:11px;padding:12px 14px;background:#fff;color:var(--ink);font:inherit;outline:none}} input:focus,select:focus{{border-color:#60a5fa;box-shadow:0 0 0 3px #dbeafe}}
    .tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 14px}} button{{border:1px solid var(--line);background:#fff;padding:9px 15px;border-radius:999px;cursor:pointer;color:#475569;font-weight:700}}
    button.active{{background:var(--ink);border-color:var(--ink);color:#fff}} .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}}
    .card{{background:var(--card);border:1px solid var(--line);border-radius:17px;padding:20px;box-shadow:0 4px 14px #13223808;transition:.18s ease}} .card:hover{{transform:translateY(-2px);box-shadow:0 12px 28px #13223812}}
    .topline{{display:flex;justify-content:space-between;gap:12px;align-items:center}} .type{{font-size:12px;font-weight:800;border-radius:999px;padding:4px 9px;background:#dbeafe;color:#1d4ed8}} .github .type{{background:#ede9fe;color:#6d28d9}} .product .type{{background:#ccfbf1;color:#0f766e}}
    .date{{font-size:12px;color:var(--muted)}} h2{{font-size:18px;line-height:1.4;margin:13px 0 8px}} h2 a{{text-decoration:none}} h2 a:hover{{color:var(--brand)}}
    .summary{{color:#475569;margin:0 0 12px}} .why{{background:#f8fafc;border-left:3px solid #60a5fa;padding:9px 11px;color:#334155;border-radius:5px;margin:12px 0}}
    .tags{{display:flex;gap:6px;flex-wrap:wrap}} .tag{{font-size:12px;background:#eef2f7;color:#475569;border-radius:7px;padding:3px 7px}} .metric{{color:var(--muted);font-size:12px;margin-top:11px}}
    .empty{{grid-column:1/-1;text-align:center;color:var(--muted);padding:46px}} footer{{color:var(--muted);border-top:1px solid var(--line);padding:24px 0 38px;font-size:13px}}
    @media(max-width:760px){{.grid{{grid-template-columns:1fr}}.toolbar{{grid-template-columns:1fr}}.hero{{padding-top:40px}}}}
  </style>
</head>
<body>
  <header class="hero"><div class="wrap"><div class="eyebrow">DAILY INTELLIGENCE · {date_text}</div><h1>Audio AI Radar</h1><p class="lead">{html.escape(config['project']['subtitle'])}</p><div class="stats"><div class="stat"><b>{counts['paper']}</b><span>最新论文</span></div><div class="stat"><b>{counts['github']}</b><span>GitHub 项目</span></div><div class="stat"><b>{counts['product']}</b><span>产品动态</span></div></div></div></header>
  <main class="wrap"><section class="toolbar"><input id="search" placeholder="搜索标题、摘要、来源…"><select id="topic"><option value="all">全部方向</option>{topic_options}</select></section><nav class="tabs"><button class="active" data-kind="all">全部</button><button data-kind="paper">论文</button><button data-kind="github">GitHub</button><button data-kind="product">产品</button></nav><section id="grid" class="grid"></section></main>
  <footer><div class="wrap">每日自动更新 · 综合时效、相关性与开源热度排序 · 请以原始链接为准</div></footer>
  <script>const DATA={payload};const LABELS={json.dumps(labels, ensure_ascii=False)};let kind='all';
  const esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
  function draw(){{const q=document.querySelector('#search').value.trim().toLowerCase(),topic=document.querySelector('#topic').value;const list=DATA.filter(x=>(kind==='all'||x.kind===kind)&&(topic==='all'||x.tags.includes(topic))&&(!q||(x.title+' '+x.summary+' '+x.source).toLowerCase().includes(q)));document.querySelector('#grid').innerHTML=list.length?list.map(x=>`<article class="card ${{x.kind}}"><div class="topline"><span class="type">${{{{paper:'论文',github:'GitHub',product:'产品'}}[x.kind]}}</span><span class="date">${{esc(x.published_at.slice(0,10))}}</span></div><h2><a href="${{esc(x.url)}}" target="_blank" rel="noopener">${{esc(x.title)}}</a></h2><p class="summary">${{esc(x.summary.slice(0,280))}}${{x.summary.length>280?'…':''}}</p><div class="why">${{esc(x.why_cn)}}</div><div class="tags">${{x.tags.map(t=>`<span class="tag">${{esc(LABELS[t])}}</span>`).join('')}}</div>${{x.kind==='github'?`<div class="metric">⭐ ${{Number(x.metrics.stars||0).toLocaleString()}} · ${{esc(x.metrics.language||'未标注语言')}}</div>`:`<div class="metric">${{esc(x.source)}}</div>`}}</article>`).join(''):'<div class="empty">没有符合当前筛选条件的条目</div>'}}
  document.querySelectorAll('button[data-kind]').forEach(b=>b.onclick=()=>{{kind=b.dataset.kind;document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');draw()}});document.querySelector('#search').oninput=draw;document.querySelector('#topic').onchange=draw;draw();</script>
</body></html>'''


def write_outputs(root: Path, items: list[Item], config: dict[str, Any], now: datetime, errors: list[str]) -> None:
    date_text = now.date().isoformat()
    _, labels = topic_catalog(config)
    reports = root / "reports"
    data_dir = root / "docs" / "data"
    reports.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    limit = int(config["project"]["max_items_per_section"])
    trimmed: list[Item] = []
    for kind in ("paper", "github", "product"):
        trimmed.extend([item for item in items if item.kind == kind][:limit])
    trimmed.sort(key=lambda value: value.score, reverse=True)
    data = {"generated_at": iso(now), "date": date_text, "items": [asdict(item) for item in trimmed], "errors": errors}
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    (data_dir / f"{date_text}.json").write_text(text, encoding="utf-8")
    (data_dir / "latest.json").write_text(text, encoding="utf-8")
    (reports / f"{date_text}.md").write_text(render_markdown(trimmed, date_text, labels, errors), encoding="utf-8")
    (root / "docs" / "index.html").write_text(render_html(trimmed, date_text, config, labels), encoding="utf-8")
    (root / "docs" / ".nojekyll").touch()
    archive = sorted(path.stem for path in reports.glob("????-??-??.md"))
    (data_dir / "archive.json").write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(root: Path, config_path: Path, demo: bool = False, now: datetime | None = None) -> list[Item]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    config = load_config(config_path)
    errors: list[str] = []
    raw: list[Item] = []
    if demo:
        raw = demo_items(now)
    else:
        if requests is None:
            raise RuntimeError("requests is not installed; run: pip install -r requirements.txt")
        session = requests.Session()
        cutoff = now - timedelta(hours=int(config["project"]["lookback_hours"]))
        collectors = [
            ("arXiv", lambda: fetch_arxiv(config, session)),
            ("GitHub", lambda: fetch_github(config, session, cutoff)),
            ("产品源", lambda: fetch_products(config, session)),
        ]
        for name, collector in collectors:
            try:
                raw.extend(collector())
            except Exception as exc:  # one failed source must not stop the daily report
                message = f"{name} 抓取失败：{type(exc).__name__}: {exc}"
                errors.append(message)
                print(f"warning: {message}", file=sys.stderr)
    items = process(raw, config, now)
    write_outputs(root, items, config, now, errors)
    print(f"generated {len(items)} items ({sum(x.kind == 'paper' for x in items)} papers, {sum(x.kind == 'github' for x in items)} repos, {sum(x.kind == 'product' for x in items)} products)")
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the daily Audio AI Radar")
    parser.add_argument("--config", default="config/topics.yml")
    parser.add_argument("--demo", action="store_true", help="use offline sample data")
    parser.add_argument("--clean", action="store_true", help="remove generated docs/data and reports first")
    args = parser.parse_args()
    root = Path.cwd()
    if args.clean:
        shutil.rmtree(root / "reports", ignore_errors=True)
        shutil.rmtree(root / "docs" / "data", ignore_errors=True)
    run(root, root / args.config, demo=args.demo)
