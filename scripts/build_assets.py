#!/usr/bin/env python3
"""生成主页里所有带动态数据的资源。

按公开的 GitHub API 重写：

    assets/masthead-{light,dark}.svg     刊头（含各项目的仓库数与星数）
    assets/stats-{light,dark}.svg        数字卡片
    README.md                            <!-- SELECTED:START --> 与 <!-- SELECTED:END --> 之间

assets/setup-{light,dark}.svg 没有动态数据，是手写的，这里刻意不动它。

只用标准库，ubuntu-latest 上不需要 pip install。本地跑：
    GITHUB_TOKEN=xxx python scripts/build_assets.py
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
USER = os.environ.get("STATS_USER", "hxh230802")

# 他的组织成员身份是私有的，/users/{user}/orgs 返回空数组，所以组织只能显式列出来。
ORGS = ["DSH-PackForge", "KnotLink-Protocol"]

TOKEN = os.environ.get("GITHUB_TOKEN", "")
ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 版式常量
SANS = "Helvetica Neue, Segoe UI, Arial, sans-serif"
SERIF = "Palatino Linotype, Palatino, Book Antiqua, Georgia, serif"
SONGTI = "Songti SC, Noto Serif CJK SC, SimSun, serif"

LIGHT = {"ground": "#F4F2EC", "ink": "#2A2A28", "sec": "#7C7B76",
         "rule": "#D9D6CD", "accent": "#C7322E"}
DARK = {"ground": "#1B1A18", "ink": "#EDEAE2", "sec": "#928E86",
        "rule": "#35322D", "accent": "#D9564F"}

KICKER = "TSINGHUA UNIVERSITY · BEIJING"
DEK_EN = "Protocols and developer tooling, built in the open."
DEK_CN = "在清华读本科，自己搭协议与开发者工具。"

# 封面条目。数字部分由 API 填充，文案是手写的。
FEATURED = [
    {
        "role": "整合包生态",
        "name": "DSH-PackForge",
        "url": "https://github.com/DSH-PackForge",
        "org": "DSH-PackForge",
        "dek": "DeepSeek Harness 的整合包与插件生态。",
        "meta": "{repos} 个仓库 · 旗舰 {top_stars}★ · MIT / CC0",
        "readme_meta": "组织 · {repos} 个仓库",
        "links": 4,
    },
    {
        "role": "通信协议",
        "name": "KnotLink-Protocol",
        "url": "https://github.com/KnotLink-Protocol",
        "org": "KnotLink-Protocol",
        "dek": "一套让程序之间互相通信的协议。",
        "meta": "{repos} 个仓库 · 核心 {top_stars}★ · SDK {sdk_stars}★（C++）",
        "readme_meta": "组织 · {repos} 个仓库",
        "links": 4,
        "sdk_repo": "KnotLinkSDK",
    },
    {
        "role": "桌面工具",
        "name": "PyToEXE",
        "url": f"https://github.com/{USER}/PyToEXE",
        "repo": "PyToEXE",
        "dek": "一个可以把 Python 文件转换成 exe 程序的工具。",
        "meta": "{stars}★ · Python · 最后更新 {year}",
        "readme_meta": "仓库 · {stars}★ · Python · {year}",
        "note": "个人账号里星数最多的仓库；{year} 年之后没有再更新。",
    },
]

SELECTED_START = "<!-- SELECTED:START -->"
SELECTED_END = "<!-- SELECTED:END -->"


# ---------------------------------------------------------------- 取数
def _get(url: str, attempts: int = 3):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "hxh230802-profile-assets")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")

    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            # 4xx 重试没有意义；5xx 和 429（限流）值得再试，
            # 否则一次抖动就让这个定时任务整整空转一天。
            if exc.code < 500 and exc.code != 429:
                raise SystemExit(
                    f"GitHub API {exc.code} for {url}: {exc.read()[:200]!r}"
                ) from exc
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        if attempt < attempts - 1:
            time.sleep(2 ** attempt)
    raise SystemExit(f"GitHub API unreachable for {url}: {last!r}")


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


def collect() -> dict:
    user = _get(f"{API}/users/{USER}")
    own = [r for r in _all_pages(f"{API}/users/{USER}/repos?type=owner") if not r.get("fork")]

    orgs: dict = {}
    all_repos = list(own)
    org_stars = 0
    for org in ORGS:
        info = _get(f"{API}/orgs/{org}")
        repos = _all_pages(f"{API}/orgs/{org}/repos?type=public")
        # fork 不算他的作品，星数统计里排除；仓库总数以 API 的 public_repos 为准。
        kept = [r for r in repos if not r.get("fork")]
        all_repos.extend(kept)
        ranked = _by_stars(kept)
        org_stars += sum(int(r.get("stargazers_count") or 0) for r in kept)
        orgs[org] = {
            "repos": int(info.get("public_repos") or len(repos)),
            "top_stars": int(ranked[0].get("stargazers_count") or 0) if ranked else 0,
            "by_name": {r["name"]: r for r in repos},
            "top": [{"name": r["name"], "stars": int(r.get("stargazers_count") or 0)}
                    for r in ranked if int(r.get("stargazers_count") or 0) > 0],
        }

    own_by_name = {r["name"]: r for r in own}

    counts: dict = {}
    for repo in all_repos:
        lang = repo.get("language")
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    langs = [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]

    return {
        "user": user,
        "own": own,
        "own_by_name": own_by_name,
        "orgs": orgs,
        "own_stars": sum(int(r.get("stargazers_count") or 0) for r in own),
        "org_stars": org_stars,
        "langs": langs,
        "date": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
    }


def _entry_values(entry: dict, data: dict) -> dict:
    """把一条 FEATURED 里 meta 模板需要的数字算出来。"""
    values: dict = {}
    if "org" in entry:
        org = data["orgs"][entry["org"]]
        values["repos"] = org["repos"]
        values["top_stars"] = org["top_stars"]
        sdk = entry.get("sdk_repo")
        if sdk:
            repo = org["by_name"].get(sdk)
            values["sdk_stars"] = int(repo.get("stargazers_count") or 0) if repo else 0
    else:
        repo = data["own_by_name"].get(entry["repo"], {})
        values["stars"] = int(repo.get("stargazers_count") or 0)
        pushed = (repo.get("pushed_at") or "")[:4]
        values["year"] = pushed or "—"
    return values


def _summary(data: dict) -> dict:
    own_repo_count = int(data["user"].get("public_repos") or len(data["own"]))
    org_repo_count = sum(v["repos"] for v in data["orgs"].values())
    return {
        "repos": own_repo_count + org_repo_count,
        "own_repos": own_repo_count,
        "org_repos": org_repo_count,
        "stars": data["own_stars"] + data["org_stars"],
        "own_stars": data["own_stars"],
        "org_stars": data["org_stars"],
        "orgs": len(data["orgs"]),
        "followers": int(data["user"].get("followers") or 0),
        "langs": " · ".join(data["langs"]),
        "date": data["date"],
    }


# ---------------------------------------------------------------- 渲染
def render_masthead(data: dict, p: dict, suffix: str = "") -> str:
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="420" '
        f'viewBox="0 0 1200 420" role="img" aria-labelledby="mastheadTitle{suffix}">',
        f'  <title id="mastheadTitle{suffix}">HXH — 清华大学 · 北京</title>',
        f'  <rect width="1200" height="420" fill="{p["ground"]}"/>',
        f'  <text x="64" y="78" font-family="{SANS}" font-size="13" font-weight="600" '
        f'letter-spacing="3.2" fill="{p["accent"]}">{_esc(KICKER)}</text>',
        f'  <line x1="64" y1="96" x2="1136" y2="96" stroke="{p["rule"]}" stroke-width="1"/>',
        f'  <line x1="664" y1="96" x2="664" y2="392" stroke="{p["rule"]}" stroke-width="1"/>',
        f'  <text x="48" y="246" font-family="{SERIF}" font-size="190" letter-spacing="-3" '
        f'fill="{p["ink"]}">HXH</text>',
        f'  <text x="64" y="306" font-family="{SERIF}" font-size="21" font-style="italic" '
        f'fill="{p["sec"]}">{_esc(DEK_EN)}</text>',
        f'  <text x="64" y="338" font-family="{SONGTI}" font-size="19" '
        f'fill="{p["sec"]}">{_esc(DEK_CN)}</text>',
        f'  <line x1="64" y1="366" x2="124" y2="366" stroke="{p["accent"]}" stroke-width="2"/>',
    ]

    for i, entry in enumerate(FEATURED):
        top = 128 + i * 92
        meta = entry["meta"].format(**_entry_values(entry, data))
        lines += [
            f'  <text x="704" y="{top}" font-family="{SANS}" font-size="11" font-weight="600" '
            f'letter-spacing="2.4" fill="{p["accent"]}">{i + 1:02d} — {_esc(entry["role"])}</text>',
            f'  <text x="704" y="{top + 38}" font-family="{SERIF}" font-size="28" '
            f'fill="{p["ink"]}">{_esc(entry["name"])}</text>',
            f'  <text x="704" y="{top + 62}" font-family="{SANS}" font-size="13" '
            f'fill="{p["sec"]}">{_esc(meta)}</text>',
        ]
        if i < len(FEATURED) - 1:
            y = top + 78
            lines.append(
                f'  <line x1="704" y1="{y}" x2="1136" y2="{y}" stroke="{p["rule"]}" stroke-width="1"/>'
            )

    lines += ["</svg>", ""]
    return "\n".join(lines)


def render_stats(data: dict, p: dict, suffix: str = "") -> str:
    d = _summary(data)
    col_x, sep_x = [64, 330, 596, 862], [306, 572, 838]

    # 组织名直接从 ORGS 推，不要再手写一遍 —— 不然改了 ORGS 这里会悄悄写错。
    org_names = " · ".join(ORGS)
    # 这一格右边紧挨着 x=838 的分隔线，名字太长会压线，超了就退回数量。
    if len(org_names) > 34:
        org_names = f"{len(ORGS)} 个组织"

    metrics = [
        ("公开仓库", f"{d['repos']}", f"个人 {d['own_repos']} · 组织 {d['org_repos']}"),
        ("星标总数", f"{d['stars']}", f"个人 {d['own_stars']} · 组织 {d['org_stars']}"),
        ("组织", f"{d['orgs']}", org_names),
        ("关注者", f"{d['followers']}", ""),
    ]

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="260" '
        f'viewBox="0 0 1200 260" role="img" aria-labelledby="statsTitle{suffix}">',
        f'  <title id="statsTitle{suffix}">公开仓库 {d["repos"]} · 星标总数 {d["stars"]} · '
        f'组织 {d["orgs"]} · 关注者 {d["followers"]}</title>',
        f'  <rect width="1200" height="260" fill="{p["ground"]}"/>',
        f'  <text x="64" y="50" font-family="{SANS}" font-size="11" font-weight="600" '
        f'letter-spacing="2.6" fill="{p["accent"]}">数字 · NUMBERS</text>',
        f'  <text x="1136" y="50" text-anchor="end" font-family="{SANS}" font-size="11" '
        f'letter-spacing="1.4" fill="{p["sec"]}">更新 · {_esc(d["date"])}</text>',
        f'  <line x1="64" y1="66" x2="1136" y2="66" stroke="{p["rule"]}" stroke-width="1"/>',
    ]

    for i, (label, value, sub) in enumerate(metrics):
        x = col_x[i]
        if i:
            lines.append(
                f'  <line x1="{sep_x[i - 1]}" y1="84" x2="{sep_x[i - 1]}" y2="192" '
                f'stroke="{p["rule"]}" stroke-width="1"/>'
            )
        lines.append(
            f'  <text x="{x}" y="100" font-family="{SANS}" font-size="11" '
            f'letter-spacing="2.2" fill="{p["sec"]}">{_esc(label)}</text>'
        )
        lines.append(
            f'  <text x="{x}" y="156" font-family="{SANS}" font-size="46" '
            f'font-weight="500" fill="{p["ink"]}">{_esc(value)}</text>'
        )
        if sub:
            lines.append(
                f'  <text x="{x}" y="180" font-family="{SANS}" font-size="12" '
                f'fill="{p["sec"]}">{_esc(sub)}</text>'
            )

    lines += [
        f'  <line x1="64" y1="208" x2="1136" y2="208" stroke="{p["rule"]}" stroke-width="1"/>',
        f'  <text x="64" y="236" font-family="{SANS}" font-size="11" letter-spacing="2.2" '
        f'fill="{p["sec"]}">常用语言</text>',
        f'  <text x="180" y="236" font-family="{SANS}" font-size="13.5" '
        f'fill="{p["ink"]}">{_esc(d["langs"])}</text>',
        "</svg>",
        "",
    ]
    return "\n".join(lines)


def render_selected(data: dict) -> str:
    blocks = []
    for i, entry in enumerate(FEATURED, start=1):
        values = _entry_values(entry, data)
        head = (f"**{i:02d} — [{entry['name']}]({entry['url']})** · "
                f"{entry['readme_meta'].format(**values)}")

        tail = ""
        if "org" in entry:
            org = data["orgs"][entry["org"]]
            # 只列至少 2★ 的仓库，免得 1★ 的也堆上来变成流水账。
            top = [r for r in org["top"] if r["stars"] >= 2][: entry.get("links", 4)]
            tail = " · ".join(
                f"[{r['name']}](https://github.com/{entry['org']}/{r['name']}) {r['stars']}★"
                for r in top
            )
        elif entry.get("note"):
            tail = entry["note"].format(**values)

        block = [head, "", f"*{entry['dek']}*"]
        if tail:
            block += ["", tail]
        blocks.append("\n".join(block))

    own_repo_count = int(data["user"].get("public_repos") or len(data["own"]))
    blocks.append(
        f"个人账号下另有 {max(own_repo_count - 1, 0)} 个公开仓库 —— "
        f"[全部仓库 →](https://github.com/{USER}?tab=repositories)"
    )
    return "\n\n".join(blocks)


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
    if SELECTED_START not in text or SELECTED_END not in text:
        print(f"README.md is missing {SELECTED_START} / {SELECTED_END}; skipping")
        return
    body = render_selected(data)
    pattern = re.compile(
        re.escape(SELECTED_START) + r".*?" + re.escape(SELECTED_END), re.DOTALL
    )
    updated = pattern.sub(f"{SELECTED_START}\n{body}\n{SELECTED_END}", text)
    if updated != text:
        path.write_text(updated, encoding="utf-8", newline="\n")
        print("wrote README.md")
    else:
        print("README.md unchanged")


def main() -> None:
    data = collect()
    print(json.dumps(_summary(data), ensure_ascii=False, indent=2))

    for name, palette in (("light", LIGHT), ("dark", DARK)):
        # 两份文件的 <title id> 不能重复，万一以后被内联进同一份文档就会撞。
        suffix = "" if name == "light" else "Dark"
        _write(ROOT / "assets" / f"masthead-{name}.svg",
               render_masthead(data, palette, suffix))
        _write(ROOT / "assets" / f"stats-{name}.svg",
               render_stats(data, palette, suffix))

    _write_readme(data)


if __name__ == "__main__":
    main()
