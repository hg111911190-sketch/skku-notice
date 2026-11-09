# -*- coding: utf-8 -*-
"""현장실습 시스템(tollgate.skku.edu) 로그인 영역의 실습 기관 목록을 내 PC 에서 읽어 판정·알림한다.

학교 통합로그인은 해외 접속을 막을 수 있고 비밀번호가 필요해서, GitHub Actions 가 아니라
이 PC(한국 IP)에서 실행한다. 비밀번호는 Windows 자격 증명 관리자(keyring)에만 저장한다.

    python tollgate_local.py run          # 수집 → 판정 → 알림 (작업 스케줄러가 3시간마다 실행)
    python tollgate_local.py check        # 결과만 화면에 출력 (GitHub 업로드·알림 없음)
    python tollgate_local.py install      # 작업 스케줄러에 등록 (3시간마다, 놓친 실행은 PC 켜질 때)
    python tollgate_local.py uninstall    # 작업 스케줄러에서 제거
    python tollgate_local.py setup-mail   # 알림 메일용 Gmail 주소·앱 비밀번호 저장 (없으면 Windows 알림)
    python tollgate_local.py probe        # 로그인해서 화면 구조를 저장 (사이트 구조가 바뀌었을 때 확인용)
    python tollgate_local.py forget       # 저장된 아이디·비밀번호 지우기

결과
- docs/tollgate_local.js : 상세 목록. 저장소에 올리지 않는다(.gitignore). docs/jobs.html 을 이 PC 에서 열면 함께 보인다.
- docs/tollgate.js       : 공개 사이트용 요약(곳 수·가장 가까운 마감)만. 매 실행마다 GitHub 에 올린다.
- %USERPROFILE%\\.skku-tollgate : 읽은 상세·알림 기록(cache.json)과 실행 기록(run.log)
"""
import base64
import getpass
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

TG = "https://tollgate.skku.edu"
SSO = "https://login.skku.edu"
SEARCH = TG + "/student/manage/search/index.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
KEYRING_SERVICE = "skku-tollgate"
PROBE_DIR = Path.home() / "tollgate_probe"
ROOT = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".skku-tollgate"
CACHE = STATE_DIR / "cache.json"
LOG = STATE_DIR / "run.log"
LOCAL_JS = ROOT / "docs" / "tollgate_local.js"
SUMMARY_JS = ROOT / "docs" / "tollgate.js"
TASK_NAME = "SKKU 현장실습 확인"
DETAIL_REFRESH_DAYS = 2   # 상세(진행상태·요건)는 이 주기로 다시 읽는다
NO_WINDOW = 0x08000000    # 작업 스케줄러(pythonw)에서 git·PowerShell 창이 번쩍이지 않게
_STDOUT_IS_LOG = False    # pythonw 로 실행돼 print 가 이미 run.log 로 갈 때

SSO_ERRORS = {
    "error-0002": "아이디 또는 비밀번호가 맞지 않습니다.",
    "error-0003": "아이디 또는 비밀번호가 맞지 않습니다.",
    "error-0007": "이미 로그인되어 있습니다.",
    "error-0010": "해외 접속 차단에 걸렸습니다.",
    "error-0011": "로그인 실패 누적으로 계정이 10분간 잠겼습니다.",
    "error-0012": "로그인 실패 누적으로 계정이 10분간 잠겼습니다.",
    "error-0015": "세션이 만료되었습니다.",
    "error-0016": "비밀번호 유효기간이 만료되었습니다. 포털에서 비밀번호를 바꾼 뒤 다시 실행하세요.",
    "error-0031": "휴면 계정입니다. 포털에서 휴면 해제 후 다시 실행하세요.",
    "error-0041": "포털 이용약관 동의가 필요합니다. 브라우저로 한 번 로그인해 동의한 뒤 다시 실행하세요.",
}


class LoginError(Exception):
    pass


