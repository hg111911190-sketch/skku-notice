# -*- coding: utf-8 -*-
"""인턴 공고를 모아 내 조건(jobs_rules.py)에 맞는 것을 골라 사이트·캘린더·알림으로 내보낸다.

소스: 링커리어(본문 텍스트), 자소설닷컴 채용 달력(본문이 이미지라 OCR), 학교·학과 공지(docs/notices.json).
결과: docs/jobs.json · docs/jobs.js (사이트), docs/jobs.ics (캘린더 구독), cache/jobs_cache.json (상세·알림 기록)
알림: MAIL_USER(Gmail 주소) + MAIL_APP_PASSWORD(앱 비밀번호) 환경변수가 있으면 Gmail 로 보낸다. 받는 주소는 MAIL_TO(없으면 MAIL_USER).

표준 라이브러리만 쓴다. OCR 은 tesseract(kor) 가 있을 때만 한다 (GitHub Actions 에서는 설치한다).
"""
import html
import io
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

import jobs_rules as R

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "jobs.json"
ICS = ROOT / "docs" / "jobs.ics"
NOTICES = ROOT / "docs" / "notices.json"
CACHE = ROOT / "cache" / "jobs_cache.json"
UA = "Mozilla/5.0 (compatible; skku-notice intern radar)"
MAX_DETAILS = 150   # 한 번에 새로 읽을 상세 페이지 수 (첫 실행이 너무 길어지지 않게)
MAX_OCR = 40        # 한 번에 새로 OCR 할 공고 수
REMIND_DAYS = 3     # 조건 충족 공고는 마감 며칠 전에 한 번 더 알린다

LK_API = "https://api.linkareer.com/graphql"
LK_HEADERS = {"Origin": "https://linkareer.com", "Referer": "https://linkareer.com/"}
LK_LIST = ("query($f:ActivityFilter,$o:ActivityOrder,$p:Pagination){activities(filterBy:$f,orderBy:$o,pagination:$p)"
           "{nodes{id title organizationName recruitStartAt recruitCloseAt categories{name} distinctInternTypes{name} homepageURL}}}")
LK_DETAIL = "query($id:ID!){activity(id:$id){detailText{text}}}"
JSS_CAL = "https://jasoseol.com/employment/calendar_list.json"

SOURCES = {"linkareer": "링커리어", "jasoseol": "자소설닷컴", "school": "학교 공지"}
ID_PREFIX = {"linkareer": "lk", "jasoseol": "jss", "school": "school"}
STATUS_ORDER = {"ok": 0, "check": 1, "no": 2}


def request(url, data=None, headers=None, binary=False, tries=3):
    h = {"User-Agent": UA, **(headers or {})}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                return raw if binary else raw.decode("utf-8", errors="replace")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3)


def strip_html(s):
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t\u00a0]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def ms_to_date(ms):
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%Y-%m-%d") if ms else ""


def warn(msg):
    print(f"[warn] {msg}", file=sys.stderr)


# ── 링커리어 ─────────────────────────────────────────────────────────
def linkareer_list():
    nodes = []
    for page in range(1, 21):
        variables = {"f": {"activityTypeID": "5", "jobTypes": ["INTERN"], "status": "OPEN"},
                     "o": {"direction": "DESC", "field": "RECENT"}, "p": {"page": page, "pageSize": 100}}
        d = json.loads(request(LK_API, {"query": LK_LIST, "variables": variables}, LK_HEADERS))
        if d.get("errors"):
            raise RuntimeError(d["errors"][0].get("message"))
        got = d["data"]["activities"]["nodes"]
        nodes += got
        if len(got) < 100:
            return nodes
        time.sleep(1)
    return nodes


def linkareer_detail(activity_id):
    d = json.loads(request(LK_API, {"query": LK_DETAIL, "variables": {"id": activity_id}}, LK_HEADERS))
    raw = (((d.get("data") or {}).get("activity") or {}).get("detailText") or {}).get("text") or ""
    return {"text": strip_html(raw)[:8000], "imgs": re.findall(r'<img[^>]+src="([^"]+)"', raw)[:3]}


