#!/usr/bin/env python3
"""生成主页那一整块 SVG 面板，以及 README 里的链接索引。

输出（全部由公开的 GitHub API 推出）：

    assets/panel-{light,dark}.svg   整块面板：刊头（含连续贡献）/ 关于 / 作品选 / 方式 / 数字 / 落款
    README.md                       LINKS:START 与 LINKS:END 之间的链接索引

Markdown 里只留链接 —— SVG 被 GitHub 当成 <img> 载入，图里的 <a> 点不动，
所以可点的东西必须留在 Markdown 里。

只用标准库。本地跑：
    GITHUB_TOKEN=$(gh auth token) python scripts/build_panel.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
USER = os.environ.get("STATS_USER", "hxh230802")

# 组织成员身份是私有的，/users/{user}/orgs 返回空数组，所以组织只能显式列出来。
ORGS = ["DSH-PackForge", "KnotLink-Protocol"]

TOKEN = os.environ.get("GITHUB_TOKEN", "")
ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 版式常量
W = 900
MARGIN = 56
RIGHT = W - MARGIN          # 844
CONTENT = RIGHT - MARGIN    # 788

MID = 450                   # 作品选 / 方式 的竖发丝线
COL2 = 480                  # 第二栏起点
SPLIT = 500                 # 刊头左右分栏的竖发丝线
LEFT_W = 424                # 刊头左栏可用宽度 —— dek 收在这里，不横穿到右栏
COL_R = 560                 # 刊头右栏起点（连续贡献）

SANS = "Helvetica Neue, Segoe UI, Arial, sans-serif"
SERIF = "Palatino Linotype, Palatino, Book Antiqua, Georgia, serif"
SONGTI = "Songti SC, Noto Serif CJK SC, SimSun, serif"

# 底色直接对齐 GitHub 各主题自己的背景（浅色 #FFFFFF / 深色 #0D1117），
# 面板才不会在页面上显出一块灰板。中性冷灰的取色参考 onethu.github.io
# （--bg #ffffff / ink #0f1115 / muted #81858c / 边框 #ebeef2）。
# 强调色仍只保留一支红，别处一律中性。
LIGHT = {"ground": "#FFFFFF", "ink": "#14171A", "sec": "#6E7278",
         "rule": "#E7EAEE", "accent": "#C7322E"}
DARK = {"ground": "#0D1117", "ink": "#E6EDF3", "sec": "#8B949E",
        "rule": "#2A3038", "accent": "#D9564F"}

KICKER = "TSINGHUA UNIVERSITY · BEIJING"
# SVG 不自动折行；英文 dek 一行放不进左栏，只能手动断
DEK_EN_LINES = ["Protocols and developer tooling,", "built in the open."]
DEK_CN = "在清华读本科，自己搭协议与开发者工具。"

SETUP = [
    ("写代码", "DeepSeek Harness · Claude"),
    ("编辑器", "VS Code"),
    ("在学", "物理 · 计算机科学"),
    ("B 站", "技术分享与记录"),
]

FEATURED = [
    {
        "role": "整合包生态",
        "name": "DSH-PackForge",
        "url": "https://github.com/DSH-PackForge",
        "org": "DSH-PackForge",
        "dek": "DeepSeek Harness 的整合包与插件生态。",
        "headline": "{top_stars}★",
        "meta": "{repos} 个仓库 · MIT / CC0",
        "links": 4,
    },
    {
        "role": "通信协议",
        "name": "KnotLink-Protocol",
        "url": "https://github.com/KnotLink-Protocol",
        "org": "KnotLink-Protocol",
        "dek": "一套让程序之间互相通信的协议。",
        "headline": "{top_stars}★",
        "meta": "{repos} 个仓库 · SDK {sdk_stars}★（C++）",
        "links": 4,
        "sdk_repo": "KnotLinkSDK",
    },
    {
        "role": "桌面工具",
        "name": "PyToEXE",
        "url": f"https://github.com/{USER}/PyToEXE",
        "repo": "PyToEXE",
        "dek": "一个可以把 Python 文件转换成 exe 程序的工具。",
        "headline": "{stars}★",
        "meta": "Python · 最后更新 {year}",
        "links": 0,
    },
]

LINKS_START = "<!-- LINKS:START -->"
LINKS_END = "<!-- LINKS:END -->"

# 动效。参考 github-readme-streak-stats 的两段关键帧：
# 当前连续那个数字由小弹入（streak-pop），其余元素错时上浮（streak-rise）。
#
# 关键纪律：基础样式必须自带可见性，动画只负责「加动作」。
# 早先这里用 opacity: 0 + fill-mode: both，结果任何不跑 CSS 动画的渲染器
# （或只是截图截早了）都会让整栏文字彻底消失 —— 内容不能依赖动画才可见。
# 所以这里动画只改 transform（缩放 / 位移），任何一项失效，元素都仍然看得见。
PANEL_STYLE = """
    @keyframes streak-pop  { 0% { transform: scale(.3) }
                             76% { transform: scale(1.12) }
                             100% { transform: scale(1) } }
    @keyframes streak-rise { from { transform: translateY(7px) }
                             to   { transform: translateY(0) } }
    @keyframes flame-pulse { 0%, 100% { opacity: .55; transform: scale(1) }
                             50% { opacity: 1; transform: scale(1.07) } }
    .sf { animation: streak-rise .55s cubic-bezier(.22,.61,.36,1) both }
    .sp { transform-box: fill-box; transform-origin: 100% 62%;
          animation: streak-pop .6s cubic-bezier(.22,.61,.36,1) both }
    .fl { transform-box: fill-box; transform-origin: 50% 90%;
          animation: flame-pulse 2.6s ease-in-out infinite }
    .d1 { animation-delay: .10s }  .d2 { animation-delay: .22s }
    .d3 { animation-delay: .34s }
    @media (prefers-reduced-motion: reduce) { .sf, .sp, .fl { animation: none } }