class Session:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.last_url = ""

    def open(self, url, data=None, json_body=None, headers=None):
        h = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9", **(headers or {})}
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            h["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if self.last_url:
            h.setdefault("Referer", self.last_url)
        with self.opener.open(urllib.request.Request(url, data=body, headers=h), timeout=45) as r:
            self.last_url = r.geturl()
            return r.read().decode("utf-8", errors="replace")

    def cookie(self, name):
        return next((c.value for c in self.jar if c.name == name), "")

    def set_cookie(self, name, value, domain):
        self.jar.set_cookie(http.cookiejar.Cookie(
            0, name, value, None, False, domain, True, domain.startswith("."), "/", True,
            False, None, False, None, None, {}))


def login(userid, password):
    """통합로그인을 거쳐 현장실습 시스템에 학생으로 로그인한 Session 을 돌려준다. 실패하면 재시도하지 않는다."""
    s = Session()
    s.set_cookie("language", "ko", ".skku.edu")
    s.set_cookie("userGb", "1", "tollgate.skku.edu")
    s.open(TG + "/index.do")
    # 학생 로그인 버튼 = group 1 → 통합로그인 페이지로 넘어간다 (retUrl 은 서버 세션에 기억된다)
    s.open(TG + "/login.do", data={"id": "", "pw": "", "group": "1"})
    if "login.skku.edu" not in s.last_url:
        raise LoginError(f"통합로그인 페이지로 넘어가지 않았습니다: {s.last_url}")
    login_page = s.last_url

    raw = s.open(SSO + "/loginAction", json_body={
        "lang": "ko", "userid": userid, "userpwd": base64.b64encode(password.encode("utf-8")).decode("ascii"),
    }, headers={"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest",
                "Origin": SSO, "Referer": login_page})
    try:
        res = json.loads(raw)
    except ValueError:
        raise LoginError("통합로그인 응답을 읽지 못했습니다 (로그인 방식이 바뀌었을 수 있음).")
    err = res.get("ERROR_KEY") or ""
    if res.get("returnCode") != "success" and not (res.get("ssoReturnCode") == 2 and res.get("returnUrl")):
        raise LoginError(SSO_ERRORS.get(err, f"로그인 실패 (코드: {err or res.get('ssoReturnCode')})"))
    if res.get("ssoReturnCode") == 2:
        print("  참고: 비밀번호 변경 권장 기간이 지났다는 안내가 있습니다 (로그인은 계속).")

    # 로그인 성공 후 브라우저가 하는 일: pToken 을 담아 returnUrl 로 폼 전송
    token = s.cookie("pToken")
    s.open(res["returnUrl"], data={"retPage": "xxx", "uid": "", "pToken": token, "lang": "ko", "tmpToken": token},
           headers={"Origin": SSO, "Referer": login_page})
    if "tollgate.skku.edu" not in s.last_url:
        raise LoginError(f"로그인 후 현장실습 시스템으로 돌아오지 않았습니다: {s.last_url}")
    return s


def credentials(ask_save=True):
    """keyring 에 저장된 아이디·비밀번호. 없으면 직접 입력받고 저장할지 묻는다."""
    import keyring
    userid = keyring.get_password(KEYRING_SERVICE, "userid")
    password = keyring.get_password(KEYRING_SERVICE, userid) if userid else None
    if userid and password:
        return userid, password, False
    userid = input("통합로그인 아이디: ").strip()
    password = getpass.getpass("비밀번호 (입력해도 화면에 안 보입니다): ")
    return userid, password, ask_save


def save_credentials(userid, password):
    import keyring
    keyring.set_password(KEYRING_SERVICE, "userid", userid)
    keyring.set_password(KEYRING_SERVICE, userid, password)


def forget_credentials():
    import keyring
    userid = keyring.get_password(KEYRING_SERVICE, "userid")
    for key in filter(None, ("userid", userid)):
        try:
            keyring.delete_password(KEYRING_SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass


def probe():
    """기관 조회 화면과 그 화면이 쓰는 스크립트를 저장한다 (수집기를 만들기 위한 구조 확인용)."""
    userid, password, new = credentials()
    print("로그인 중...")
    try:
        s = login(userid, password)
    except LoginError as e:
        print(f"로그인 실패: {e}\n(계정 잠금을 피하려고 다시 시도하지 않습니다.)")
        if not new:
            print("저장된 비밀번호가 틀렸다면 `python tollgate_local.py forget` 후 다시 실행하세요.")
        sys.exit(1)
    print("로그인 성공")
    if new and input("다음부터 자동으로 쓰도록 이 PC 의 Windows 자격 증명 관리자에 저장할까요? (y/n): ").strip().lower() == "y":
        save_credentials(userid, password)
        print("저장했습니다.")

    PROBE_DIR.mkdir(exist_ok=True)
    after = s.open(TG + "/index.do")
    (PROBE_DIR / "after_login.html").write_text(after, encoding="utf-8")
    page = s.open(SEARCH)
    (PROBE_DIR / "search_index.html").write_text(page, encoding="utf-8")
    print(f"기관 조회 화면: {s.last_url} ({len(page):,}자)")
    for src in sorted(set(re.findall(r'src="(/common/js/service/[^"]+\.js)[^"]*"', page))):
        try:
            (PROBE_DIR / Path(src).name).write_text(s.open(TG + src), encoding="utf-8")
        except Exception as e:
            print(f"  {src} 저장 실패: {e}")
    # 목록이 화면 안에 바로 있지 않고 따로 불러오는 경우를 위해, 화면의 폼을 기본값으로 한 번 보내 본다
    form = re.search(r'<form[^>]*name="searchForm"[^>]*>(.*?)</form>', page, re.S)
    if form:
        fields = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(1)))
        (PROBE_DIR / "search_list.html").write_text(s.open(SEARCH, data=fields), encoding="utf-8")
    print(f"저장 완료: {PROBE_DIR}")
    print("이 폴더 안의 파일 이름이 나오면 Claude 에게 '저장했어'라고 알려 주세요.")