def collect_linkareer(ctx):
    out = []
    for a in linkareer_list():
        company, title = a.get("organizationName") or "", a.get("title") or ""
        end = ms_to_date(a.get("recruitCloseAt"))
        if (end and end < ctx.today_s) or R.title_excluded(title):
            continue
        cats = [c["name"] for c in a.get("categories") or []]
        group = R.auto_group(company)
        jobs = R.job_matches(R.strip_company(title, company), categories=cats)
        if not group and not jobs:
            continue
        key = f"lk-{a['id']}"
        d = ctx.detail(key, lambda: linkareer_detail(a["id"]))
        text, basis = (d or {}).get("text") or "", "본문"
        if d is not None and len(text) < 80 and d.get("imgs"):  # 본문이 이미지뿐인 공고
            ocr = ctx.ocr(d)
            if ocr:
                text, basis = text + "\n" + ocr, "OCR"
        out.append(ctx.item(
            id=key, source="linkareer", company=company, title=title,
            url=f"https://linkareer.com/activity/{a['id']}", apply_url=a.get("homepageURL") or "",
            start=ms_to_date(a.get("recruitStartAt")), end=end, fields=cats, auto=group, jobs=jobs,
            intern_type=", ".join(t["name"] for t in a.get("distinctInternTypes") or [] if t["name"] != "기타"),
            text=text if d is not None else None, basis=basis,
            no_text_reason="공고가 이미지라 자격 미확인 (OCR 대기)",
        ))
    return out


# ── 자소설닷컴 ───────────────────────────────────────────────────────
def jasoseol_detail(eid):
    page = request(f"https://jasoseol.com/recruit/{eid}")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    ec = json.loads(m.group(1))["props"]["pageProps"]["initialEmploymentCompany"] if m else {}
    emps = ec.get("employments") or []
    fields = [e["field"] for e in emps if e.get("division") == 3 and e.get("field")] or \
             [e["field"] for e in emps if e.get("field")]
    content = ec.get("content") or ""
    return {
        "fields": fields[:30],
        "apply_url": ec.get("employment_page_url") or "",
        "imgs": re.findall(r'<img[^>]+src="([^"]+)"', content)[:3],
        "text": strip_html(content)[:8000],
    }


def collect_jasoseol(ctx):
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {"start_time": iso(ctx.now - timedelta(days=30)), "end_time": iso(ctx.now + timedelta(days=90))}
    data = json.loads(request(JSS_CAL, body))
    out, seen = [], set()
    for e in data.get("employment", []):
        title, company = e.get("title") or "", e.get("name") or ""
        divisions = {s.get("division") for s in e.get("employments") or []}
        end = (e.get("end_time") or "")[:10]
        if (e["id"] in seen or (3 not in divisions and not R.INTERN_TITLE_RE.search(title))
                or (end and end < ctx.today_s) or R.title_excluded(title)):
            continue
        seen.add(e["id"])
        group = R.auto_group(company) or R.auto_group((e.get("company_group") or {}).get("name"))
        key = f"jss-{e['id']}"
        d = ctx.detail(key, lambda: jasoseol_detail(e["id"]))
        fields = d["fields"] if d else []
        jobs = R.job_matches(R.strip_company(title, company), *fields)
        if not group and not jobs:
            continue
        text, basis = (d or {}).get("text") or "", "본문"
        if d is not None and not text.strip():
            text, basis = ctx.ocr(d), "OCR"
        out.append(ctx.item(
            id=key, source="jasoseol", company=company, title=title, url=f"https://jasoseol.com/recruit/{e['id']}",
            apply_url=(d or {}).get("apply_url", ""), start=(e.get("start_time") or "")[:10], end=end,
            fields=fields, auto=group, jobs=jobs, intern_type="", text=text if d is not None else None, basis=basis,
            no_text_reason="공고가 이미지라 자격 미확인 (OCR 대기)",
        ))
    return out


def ocr_tool():
    exe = shutil.which("tesseract")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return exe if "kor" in (r.stdout + r.stderr).split() else None


def ocr_images(exe, urls):
    try:
        from PIL import Image
    except ImportError:
        Image = None
    texts = []
    for url in urls:
        raw = request(url, binary=True)
        with tempfile.TemporaryDirectory() as td:
            paths = []
            if Image:  # 흑백 + 확대 + 긴 포스터는 나눠서 읽는다
                im = Image.open(io.BytesIO(raw)).convert("L")
                if im.width < 1400:
                    im = im.resize((1400, int(im.height * 1400 / im.width)))
                for k, y in enumerate(range(0, im.height, 5000)):
                    p = Path(td) / f"{k}.png"
                    im.crop((0, max(0, y - 80), im.width, min(im.height, y + 5000))).save(p)
                    paths.append(p)
            else:
                p = Path(td) / ("in" + (Path(url.split("?")[0]).suffix or ".png"))
                p.write_bytes(raw)
                paths.append(p)
            for p in paths:
                r = subprocess.run([exe, str(p), "stdout", "-l", "kor+eng"], capture_output=True, timeout=300)
                texts.append(r.stdout.decode("utf-8", errors="replace"))
    return "\n".join(texts)


