# -*- coding: utf-8 -*-
"""성균관대 공지 게시판 4곳을 긁어서 docs/notices.json 으로 저장한다.

표준 라이브러리만 사용하므로 별도 설치 없이 `python scrape.py` 로 실행된다.
"""
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

SOURCES = [
    {"id": "skku", "name": "학교 공지", "url": "https://www.skku.edu/skku/campus/skk_comm/notice01.do"},
    {"id": "ice", "name": "정보통신대학", "url": "https://ice.skku.edu/ice/notice.do"},
    {"id": "eee", "name": "전자전기공학부", "url": "https://eee.skku.edu/eee/notice.do"},
    {"id": "futurecar", "name": "미래자동차", "url": "https://swb.skku.edu/futurecar/notice.do"},
]
PAGES = 3          # 게시판당 가져올 페이지 수
PAGE_SIZE = 10     # 페이지당 글 수 (학교 공지는 10개 넘게 요청해도 10개만 준다)
KST = timezone(timedelta(hours=9))
OUT = Path(__file__).parent / "docs" / "notices.json"

ITEM_RE = re.compile(r'<dl class="board-list-content-wrap[^"]*">(.*?)</dl>', re.S)
LINK_RE = re.compile(r'<a href="(\?mode=view&amp;articleNo=(\d+)[^"]*)"[^>]*>(.*?)</a>', re.S)
CATEGORY_RE = re.compile(r'<span class="c-board-list-category">(.*?)</span>', re.S)
INFO_RE = re.compile(r'<dd class="board-list-content-info">\s*<ul>(.*?)</ul>', re.S)
LI_RE = re.compile(r'<li[^>]*>(.*?)</li>', re.S)
TAG_RE = re.compile(r'<[^>]+>')


def text(s):
    return re.sub(r'\s+', ' ', html.unescape(TAG_RE.sub('', s))).strip()


def fetch(url, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (skku-notice aggregator)"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3)


def parse(page_html, source):
    items = []
    for block in ITEM_RE.findall(page_html):
        link = LINK_RE.search(block)
        if not link:
            continue
        href, article_no, title = link.groups()
        cat = CATEGORY_RE.search(block)
        info = INFO_RE.search(block)
        cells = [text(c) for c in LI_RE.findall(info.group(1))] if info else []
        date = next((c for c in cells if re.fullmatch(r'\d{4}-\d{2}-\d{2}', c)), "")
        views = next((re.sub(r'\D', '', c) for c in cells if c.startswith("조회수")), "")
        dept = cells[1] if len(cells) > 1 else ""
        items.append({
            "source": source["id"],
            "id": f'{source["id"]}-{article_no}',
            "title": text(title),
            "url": source["url"] + "?mode=view&articleNo=" + article_no,
            "category": text(cat.group(1)).strip("[]") if cat else "",
            "dept": dept,
            "date": date,
            "views": int(views) if views else None,
            "pinned": "board-list-content-top" in block,
        })
    return items


def scrape_source(source):
    seen, items = set(), []
    for page in range(PAGES):
        url = f'{source["url"]}?mode=list&articleLimit={PAGE_SIZE}&article.offset={page * PAGE_SIZE}'
        for it in parse(fetch(url), source):
            if it["id"] not in seen:
                seen.add(it["id"])
                items.append(it)
        time.sleep(0.5)
    return items


def main():
    prev_items = json.loads(OUT.read_text(encoding="utf-8")).get("items", []) if OUT.exists() else []

    all_items, sources = [], []
    for src in SOURCES:
        try:
            items = scrape_source(src)
            ok = True
        except Exception as e:  # 한 곳이 죽어도 나머지는 갱신
            print(f'[warn] {src["id"]}: {e}', file=sys.stderr)
            items, ok = [], False
        if not ok:
            items = [it for it in prev_items if it["source"] == src["id"]]
        print(f'{src["id"]}: {len(items)}개' + ("" if ok else " (이전 데이터 유지)"))
        all_items += items
        sources.append({"id": src["id"], "name": src["name"], "url": src["url"], "ok": ok})

    all_items.sort(key=lambda x: x["date"], reverse=True)
    data = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "sources": sources,
        "items": all_items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    # 로컬에서 index.html 을 파일로 열 때도 읽히도록 스크립트 형태로도 저장
    OUT.with_suffix(".js").write_text("window.NOTICES = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")


if __name__ == "__main__":
    main()