# ── 수집 ─────────────────────────────────────────────────────────────
# 학과명에 이 말이 있으면 내 학과(전자전기공학부)도 지원 대상으로 본다
EE_DEPT_RE = re.compile(r"전자|전기|정보통신|반도체")
DEPT_RE = re.compile(r"<div>\s*(.*?)\s*/\((\d+)\)\s*\[([^/\]]*)/(\d+)\]\s*</div>", re.S)
DETAIL_LABELS = [
    "학교 안내사항", "정규 실습시간", "실습기간", "실습요일", "연장실습여부", "근로계약 체결여부", "전형방법",
    "접수마감일자", "면접일자", "최종선발일자", "참고일정", "선발대상/학생평가교수", "총 모집인원",
    "학생요건 요구역량", "학생요건 기타사항", "실습지원비", "실습지원비 지급예정일", "기타지원사항",
    "기관담당교수", "진행상태", "실습직무", "직무명", "교육목표", "직무개요", "운영/지도계획", "운영계획서 파일첨부",
]


def strip_html(s):
    import html
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</th>|</td>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t ]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def search_fields(page_html):
    """기관 조회 검색 폼의 기본값 (진행중·현재 학기)."""
    form = re.search(r'<form[^>]*name="searchForm"[^>]*>(.*?)</form>', page_html, re.S)
    fields = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(1))) if form else {}
    fields.update({"compTypeCode": "", "locationCode": "", "compInKind": "", "compName": ""})
    return fields


def parse_rows(page_html):
    rows = []
    for tr in re.findall(r"<tr>\s*<td class=\"left_no\">.*?</tr>", page_html, re.S):
        m = re.search(r"jobInternDetail\('(\d+)'\s*,\s*'(\d+)'\)", tr)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not m or len(tds) < 10:
            continue
        cell = [strip_html(td) for td in tds]
        rows.append({
            "jid": m.group(1), "js": m.group(2), "industry": cell[0], "comp_type": cell[1],
            "company": cell[2], "dept": cell[3], "location": cell[4], "period": cell[5], "deadline": cell[6],
            "targets": [{"name": n, "code": c, "cond": cond, "count": int(k)} for n, c, cond, k in DEPT_RE.findall(tds[8])],
            "pay": re.sub(r"\s+", " ", cell[9]),
            "can_apply": "sh.join(" in tr, "applied": "sh.cancel(" in tr,
        })
    return rows