"""

# streak-stats 的火苗轮廓，原坐标系约 -8..8 × 0..22
FLAME = ("M 1.5 0.67 C 1.5 0.67 2.24 3.32 2.24 5.47 C 2.24 7.53 0.89 9.2 -1.17 9.2 "
         "C -3.23 9.2 -4.79 7.53 -4.79 5.47 L -4.76 5.11 C -6.78 7.51 -8 10.62 -8 13.99 "
         "C -8 18.41 -4.42 22 0 22 C 4.42 22 8 18.41 8 13.99 C 8 8.6 5.41 3.79 1.5 0.67 Z "
         "M -0.29 19 C -2.07 19 -3.51 17.6 -3.51 15.86 C -3.51 14.24 -2.46 13.1 -0.7 12.74 "
         "C 1.07 12.38 2.9 11.53 3.92 10.16 C 4.31 11.45 4.51 12.81 4.51 14.2 "
         "C 4.51 16.85 2.36 19 -0.29 19 Z")


# ---------------------------------------------------------------- 取数
def _request(req, attempts: int = 3):
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            # 4xx 重试没有意义；5xx 与 429（限流）值得再试，
            # 否则一次抖动就让这个定时任务整整空转一天。
            if exc.code < 500 and exc.code != 429:
                raise SystemExit(
                    f"API {exc.code} for {req.full_url}: {exc.read()[:200]!r}"
                ) from exc
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        if attempt < attempts - 1:
            time.sleep(2 ** attempt)
    raise SystemExit(f"API unreachable for {req.full_url}: {last!r}")


def _get(url: str):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "hxh230802-profile-panel")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    return _request(req)


def _graphql(query: str, variables: dict):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(GRAPHQL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "hxh230802-profile-panel")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    data = _request(req)
    if "errors" in data:
        raise SystemExit(f"GraphQL errors: {data['errors']}")
    return data["data"]


def _all_pages(url: str) -> list:
    items: list = []
    page = 1
    sep = "&" if "?" in url else "?"
    while True:
        batch = _get(f"{url}{sep}per_page=100&page={page}")
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return items


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _by_stars(repos: list) -> list:
    return sorted(repos, key=lambda r: (-int(r.get("stargazers_count") or 0), r["name"]))


CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def collect_streak() -> dict:
    """近一年的贡献总数与连续天数。

    contributionsCollection 单次最多覆盖一年，所以这里就取近一年 ——
    正好对上 GitHub 自己主页那句 "contributions in the last year"。

    这是硬依赖：拿不到就让整次运行失败，绝不静默降级。
    否则某天 GraphQL 权限一变，Action 会生成一张没有连续贡献的面板并提交上去，
    把已经做好的那一块悄悄删掉 —— 失败要吵，不要安静。
    """
    if not TOKEN:
        raise SystemExit("GITHUB_TOKEN is required for the streak block")

    to = dt.datetime.now(dt.timezone.utc)
    frm = to - dt.timedelta(days=365)
    data = _graphql(CONTRIB_QUERY, {
        "login": USER,
        "from": frm.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": to.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    user = (data or {}).get("user")
    if not user:
        raise SystemExit(f"streak: no such user {USER}")
    cal = user["contributionsCollection"]["contributionCalendar"]

    days: list = []
    for week in cal["weeks"]:
        for day in week["contributionDays"]:
            days.append((day["date"], int(day["contributionCount"])))
    days.sort()

    longest = run = 0
    best_from = best_to = run_from = None
    for date, n in days:
        if n > 0:
            if run == 0:
                run_from = date
            run += 1
            if run > longest:
                longest, best_from, best_to = run, run_from, date
        else:
            run = 0

    # 当前连续：从最后一天往回数；今天还没提交就从昨天算起（和 GitHub 口径一致）
    idx = len(days) - 1
    if idx >= 0 and days[idx][1] == 0:
        idx -= 1
    current = 0
    cur_from = None
    while idx >= 0 and days[idx][1] > 0:
        current += 1
        cur_from = days[idx][0]
        idx -= 1

    return {
        "total": int(cal["totalContributions"]),
        "current": current,
        "current_from": cur_from,
        "longest": longest,
        "longest_from": best_from,
        "longest_to": best_to,
    }


def collect() -> dict:
    user = _get(f"{API}/users/{USER}")
    own = [r for r in _all_pages(f"{API}/users/{USER}/repos?type=owner") if not r.get("fork")]

    orgs: dict = {}
    all_repos = list(own)
    org_stars = 0
    for org in ORGS:
        info = _get(f"{API}/orgs/{org}")
        repos = _all_pages(f"{API}/orgs/{org}/repos?type=public")
        # fork 不算他的作品，星数与语言统计里排除；仓库总数以 API 的 public_repos 为准。
        kept = [r for r in repos if not r.get("fork")]
        all_repos.extend(kept)
        ranked = _by_stars(kept)
        org_stars += sum(int(r.get("stargazers_count") or 0) for r in kept)
        orgs[org] = {
            # 组织显示名：KnotLink-Protocol 这个 login 的 name 字段就是 "KnotLink"，
            # 取不到再退回 login。不要手写名单，否则改了 ORGS 会悄悄对不上。
            "name": info.get("name") or org,
            "repos": int(info.get("public_repos") or len(repos)),
            "top_stars": int(ranked[0].get("stargazers_count") or 0) if ranked else 0,
            "by_name": {r["name"]: r for r in repos},
            "top": [{"name": r["name"], "stars": int(r.get("stargazers_count") or 0)}
                    for r in ranked if int(r.get("stargazers_count") or 0) > 0],
        }

    counts: dict = {}
    for repo in all_repos:
        lang = repo.get("language")
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    langs = [n for n, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]

    own_repo_count = int(user.get("public_repos") or len(own))
    return {
        "user": user,
        "own": own,
        "own_by_name": {r["name"]: r for r in own},
        "orgs": orgs,
        "own_repos": own_repo_count,
        "org_repos": sum(v["repos"] for v in orgs.values()),
        "own_stars": sum(int(r.get("stargazers_count") or 0) for r in own),
        "org_stars": org_stars,
        "followers": int(user.get("followers") or 0),
        "langs": langs,
        "streak": collect_streak(),
        "date": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
    }


def _values(entry: dict, data: dict) -> dict:
    v: dict = {}
    if "org" in entry:
        org = data["orgs"][entry["org"]]
        v["repos"] = org["repos"]
        v["top_stars"] = org["top_stars"]
        sdk = entry.get("sdk_repo")
        if sdk:
            repo = org["by_name"].get(sdk)
            v["sdk_stars"] = int(repo.get("stargazers_count") or 0) if repo else 0
    else:
        repo = data["own_by_name"].get(entry["repo"], {})
        v["stars"] = int(repo.get("stargazers_count") or 0)
        v["year"] = (repo.get("pushed_at") or "")[:4] or "—"
    return v


def _md(date_str: str | None) -> str:
    """2026-09-30 -> 09-30"""
    return date_str[5:] if date_str else ""


# ---------------------------------------------------------------- 版面构建
def _advance(ch: str, latin: float) -> float:
    """估算一个字形的步进宽度（em）。宁可高估，也不要漏报溢出。"""
    if ch == "★":
        return 0.90
    if ch in "—–":
        return 0.90
    if ord(ch) > 0x2E7F:      # CJK、CJK 标点、全角符号
        return 1.00
    if ch in " ·-":
        return 0.30
    if ch in ".,:;!|'\"`()[]/":
        return 0.30
    if ch.isupper():
        # 大写明显更宽 —— 字标与缩写（HXH / DSH / SDK / MIT）全靠这条才不被低报
        return max(latin, 0.66)
    return latin


class Panel:
    """按 y 游标往下堆的 SVG 构建器。

    高度由内容算出来，所以不可能溢出画布；
    宽度则逐条检查，越界就记一条 warning。
    """

    def __init__(self, palette: dict, suffix: str):
        self.p = palette
        self.suffix = suffix
        self.body: list = []
        self.y = 0
        self.warnings: list = []
        self.animated = False

    def text(self, x, s, size, fill, *, y=None, family=SANS, weight=None,
             ls=None, italic=False, anchor=None, latin=0.55, cls=None, wrap=None,
             max_w=None):
        yy = self.y if y is None else y
        attrs = [f'x="{x}"', f'y="{yy}"', f'font-family="{family}"',
                 f'font-size="{size}"']
        if weight:
            attrs.append(f'font-weight="{weight}"')
        if italic:
            attrs.append('font-style="italic"')
        if ls:
            attrs.append(f'letter-spacing="{ls}"')
        if anchor:
            attrs.append(f'text-anchor="{anchor}"')
        if cls:
            attrs.append(f'class="{cls}"')
            self.animated = True
        attrs.append(f'fill="{fill}"')

        if anchor is None:
            adv = sum(_advance(c, latin) for c in s) * size
            if ls:
                adv += ls * max(len(s) - 1, 0)
            # 可用宽度默认是「右边界 - 起点」；分栏里的文字再用 max_w 收窄，
            # 不然像 dek 这种会一路横穿到右栏下面去
            available = RIGHT - x
            if max_w is not None:
                available = min(available, max_w)
            if adv > available + 0.5:
                self.warnings.append(
                    f"OVERFLOW [{self.suffix or 'light'}] y={yy} x={x} size={size} "
                    f"needs={adv:.0f} has={available:.0f} end={x + adv:.0f} :: {s}"
                )
        el = f'<text {" ".join(attrs)}>{_esc(s)}</text>'
        if wrap:
            # 外层 g 承担 transform 动画，text 自身保持正常字号 ——
            # 动画不跑时它仍是一个大小正确、读得清的字
            el = f'<g class="{wrap}">{el}</g>'
            self.animated = True
        self.body.append(f'  {el}')

    def flame(self, cx, bottom, scale=0.9, cls="fl"):
        """连续贡献的火苗。外层 g 管放置，内层 g 管 CSS 动画 ——
        如果同一个元素上既有 transform 属性又有 CSS transform，CSS 会把属性覆盖掉。"""
        self.body.append(
            f'  <g transform="translate({cx},{bottom}) scale({scale})">'
            f'<g class="{cls}"><path d="{FLAME}" fill="{self.p["accent"]}"/></g></g>'
        )
        self.animated = True

    def hline(self, y=None, *, x1=MARGIN, x2=RIGHT, sw=1, color=None):
        yy = self.y if y is None else y
        self.body.append(
            f'  <line x1="{x1}" y1="{yy}" x2="{x2}" y2="{yy}" '
            f'stroke="{color or self.p["rule"]}" stroke-width="{sw}"/>'
        )

    def vline(self, x, y1, y2, *, color=None):
        self.body.append(
            f'  <line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" '
            f'stroke="{color or self.p["rule"]}" stroke-width="1"/>'
        )

    def gap(self, dy):
        self.y += dy

    def rule(self, before=44, after=44):
        self.y += before
        self.hline()
        self.y += after

    def section(self, label):
        self.text(MARGIN, label, 22, self.p["accent"], ls=4.0, weight="600")
        self.y += 46

    def svg(self, title: str, desc: str) -> str:
        height = int(self.y + MARGIN)
        head = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
            f'viewBox="0 0 {W} {height}" role="img" '
            f'aria-labelledby="panelTitle{self.suffix} panelDesc{self.suffix}">',
            f'  <title id="panelTitle{self.suffix}">{_esc(title)}</title>',
            f'  <desc id="panelDesc{self.suffix}">{_esc(desc)}</desc>',
        ]
        if self.animated:
            head.append(f'  <style>{PANEL_STYLE}  </style>')
        head.append(f'  <rect width="{W}" height="{height}" fill="{self.p["ground"]}"/>')
        return "\n".join(head + self.body + ["</svg>", ""])


# ---------------------------------------------------------------- 各区块
def block_masthead(p: Panel, data: dict) -> None:
    p.y = 64
    p.text(MARGIN, KICKER, 22, p.p["accent"], ls=4.0, weight="600")
    p.hline(84)
    p.vline(SPLIT, 112, 452)

    # 字标缩到左半边，把右半边让给连续贡献。
    # x=42 让 Palatino 的左边距把字形墨迹落到 x=56 的对齐线上。
    p.text(42, "HXH", 190, p.p["ink"], y=255, family=SERIF, ls=-3, latin=0.72)

    s = data.get("streak")
    if s:
        p.text(COL_R, "贡献 · STREAK", 18, p.p["accent"], y=150, ls=2.6, weight="600",
               cls="sf d1")
        p.hline(166, x1=COL_R)
        rows = [
            ("贡献总数", f"{s['total']}", "近 12 个月", None),
            ("当前连续", f"{s['current']}", f"自 {_md(s['current_from'])}" if s["current"] else "今天还没提交", True),
            ("最长连续", f"{s['longest']}", f"{_md(s['longest_from'])} – {_md(s['longest_to'])}" if s["longest"] else "", None),
        ]
        for i, (label, value, sub, is_current) in enumerate(rows):
            y = 200 + i * 68
            if is_current:
                p.flame(COL_R - 18, y + 2)
            p.text(COL_R, label, 19, p.p["sec"], y=y, cls=f"sf d{i + 1}")
            p.text(RIGHT, value, 38, p.p["ink"], y=y + 6, weight="500", anchor="end",
                   cls=None if is_current else f"sf d{i + 1}",
                   wrap="sp" if is_current else None)
            if sub:
                p.text(COL_R, sub, 14, p.p["sec"], y=y + 22, cls=f"sf d{i + 2}")
            if i < len(rows) - 1:
                p.hline(y + 38, x1=COL_R)

    # dek 收在左栏里（max_w），不再横穿到「贡献」下面
    for i, line in enumerate(DEK_EN_LINES):
        p.text(MARGIN, line, 22, p.p["sec"], y=330 + i * 32,
               family=SERIF, italic=True, latin=0.50, max_w=LEFT_W)
    p.text(MARGIN, DEK_CN, 20, p.p["sec"], y=404, family=SONGTI, max_w=LEFT_W)
    p.hline(432, x1=MARGIN, x2=112, sw=3, color=p.p["accent"])
    p.y = 462


def block_selected(p: Panel, data: dict) -> None:
    p.section("作品选 · SELECTED")
    p.gap(14)
    for i, entry in enumerate(FEATURED, start=1):
        top = p.y
        values = _values(entry, data)

        # 左栏：编号 / 名称 / 一句话
        p.text(MARGIN, f"{i:02d} — {entry['role']}", 20, p.p["accent"],
               y=top + 38, ls=3.0, weight="600")
        p.text(MARGIN, entry["name"], 44, p.p["ink"], y=top + 94, family=SERIF,
               latin=0.50)
        p.text(MARGIN, entry["dek"], 24, p.p["sec"], y=top + 130, family=SERIF,
               italic=True, latin=0.50)

        # 右栏：把数字挂在右边距上，和左栏形成对位 —— 否则整段右边全是空的
        p.text(RIGHT, entry["headline"].format(**values), 44, p.p["ink"],
               y=top + 94, weight="500", anchor="end")
        p.text(RIGHT, entry["meta"].format(**values), 20, p.p["sec"],
               y=top + 130, anchor="end")

        p.y = top + 154
        if i < len(FEATURED):
            p.y += 26
            p.hline()
            p.y += 26


def block_setup(p: Panel) -> None:
    p.section("方式 · SETUP")
    p.gap(14)
    top = p.y
    p.vline(MID, top + 20, top + 224)

    for i, (label, value) in enumerate(SETUP):
        x = MARGIN if i % 2 == 0 else COL2
        y = top + 40 + (i // 2) * 124
        p.text(x, label, 20, p.p["sec"], y=y, ls=3.0)
        p.text(x, value, 26, p.p["ink"], y=y + 44, family=SERIF, latin=0.50)
    p.y = top + 240


def block_numbers(p: Panel, data: dict) -> None:
    p.section("数字 · NUMBERS")
    p.gap(14)

    org_names = " · ".join(v["name"] for v in data["orgs"].values())

    cells = [
        ("公开仓库", f"{data['own_repos'] + data['org_repos']}",
         f"个人 {data['own_repos']} · 组织 {data['org_repos']}"),
        ("星标总数", f"{data['own_stars'] + data['org_stars']}",
         f"个人 {data['own_stars']} · 组织 {data['org_stars']}"),
        ("组织", f"{len(data['orgs'])}", org_names),
        ("关注者", f"{data['followers']}", ""),
    ]

    top = p.y
    p.vline(MID - 4, top + 24, top + 300)
    for idx, (label, value, sub) in enumerate(cells):
        x = MARGIN if idx % 2 == 0 else COL2 - 6
        y = top + 46 + (idx // 2) * 156
        p.text(x, label, 22, p.p["sec"], y=y, ls=3.0)
        p.text(x, value, 64, p.p["ink"], y=y + 68, weight="500")
        if sub:
            p.text(x, sub, 22, p.p["sec"], y=y + 98)
    p.y = top + 300

    p.gap(24)
    p.hline()
    p.gap(44)
    p.text(MARGIN, "常用语言", 22, p.p["sec"], ls=3.0)
    p.text(220, " · ".join(data["langs"]), 24, p.p["ink"])


def block_colophon(p: Panel, data: dict) -> None:
    p.rule(before=44, after=44)
    p.text(MARGIN, "hxh26@tsinghua.edu.cn", 26, p.p["ink"])
    p.text(RIGHT, f"更新 · {data['date']}", 22, p.p["sec"], y=p.y, anchor="end")


# ---------------------------------------------------------------- 组装
def render_panel(data: dict, palette: dict, suffix: str):
    p = Panel(palette, suffix)
    block_masthead(p, data)
    p.rule()
    block_selected(p, data)
    p.rule()
    block_setup(p)
    p.rule()
    block_numbers(p, data)
    block_colophon(p, data)

    names = "、".join(e["name"] for e in FEATURED)
    s = data.get("streak")
    streak_txt = ""
    if s:
        streak_txt = (f"近一年贡献 {s['total']} 次，当前连续 {s['current']} 天，"
                      f"最长连续 {s['longest']} 天。")
    desc = (
        f"{USER} 的主页面板：清华大学在读，方向人工智能。{streak_txt}"
        f"公开仓库 {data['own_repos'] + data['org_repos']} 个，"
        f"星标 {data['own_stars'] + data['org_stars']} 个，"
        f"组织 {len(data['orgs'])} 个，关注者 {data['followers']} 人。"
        f"代表项目：{names}。"
    )
    return p.svg("HXH — 清华大学 · 北京", desc), p.warnings


def render_links(data: dict) -> str:
    rows = []
    for i, entry in enumerate(FEATURED, start=1):
        parts = [f"[{entry['name']}]({entry['url']})"]
        if "org" in entry:
            org = data["orgs"][entry["org"]]
            # 只列至少 2★ 的仓库，免得 1★ 的也堆上来变成流水账。
            for r in [x for x in org["top"] if x["stars"] >= 2][: entry.get("links", 4)]:
                if r["name"] == entry["name"]:
                    continue
                parts.append(
                    f"[{r['name']}](https://github.com/{entry['org']}/{r['name']})"
                )
        rows.append(f"`{i:02d}` " + " · ".join(parts))

    rows.append(f"`00` [{USER} 的全部仓库](https://github.com/{USER}?tab=repositories)")
    rows.append("`联系` **hxh26@tsinghua.edu.cn** · "
                "[Bilibili](https://space.bilibili.com/1396650915) · "
                "[个人博客](https://example.com) · "
                "[知乎](https://example.com) · [X](https://example.com)")
    return "\n\n".join(rows)


# ---------------------------------------------------------------- 落盘
def _write(path: pathlib.Path, svg: str) -> None:
    ET.fromstring(svg)  # 自检：先当 XML 解析一遍，别把转义错误提交进仓库
    path.write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)}")


def _write_readme(data: dict) -> None:
    path = ROOT / "README.md"
    if not path.exists():
        print("README.md not found; skipping")
        return
    text = path.read_text(encoding="utf-8")
    if LINKS_START not in text or LINKS_END not in text:
        print(f"README.md is missing {LINKS_START} / {LINKS_END}; skipping")
        return
    pattern = re.compile(re.escape(LINKS_START) + r".*?" + re.escape(LINKS_END), re.DOTALL)
    updated = pattern.sub(f"{LINKS_START}\n{render_links(data)}\n{LINKS_END}", text)
    if updated != text:
        path.write_text(updated, encoding="utf-8", newline="\n")
        print("wrote README.md")
    else:
        print("README.md unchanged")


def main() -> None:
    data = collect()
    print(json.dumps(
        {"repos": data["own_repos"] + data["org_repos"],
         "stars": data["own_stars"] + data["org_stars"],
         "orgs": len(data["orgs"]), "followers": data["followers"],
         "langs": data["langs"], "streak": data["streak"], "date": data["date"]},
        ensure_ascii=False, indent=2))

    warnings: list = []
    for name, palette in (("light", LIGHT), ("dark", DARK)):
        suffix = "" if name == "light" else "Dark"
        svg, warn = render_panel(data, palette, suffix)
        warnings.extend(warn)
        _write(ROOT / "assets" / f"panel-{name}.svg", svg)

    _write_readme(data)

    if warnings:
        print(f"\n!! {len(warnings)} layout warning(s):")
        for w in warnings:
            print("  " + w)
    else:
        print("\nlayout check: no overflow")


if __name__ == "__main__":
    main()