# ── 학교·학과 공지 (scrape.py 결과 재사용) ───────────────────────────
def school_text(url):
    page = request(url)
    i = max(page.find("board-view-content-wrap"), page.find("board-write-box"))
    if i < 0:
        return strip_html(page)[:8000]
    seg = page[i:i + 30000]
    for stop in ("board-view-file", "board-txt-navi", "boardView_prev"):
        j = seg.find(stop)
        if j > 0:
            seg = seg[:j]
    return strip_html("<" + seg)[:8000]


def school_deadline(title, posted):
    """제목의 '(~11/29)', '8/9(일)까지' 에서 마감일을 뽑는다."""
    m = (re.findall(r"~\s*(\d{1,2})[./](\d{1,2})", title)
         or re.findall(r"(\d{1,2})[./](\d{1,2})\s*(?:\([^)]{1,3}\))?\s*까지", title))
    if not m or not posted:
        return ""
    mo, dd = map(int, m[-1])
    y = int(posted[:4]) + ((mo, dd) < (int(posted[5:7]), int(posted[8:10])))
    try:
        return date(y, mo, dd).isoformat()
    except ValueError:
        return ""


def collect_school(ctx):
    if not NOTICES.exists():
        return []
    data = json.loads(NOTICES.read_text(encoding="utf-8"))
    boards = {s["id"]: s["name"] for s in data.get("sources", [])}
    cutoff = (ctx.now - timedelta(days=45)).strftime("%Y-%m-%d")
    out, seen = [], set()
    for n in data.get("items", []):
        title = n.get("title") or ""
        if (n.get("date") or "") < cutoff or not R.INTERN_TITLE_RE.search(title) or R.title_excluded(title):
            continue
        dedupe = re.sub(r"\W", "", title)
        if dedupe in seen:  # 여러 게시판에 같은 글
            continue
        seen.add(dedupe)
        company = (re.match(r"\s*\[([^\]]+)\]", title) or [None, ""])[1]
        group = R.auto_group(company)
        jobs = R.job_matches(R.strip_company(title, company))
        if not group and not jobs and "현장실습" not in title:
            continue
        end = school_deadline(title, n.get("date"))
        if end and end < ctx.today_s:
            continue
        key = f"school-{n['id']}"
        d = ctx.detail(key, lambda: {"text": school_text(n["url"])})
        out.append(ctx.item(
            id=key, source="school", company=company or boards.get(n["source"], "학교"), title=title,
            url=n["url"], apply_url="", start=n.get("date") or "", end=end, fields=[], auto=group, jobs=jobs,
            intern_type=boards.get(n["source"], ""), text=d.get("text") if d else None, basis="본문",
        ))
    return out


# ── 실행 상태 (캐시·판정) ────────────────────────────────────────────
class Context:
    def __init__(self, now, cache, prev_items, first_run):
        self.now, self.today, self.today_s = now, now.date(), now.strftime("%Y-%m-%d")
        self.cache, self.prev = cache, prev_items
        # 첫 실행은 한 번에 다 읽는다 (나눠 읽으면 다음 실행에 '확인 필요→충족' 알림이 몰린다)
        self.detail_budget = 10 ** 6 if first_run else MAX_DETAILS
        self.ocr_budget = 10 ** 6 if first_run else MAX_OCR
        self.ocr_exe = ocr_tool()

    def detail(self, key, fetch):
        d = self.cache["details"].get(key)
        if d is None and self.detail_budget > 0:
            self.detail_budget -= 1
            try:
                d = self.cache["details"][key] = fetch()
            except Exception as e:
                warn(f"{key} 상세 실패: {e}")
            time.sleep(0.7)
        return d

    def ocr(self, d):
        if "ocr" in d:
            return d["ocr"]
        if not self.ocr_exe or self.ocr_budget <= 0 or not d.get("imgs"):
            return ""
        self.ocr_budget -= 1
        try:
            d["ocr"] = ocr_images(self.ocr_exe, d["imgs"])[:8000]
        except Exception as e:
            warn(f"OCR 실패: {e}")
            return ""
        return d["ocr"]

    def item(self, text, basis, no_text_reason="지원 자격 정보 없음", **it):
        if text is None:
            c = {"status": "check", "reason": "상세 페이지 아직 안 읽음 (다음 실행에서 확인)", "evidence": ""}
            basis = ""
        else:
            c = R.classify(text, it["title"], self.today)
            if len(text.strip()) < 80:  # 본문이 사실상 없음 (이미지 공고)
                basis = "제목" if c["evidence"] == "" else basis
                if c["reason"] == "지원 자격 정보 없음":
                    c["reason"] = no_text_reason
        prev = self.prev.get(it["id"], {})
        return {**it, **c, "basis": basis, "source_name": SOURCES[it["source"]],
                "first_seen": prev.get("first_seen") or self.now.strftime("%Y-%m-%d %H:%M"), "also": []}