def parse_detail(page_html):
    sections, cur = {}, None
    for line in strip_html(page_html).split("\n"):
        key = line.strip()
        if key in DETAIL_LABELS:
            cur = key
            sections.setdefault(cur, [])
        elif cur and key:
            sections[cur].append(key)
    return {k: "\n".join(v) for k, v in sections.items()}


def fetch_all(s):
    first = s.open(SEARCH)
    fields = search_fields(first)
    rows, seen = [], set()
    for page in range(1, 41):
        doc = first if page == 1 else s.open(SEARCH, data={**fields, "page": str(page)})
        got = [r for r in parse_rows(doc) if r["jid"] not in seen]
        if not got:
            break
        seen.update(r["jid"] for r in got)
        rows += got
        time.sleep(0.4)
    return rows


def dept_check(targets):
    """(지원 가능한 학과인지, 전자전기 계열을 콕 집어 뽑는지)"""
    ee = any(EE_DEPT_RE.search(t["name"]) for t in targets)
    return ee or any(t["name"] == "전체학과" for t in targets), ee


def build_items(s, rows, cache, now):
    import jobs_rules as R
    from jobs import without_company
    today_s = now.strftime("%Y-%m-%d")
    items, seen = [], set()
    for r in rows:
        end = r["deadline"][:10]
        if end and end < today_s:
            continue
        ok_dept, ee = dept_check(r["targets"])
        if not ok_dept:
            continue
        d = cache["details"].get(r["jid"])
        stale = not d or d.get("_at", "") < (now - timedelta(days=DETAIL_REFRESH_DAYS)).strftime("%Y-%m-%d %H:%M")
        if stale:
            try:
                html_ = s.open(TG + "/jobInternDetail.do", data={"jidSeq": r["jid"], "jsSeq": r["js"]},
                               headers={"X-Requested-With": "XMLHttpRequest"})
                d = cache["details"][r["jid"]] = {**parse_detail(html_), "_at": now.strftime("%Y-%m-%d %H:%M")}
            except Exception as e:
                log(f"[warn] 상세 실패 {r['jid']}: {e}")
            time.sleep(0.4)
        d = d or {}
        role = d.get("직무명", "")
        group = R.auto_group(r["company"])
        # 직무개요·교육목표 같은 긴 글에서 찾으면 '공정', '품질' 같은 말이 우연히 걸려서 부서·직무명만 본다
        jobs = R.job_matches(without_company(f"{r['dept']} {role}", r["company"]))
        if not (ee or group or jobs):  # 전체학과 모집은 직무가 맞을 때만
            continue
        title = r["dept"] + (f" · {role}" if role and role not in r["dept"] else "")
        if (r["company"], title, end) in seen:  # 같은 공고가 두 번 등록된 경우
            continue
        seen.add((r["company"], title, end))
        # 현장실습 시스템 공고는 원래 재학생 학점연계용이라, 학년·졸업 조건이 따로 없으면 '재학생 지원 가능'이 된다
        req = "\n".join(filter(None, (d.get("학생요건 요구역량"), d.get("학생요건 기타사항"), d.get("학교 안내사항"),
                                      "(학점연계 현장실습)")))
        c = R.classify(req, title, now.date()) if d else {"status": "check", "reason": "상세를 아직 못 읽음", "evidence": ""}
        if "(학점연계 현장실습)" in c["evidence"]:  # 위에서 덧붙인 문구로 판정됐다 = 학년·졸업 조건이 없다
            c = {**c, "reason": "학년·졸업 조건 없음 (학점연계 현장실습)", "evidence": ""}
        progress = d.get("진행상태", "")
        state = "지원함" if r["applied"] else "지금 신청 가능" if r["can_apply"] else (progress or "접수 전")
        items.append({
            "id": f"tgl-{r['jid']}", "source": "tollgate_login", "source_name": "현장실습 시스템",
            "company": r["company"], "title": title, "url": SEARCH, "apply_url": "",
            "start": "", "end": end, "fields": [r["industry"], r["comp_type"], r["location"]],
            "auto": group, "jobs": (["전자전기 학과 모집"] if ee else []) + jobs,
            "intern_type": f"{state} · {r['period']} · {r['pay']}",
            **c, "basis": "학생요건", "first_seen": cache["first_seen"].setdefault(r["jid"], now.strftime("%Y-%m-%d %H:%M")),
            "also": [], "can_apply": r["can_apply"],
        })
    order = {"ok": 0, "check": 1, "no": 2}
    items.sort(key=lambda it: (order[it["status"]], it["end"] or "9999", it["company"]))
    return items


# ── 결과 내보내기·알림 ───────────────────────────────────────────────
def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M} {msg}"
    print(line, flush=True)
    if not _STDOUT_IS_LOG:
        STATE_DIR.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          creationflags=NO_WINDOW)


def publish_summary(items, now):
    """공개 사이트에는 곳 수와 가장 가까운 마감만 올린다 (기관 이름·내용은 올리지 않는다)."""
    live = [it for it in items if it["status"] != "no"]
    ends = sorted(it["end"] for it in live if it["end"])
    summary = {"checked": now.strftime("%Y-%m-%d %H:%M"), "ok": sum(it["status"] == "ok" for it in live),
               "check": sum(it["status"] == "check" for it in live), "next_end": ends[0] if ends else "",
               "url": TG + "/index.do"}
    pulled = git("pull", "-q", "--rebase", "--autostash")
    if pulled.returncode:
        log(f"[warn] git pull 실패: {pulled.stderr.strip()[:200]}")
    SUMMARY_JS.write_text("window.TOLLGATE = " + json.dumps(summary, ensure_ascii=False) + ";\n", encoding="utf-8")
    git("add", str(SUMMARY_JS.relative_to(ROOT)))
    if git("diff", "--cached", "--quiet").returncode == 0:
        return
    git("commit", "-q", "-m", f"현장실습 요약 갱신 {summary['checked']}")
    for _ in range(2):  # Actions 커밋과 겹치면 한 번 더 받아서 올린다
        if git("push", "-q").returncode == 0:
            return
        git("pull", "-q", "--rebase", "--autostash")
    log("[warn] 요약을 GitHub 에 올리지 못했습니다 (다음 실행에서 다시 시도)")


def mail_env():
    """keyring 의 메일 설정을 jobs.send 가 읽는 환경변수로 옮긴다. 설정이 없으면 False."""
    import keyring
    user, pw = keyring.get_password(KEYRING_SERVICE, "mail_user"), keyring.get_password(KEYRING_SERVICE, "mail_app_password")
    if not (user and pw):
        return False
    os.environ.update({"MAIL_USER": user, "MAIL_APP_PASSWORD": pw,
                       "MAIL_TO": keyring.get_password(KEYRING_SERVICE, "mail_to") or user, "SITE_URL": SEARCH})
    return True


def toast(title, body):
    """메일 설정이 없을 때 쓰는 Windows 알림."""
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
          "$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
          "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
          "$t = $x.GetElementsByTagName('text');"
          "$t.Item(0).AppendChild($x.CreateTextNode($env:TOAST_TITLE)) > $null;"
          "$t.Item(1).AppendChild($x.CreateTextNode($env:TOAST_BODY)) > $null;"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
          "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show("
          "[Windows.UI.Notifications.ToastNotification]::new($x))")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW,
                   env={**os.environ, "TOAST_TITLE": title, "TOAST_BODY": body}, capture_output=True)