def merge_duplicates(items):
    """링커리어·자소설에 같이 올라온 공고(같은 회사·같은 마감일)는 하나로 합친다."""
    by_key, out = {}, []
    for it in sorted(items, key=lambda x: x["source"] != "linkareer"):
        key = (R.norm_company(it["company"]), it["end"]) if it["end"] and it["source"] != "school" else None
        base = by_key.get(key)
        if base is None:
            if key:
                by_key[key] = it
            out.append(it)
            continue
        base["also"].append({"name": it["source_name"], "url": it["url"]})
        if base["basis"] in ("", "제목") and it["basis"] not in ("", "제목"):
            base.update({k: it[k] for k in ("status", "reason", "evidence", "basis")})
        base["fields"] = base["fields"] or it["fields"]
    return out


# ── 내보내기 ─────────────────────────────────────────────────────────
def d_day(end, today):
    if not end:
        return ""
    n = (date.fromisoformat(end) - today).days
    return "D-day" if n == 0 else f"D-{n}"


def ics_text(items, now):
    def esc(s):
        return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def fold(line):  # 75 바이트마다 줄을 접는다 (한글이 잘리지 않게)
        out, cur = [], ""
        for ch in line:
            if len((cur + ch).encode("utf-8")) > 74:
                out.append(cur)
                cur = " "
            cur += ch
        return "\r\n".join(out + [cur])

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//skku-notice//intern radar//KO", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:인턴 공고 마감", "X-WR-TIMEZONE:Asia/Seoul"]
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for it in items:
        if it["status"] == "no" or not it["end"]:
            continue
        d = date.fromisoformat(it["end"])
        summary = "[마감] " + ("" if it["status"] == "ok" else "(확인) ") + it["company"] + " - " + it["title"]
        lines += ["BEGIN:VEVENT", f"UID:{it['id']}@skku-notice", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                  "SUMMARY:" + esc(summary), "DESCRIPTION:" + esc(it["reason"] + "\n" + it["url"]),
                  "URL:" + it["url"], "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


# ── 알림 ─────────────────────────────────────────────────────────────
def site_url():
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/jobs.html"
    return ""


def describe(it, today):
    tag = it["auto"] or ", ".join(it["jobs"][:3])
    end = f"마감 {it['end'][5:].replace('-', '/')} ({d_day(it['end'], today)})" if it["end"] else "마감 미기재"
    meta = " · ".join(x for x in (tag, end, it["reason"]) if x)
    return f"• {it['company']} — {it['title']}\n  {meta}\n  {it['url']}"


def mail_ready():
    return bool(os.environ.get("MAIL_USER") and os.environ.get("MAIL_APP_PASSWORD"))


def send(subject, body):
    env = os.environ
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"] = subject, env["MAIL_USER"]
    msg["To"] = env.get("MAIL_TO") or env["MAIL_USER"]
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        # 앱 비밀번호는 'abcd efgh ijkl mnop' 처럼 띄어 보여 주므로 공백을 지운다
        s.login(env["MAIL_USER"], env["MAIL_APP_PASSWORD"].replace(" ", ""))
        s.send_message(msg)


def notify(items, cache, today):
    """새 공고(조건 충족·확인 필요)와 마감 임박 공고를 알린다. 보낸 것은 cache 에 기록한다."""
    live = [it for it in items if it["status"] != "no"]
    fresh = [it for it in live if it["id"] not in cache["notified"]]
    upgraded = [it for it in live if cache["notified"].get(it["id"]) == "check" and it["status"] == "ok"]
    soon = [it for it in live if it["status"] == "ok" and it["end"] and it["id"] not in cache["reminded"]
            and 0 <= (date.fromisoformat(it["end"]) - today).days <= REMIND_DAYS]
    url = site_url()

    def remember():
        for it in live:
            cache["notified"][it["id"]] = it["status"]
        for it in soon:
            cache["reminded"][it["id"]] = today.isoformat()

    def deliver(subject, body):  # 실패하면 기록하지 않아 다음 실행에서 다시 보낸다
        try:
            send(subject, body)
        except Exception as e:
            warn(f"알림 전송 실패: {e}")
            return False
        remember()
        return True

    if not mail_ready():
        print(f"(메일 설정 없음: 새 공고 {len(fresh)}건, 마감 임박 {len(soon)}건은 사이트에서 확인)")
        remember()
        return
    if not cache.get("announced"):  # 처음 연결됐을 때는 목록 대신 요약만
        ok = [it for it in live if it["status"] == "ok"]
        body = (f"인턴 공고 알림이 연결됐습니다.\n현재 조건 충족 {len(ok)}건, 확인 필요 {len(live) - len(ok)}건."
                + ("\n\n" + "\n\n".join(describe(it, today) for it in ok[:10]) if ok else "")
                + (f"\n\n전체 목록: {url}" if url else ""))
        cache["announced"] = deliver("[인턴 알림] 연결 완료", body)
        return

    parts, listed = [], {it["id"] for it in fresh + upgraded}
    for label, group in (("✅ 조건 충족", [it for it in fresh if it["status"] == "ok"] + upgraded),
                         ("❔ 확인 필요", [it for it in fresh if it["status"] == "check"]),
                         (f"⏰ 마감 {REMIND_DAYS}일 이내", [it for it in soon if it["id"] not in listed])):
        if group:
            parts.append(label + "\n\n" + "\n\n".join(describe(it, today) for it in group))
    if not parts:
        return
    n = len(fresh) + len(upgraded)
    deliver(f"[인턴 알림] 새 공고 {n}건" if n else "[인턴 알림] 마감 임박",
            (f"🔔 인턴 공고 새로 {n}건\n\n" if n else "") + "\n\n".join(parts) + (f"\n\n전체 목록: {url}" if url else ""))


# ── main ─────────────────────────────────────────────────────────────
def main():
    now = datetime.now(KST)
    first_run = not CACHE.exists()
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if not first_run else {}
    for k in ("details", "notified", "reminded"):
        cache.setdefault(k, {})
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    prev_items = {it["id"]: it for it in prev.get("items", [])}
    ctx = Context(now, cache, prev_items, first_run)
    print(f"OCR: {'사용 (' + ctx.ocr_exe + ')' if ctx.ocr_exe else '없음 — 자소설 이미지 공고는 확인 필요로 표시'}")

    items, sources, failed = [], [], set()
    for sid, collect in (("linkareer", collect_linkareer), ("jasoseol", collect_jasoseol), ("school", collect_school)):
        try:
            got, ok = collect(ctx), True
        except Exception as e:  # 한 곳이 죽어도 나머지는 갱신
            warn(f"{sid}: {e}")
            got, ok = [it for it in prev_items.values() if it["source"] == sid], False
            failed.add(sid)
        print(f"{sid}: {len(got)}건" + ("" if ok else " (이전 데이터 유지)"))
        items += got
        sources.append({"id": sid, "name": SOURCES[sid], "ok": ok})

    items = merge_duplicates(items)
    items.sort(key=lambda it: (STATUS_ORDER[it["status"]], it["end"] or "9999", it["company"]))
    counts = {s: sum(it["status"] == s for it in items) for s in STATUS_ORDER}
    print(f"조건 충족 {counts['ok']} · 확인 필요 {counts['check']} · 불일치 {counts['no']}")

    notify(items, cache, ctx.today)

    # 목록에서 사라진(마감·삭제) 공고의 기록은 지운다. 실패한 소스의 기록은 남긴다.
    alive = {it["id"] for it in items}
    alive_prefixes = {ID_PREFIX[s] for s in failed}
    for k in ("details", "notified", "reminded"):
        cache[k] = {i: v for i, v in cache[k].items() if i in alive or i.split("-", 1)[0] in alive_prefixes}

    data = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "profile": {"grad": f"{R.GRAD[0]}년 {R.GRAD[1]}월", "grade": R.grade_on(ctx.today),
                    "semesters_done": R.semesters_done(ctx.today)},
        "ocr": bool(ctx.ocr_exe),
        "sources": sources,
        "items": items,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.with_suffix(".js").write_text("window.JOBS = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    ICS.write_bytes(ics_text(items, now).encode("utf-8"))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