def run(dry=False):
    """dry=True 면 결과만 보여 주고 GitHub 업로드·알림·알림 기록은 하지 않는다."""
    import jobs
    now = datetime.now(jobs.KST)
    STATE_DIR.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for k in ("details", "notified", "reminded", "first_seen"):
        cache.setdefault(k, {})
    userid, password, new = credentials(ask_save=False)
    if new:
        log("저장된 아이디·비밀번호가 없습니다. `python tollgate_local.py probe` 로 한 번 로그인해 저장하세요.")
        return 1
    try:
        s = login(userid, password)
    except LoginError as e:
        log(f"로그인 실패: {e}")
        toast("현장실습 확인 실패", str(e))
        return 1
    rows = fetch_all(s)
    items = build_items(s, rows, cache, now)
    counts = {k: sum(it["status"] == k for it in items) for k in ("ok", "check", "no")}
    log(f"실습 기관 {len(rows)}곳 중 내 학과·직무 {len(items)}곳 (충족 {counts['ok']} · 확인 필요 {counts['check']} · 불일치 {counts['no']})")

    LOCAL_JS.write_text("window.TOLLGATE_ITEMS = " + json.dumps(items, ensure_ascii=False) + ";\n", encoding="utf-8")
    if dry:
        for it in items:
            print(f"  [{it['status']}] {it['company']} | {it['title']} | 마감 {it['end'] or '-'} | {it['reason']}"
                  f" | {', '.join(it['jobs']) or it['auto']} | {it['intern_type']}")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    publish_summary(items, now)

    if mail_env():
        jobs.notify(items, cache, now.date(), label="현장실습")
    else:
        fresh = [it for it in items if it["status"] != "no" and f"{it['id']}" not in cache["notified"]]
        if fresh:
            toast(f"현장실습: 새 실습처 {len(fresh)}곳", ", ".join(f"{it['company']}" for it in fresh[:4])
                  + (" 외" if len(fresh) > 4 else ""))
        jobs.notify(items, cache, now.date(), label="현장실습")  # 메일이 없으면 기록만 남긴다

    alive = {it["id"] for it in items}
    for k in ("notified", "reminded"):
        cache[k] = {i: v for i, v in cache[k].items() if i in alive}
    live_jids = {r["jid"] for r in rows}
    for k in ("details", "first_seen"):
        cache[k] = {j: v for j, v in cache[k].items() if j in live_jids}
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


# ── 설정 ─────────────────────────────────────────────────────────────
def setup_mail():
    import keyring
    print("알림 메일을 보낼 Gmail 주소와 앱 비밀번호를 저장합니다 (README 의 '알림 연결' 과 같은 앱 비밀번호).")
    user = input("Gmail 주소: ").strip()
    pw = getpass.getpass("앱 비밀번호 16자리 (화면에 안 보입니다): ").strip()
    to = input(f"받을 주소 (엔터 = {user}): ").strip()
    keyring.set_password(KEYRING_SERVICE, "mail_user", user)
    keyring.set_password(KEYRING_SERVICE, "mail_app_password", pw)
    if to:
        keyring.set_password(KEYRING_SERVICE, "mail_to", to)
    print("저장했습니다. 다음 실행부터 Windows 알림 대신 메일로 알립니다.")


def install():
    pyw = Path(sys.executable).with_name("pythonw.exe")
    ps = (f"$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument '\"{ROOT / 'tollgate_local.py'}\" run' "
          f"-WorkingDirectory '{ROOT}';"
          "$t = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(8) -RepetitionInterval (New-TimeSpan -Hours 3);"
          "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable "
          "-ExecutionTimeLimit (New-TimeSpan -Minutes 20);"
          f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s "
          "-Description '현장실습 시스템 실습 기관 확인 (skku-notice/tollgate_local.py)' -Force | Out-Null")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    print("작업 스케줄러에 등록했습니다 (매일 8시부터 3시간마다)." if r.returncode == 0 else f"등록 실패: {r.stderr}")


def uninstall():
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false"], capture_output=True)
    print("작업 스케줄러에서 지웠습니다.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        if sys.stdout is None:  # pythonw(작업 스케줄러)로 실행되면 콘솔이 없다
            STATE_DIR.mkdir(exist_ok=True)
            sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8")
            _STDOUT_IS_LOG = True
        sys.exit(run())
    elif cmd == "check":
        sys.exit(run(dry=True))
    elif cmd == "probe":
        probe()
    elif cmd == "install":
        install()
    elif cmd == "uninstall":
        uninstall()
    elif cmd == "setup-mail":
        setup_mail()
    elif cmd == "forget":
        forget_credentials()
        print("저장된 아이디·비밀번호를 지웠습니다.")
    else:
        print(__doc__)
