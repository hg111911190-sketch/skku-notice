# -*- coding: utf-8 -*-
"""인턴 공고 필터 규칙: 내 학적 정보, 직무 키워드, 자동차 회사 목록, 지원 자격 판정.

조건을 바꾸고 싶으면 이 파일만 고치면 된다.
`python test_jobs_rules.py` 로 판정 예시가 그대로 맞는지 확인할 수 있다.
"""
import re
from datetime import date

# ── 내 정보 ──────────────────────────────────────────────────────────
GRAD = (2028, 2)      # 졸업 예정 (년, 월)
ENTER_YEAR = 2024     # 입학 연도. 휴학 없이 2026년 2학기 = 3학년 6학기

# ── 직무 키워드: 제목·모집 직무·카테고리에 하나라도 있으면 통과 ─────────
# 영문은 단어 경계로, 한글은 부분 문자열로 찾는다.
JOB_KEYWORDS = [
    # 전자전기·하드웨어
    "반도체", "임베디드", "embedded", "회로", "circuit", "펌웨어", "firmware", "f/w",
    "하드웨어", "hardware", "h/w", "전자", "전기", "전력", "전장", "제어", "소자", "패키징",
    "fpga", "soc", "asic", "rtl", "아날로그", "analog", "신호처리", "rf", "안테나",
    "인버터", "모터", "배터리", "bms", "센서", "디스플레이", "로봇", "로보틱스", "메카트로닉스",
    # 자율주행·차량 ('차량'만 쓰면 '숙소+차량 지원' 같은 복리후생에 걸려서 좁혔다)
    "자율주행", "autonomous", "adas", "라이다", "lidar", "레이더", "radar", "차량용", "차량개발", "차량 개발",
    # 생산·품질·구매 (관리 직무). '제조'만 쓰면 '부품 제조 기업' 같은 회사 소개에 걸려서 좁혔다
    "생산기술", "생산관리", "공정", "설비", "품질", "qc", "구매", "조달", "purchasing", "procurement",
    "scm", "제조기술", "제조공정", "제조혁신", "manufacturing", "양산",
]
# 키워드를 포함하지만 직무와 무관한 말 (먼저 지운 뒤 키워드를 찾는다)
JOB_EXCLUDE = [
    "전자상거래", "전자결재", "전자책", "전자문서", "전자신문", "전기신문", "공정거래", "공정무역",
    "삼성전자", "lg전자", "엘지전자", "전자랜드",
]
# 제목이 이렇게 생기면 아예 뺀다. 해외 J-1 인턴 알선(12~18개월 풀타임, 휴학 필요)과 생산직.
# 해외 인턴도 보고 싶으면 첫 줄을 지운다.
EXCLUDE_TITLE_RE = re.compile(
    r"\[(?:미국|캐나다|일본|베트남|독일|호주|싱가포르|해외)[^\]]*\]|J-?1\s*비자|해외\s*인턴|워킹\s*홀리데이"
    r"|생산직|기능직"
)
# 링커리어 직무 카테고리 중 이것에 속하면 통과
LINKAREER_CATEGORIES = {
    "전기/전자/반도체", "생산/공정관리", "품질관리(QC/QA)", "설비/기계유지보수", "구매/자재관리",
}

# ── 자동차 회사: 여기 속하면 직무와 상관없이 학년·졸업 조건만 본다 ──────
# 이름은 공백·(주)를 뺀 소문자로 비교한다. 4글자 이상은 앞부분 일치도 인정
# (예: '현대자동차남양연구소'), 짧은 이름은 정확히 같아야 한다 ('기아대책' 오인 방지).
AUTO_COMPANIES = {
    "현대자동차그룹": [
        "현대자동차그룹", "현대자동차", "현대차", "기아", "기아자동차", "제네시스", "현대모비스",
        "현대제철", "현대건설", "현대엔지니어링", "현대글로비스", "현대위아", "현대트랜시스",
        "현대오토에버", "현대케피코", "현대로템", "현대비앤지스틸", "현대캐피탈", "현대카드",
        "현대커머셜", "현대차증권", "이노션", "해비치호텔앤드리조트", "현대엔지비", "현대아이에프씨",
        "현대ngv", "포티투닷", "42dot", "슈퍼널", "보스턴다이나믹스", "모션랩",
    ],
    "HL그룹": [
        "hl그룹", "hl만도", "hl클레무브", "hl디앤아이한라", "hl홀딩스", "hl로보틱스", "hl그린파워",
        "만도", "클레무브",
    ],
    "기타 자동차": [
        "한온시스템", "한국지엠", "한국gm", "gm한국사업장", "르노코리아", "kg모빌리티", "에스엘",
        "서연이화", "덴소코리아", "한국로버트보쉬", "보쉬코리아", "콘티넨탈오토모티브", "엘지마그나",
        "lg마그나이파워트레인",
    ],
}

INTERN_TITLE_RE = re.compile(r"인턴|intern|현장실습", re.I)


def title_excluded(title):
    return bool(EXCLUDE_TITLE_RE.search(title or ""))


def norm_company(name):
    s = (name or "").lower()
    s = re.sub(r"\(주\)|㈜|주식회사|\(유\)|\s", "", s)
    return s.replace("에이치엘", "hl")


def auto_group(company):
    """자동차 회사면 그룹 이름, 아니면 ''."""
    for part in re.split(r"[/,·]", company or ""):
        n = norm_company(part)
        if not n:
            continue
        for group, names in AUTO_COMPANIES.items():
            for nm in names:
                if n == nm or (len(nm) >= 4 and n.startswith(nm)):
                    return group
    return ""


_KW_RES = [
    (kw, re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])") if re.fullmatch(r"[a-z0-9/]+", kw) else None)
    for kw in JOB_KEYWORDS
]


def job_matches(*texts, categories=()):
    """직무 키워드/카테고리 중 걸린 것 목록."""
    s = " ".join(t for t in texts if t).lower()
    for ex in JOB_EXCLUDE:
        s = s.replace(ex, " ")
    hits = [c for c in categories if c in LINKAREER_CATEGORIES]
    for kw, rx in _KW_RES:
        if (rx.search(s) if rx else kw in s) and kw not in hits:
            hits.append(kw)
    return hits


def strip_company(title, company):
    """제목에서 회사명을 지운다 ('[LG전자] 마케팅 인턴' 의 '전자' 오인 방지)."""
    t = title or ""
    for part in {company or "", re.sub(r"\(주\)|㈜|주식회사", "", company or "").strip()}:
        if len(part) >= 2:
            t = t.replace(part, " ")
    return t


# ── 학년·학기 (날짜 기준) ───────────────────────────────────────────
def grade_on(d):
    """d 시점의 학년. 3월 1일에 올라간다."""
    return max(1, min(4, d.year - ENTER_YEAR + (1 if d.month >= 3 else 0)))


def semesters_done(d):
    """d 시점까지 마친 학기 수. 1학기는 6/20, 2학기는 12/20에 끝난 것으로 본다."""
    n = 2 * (d.year - ENTER_YEAR) + ((d.month, d.day) >= (6, 20)) + ((d.month, d.day) >= (12, 20))
    return max(0, min(8, n))


# ── 지원 자격 판정 ──────────────────────────────────────────────────
# 공백을 모두 지운 문자열에서 찾는다 ('2028 년 2 월' 같은 OCR 결과도 잡히도록).
_DATE_PATTERNS = [
    (re.compile(r"(20[2-4]\d)년도?(\d{1,2})월"), "ym"),
    (re.compile(r"(20[2-4]\d)[./](\d{1,2})(?!\d)"), "ym"),
    (re.compile(r"(?<![\d.])'?([2-4]\d)년도?(\d{1,2})월"), "yym"),
    (re.compile(r"'([2-4]\d)[./](\d{1,2})(?!\d)"), "yym"),
    (re.compile(r"(20[2-4]\d)학년도"), "acad"),
    (re.compile(r"(20[2-4]\d)년(?!도?\d{1,2}월)도?"), "y"),
    (re.compile(r"(?<![\d.])'?([2-4]\d)년(?!도?\d{1,2}월)도?"), "yy"),
]
_GRAD_NEXT_RE = re.compile(r"(.{0,16}?)졸업", re.S)     # 날짜 뒤에 '졸업'이 바로 오는지
_GRAD_PREV_RE = re.compile(r"졸업(?:예정)?(?:자)?[(:：]$")  # '졸업예정자(2028년 2월)' 형태
_MOD_RE = re.compile(r"\(?(이전|이내|까지|이후)")
# 날짜와 '졸업' 사이에 이런 말이 있으면 졸업 시기가 아니라 공고·근무 시기다
_NOT_GRAD_RE = re.compile(r"상반기|하반기|하계|동계|인턴|채용|모집|입사|기준|마감|접수|근무|실습")
_SEMESTER_RE = re.compile(r"(\d)학기(?:이상|이수|수료|를?마친|를?마치신)(?!미만)")
_GRADE_MIN_RE = re.compile(r"([1-4])학년이상")
_GRADE_EXACT_RE = re.compile(r"([1-4])학년(?:재학|휴학|학생)")
_GRADE_UNDER_RE = re.compile(r"([1-4])학년(?:([12])학기)?미만")
_STUDENT_RE = re.compile(r"재학생|재학중|휴학생|대학생|학년무관|학력무관|학년제한없|학력제한없|전학년"
                         r"|학점연계|현장실습학기|학점인정|학점등록")
_ANY_EDU_RE = re.compile(r"고졸이상|고등학교졸업이상|고등학교졸업자이상")
_EXPECTED_RE = re.compile(r"졸업예정|졸업\(예정\)|졸업유예")
_GRADUATE_ONLY_RE = re.compile(r"기졸업자|졸업자|졸업하신|졸업한|대학(?:교)?졸업(?:\([^)]{0,6}\))?이상|대졸이상|학사이상|학사학위"
                               r"|학력:?(?:4년제)?(?:정규)?대학(?:교)?졸업")
_INVISIBLE_RE = re.compile(r"[​-‏⁠﻿]")  # 제로폭 공백 등 (본문에 섞여 있으면 단어가 끊긴다)
_MASTER_RE = re.compile(r"석사|박사|대학원생")


def _compact(s):
    """공백을 지운 문자열과, 각 글자의 원래 위치."""
    s = (s or "").replace("’", "'").replace("‘", "'")
    keep = [(i, ch) for i, ch in enumerate(s) if not ch.isspace() and not _INVISIBLE_RE.match(ch)]
    return "".join(ch for _, ch in keep), [i for i, _ in keep]


def _snippet(orig, idx, s, e, pad=28):
    if not idx:
        return ""
    a = idx[max(0, min(s, len(idx) - 1))]
    b = idx[max(0, min(e, len(idx)) - 1)] + 1
    return re.sub(r"\s+", " ", orig[max(0, a - pad):b + pad]).strip()


def _grad_constraints(t):
    """졸업 시기 언급을 (년, 월 또는 None, 'exact'|'before'|'after', 시작, 끝) 으로 뽑는다."""
    out, taken = [], []
    for rx, kind in _DATE_PATTERNS:
        for m in rx.finditer(t):
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            g = m.groups()
            if kind == "ym":
                y, mo = int(g[0]), int(g[1])
            elif kind == "yym":
                y, mo = 2000 + int(g[0]), int(g[1])
            elif kind == "acad":
                y, mo = int(g[0]) + 1, 2          # 2027학년도 졸업 = 2028년 2월
            elif kind == "y":
                y, mo = int(g[0]), None
            else:
                y, mo = 2000 + int(g[0]), None
            if mo is not None and not 1 <= mo <= 12:
                continue
            nxt = _GRAD_NEXT_RE.match(t, e)
            between = nxt.group(1) if nxt else ""
            near_next = nxt and not _NOT_GRAD_RE.search(between) and not re.search(r"\d", re.sub(r"[2-4]년제", "", between))
            if not near_next and not _GRAD_PREV_RE.search(t[max(0, s - 8):s]):
                continue
            taken.append((s, e))
            mod = _MOD_RE.match(between if near_next else t[e:e + 4])
            way = "after" if mod and mod.group(1) == "이후" else "before" if mod else "exact"
            out.append((y, mo, way, s, e))
    return out


def _grad_ok(y, mo, way):
    if way == "after":
        return GRAD >= (y, mo or 1)
    if way == "before":
        return GRAD <= (y, mo or 12)
    return GRAD == (y, mo) if mo else GRAD[0] == y


def classify(text, title="", today=None):
    """공고 본문(+제목)으로 지원 가능 여부를 판정한다.

    반환: {"status": "ok"|"check"|"no", "reason": 짧은 설명, "evidence": 원문 일부}
      ok    = 조건 충족 (2028년 2월 졸업 포함, 재학생 가능, 3학년 이상 등)
      check = 확인 필요 (조건이 없거나 '졸업예정자'처럼 시기가 불분명)
      no    = 불일치 (2027년 졸업자만, 졸업자만, 석·박사 등)
    """
    today = today or date.today()
    orig = f"{title}\n{text or ''}"
    t, idx = _compact(orig)
    title_c, _ = _compact(title)

    def res(status, reason, s=None, e=None):
        return {"status": status, "reason": reason, "evidence": _snippet(orig, idx, s, e) if s is not None else ""}

    if _MASTER_RE.search(title_c) and not re.search(r"학사|학부", title_c):
        return res("no", "석·박사 대상")

    cons = _grad_constraints(t)
    if cons:
        hit = next((c for c in cons if _grad_ok(*c[:3])), None)
        if hit:
            return res("ok", f"{GRAD[0]}년 {GRAD[1]}월 졸업예정 포함", hit[3], hit[4])
        y, mo, way, s, e = max(cons, key=lambda c: (c[0], c[1] or 12))
        when = f"{y}년 {mo}월" if mo else f"{y}년"
        word = {"before": " 이전", "after": " 이후", "exact": ""}[way]
        return res("no", f"{when}{word} 졸업예정 대상", s, e)

    done, grade = semesters_done(today), grade_on(today)
    m = _SEMESTER_RE.search(t)
    if m:
        n = int(m.group(1))
        if n <= done + 1:
            return res("ok", f"{n}학기 이상 이수 (현재 {done}학기 이수, {done + 1}학기 중)", *m.span())
        return res("no", f"{n}학기 이상 이수 필요", *m.span())

    m = _GRADE_UNDER_RE.search(t)
    if m and (grade, 1) < (int(m.group(1)), int(m.group(2) or 1)):
        return res("ok", f"{m.group(1)}학년{' ' + m.group(2) + '학기' if m.group(2) else ''} 미만 재학생", *m.span())
    m = _GRADE_MIN_RE.search(t) or _GRADE_EXACT_RE.search(t)
    if m:
        n = int(m.group(1))
        exact = m.re is _GRADE_EXACT_RE
        if (n == grade) or (not exact and n < grade):
            return res("ok", f"{n}학년{'' if exact else ' 이상'} 대상 (현재 {grade}학년)", *m.span())
        if n == grade + 1:
            return res("check", f"{n}학년 대상 (현재 {grade}학년, 내년엔 해당)", *m.span())
        return res("no", f"{n}학년 대상 (현재 {grade}학년)", *m.span())

    m = _STUDENT_RE.search(t)
    if m:
        return res("ok", "재학생 지원 가능", *m.span())
    m = _ANY_EDU_RE.search(t)
    if m:
        return res("ok", "학력 무관 (고졸 이상)", *m.span())
    m = _EXPECTED_RE.search(t)
    if m:
        return res("check", "졸업예정자 대상 (졸업 시기 미기재)", *m.span())
    m = _GRADUATE_ONLY_RE.search(t)
    if m:
        return res("no", "졸업자 대상", *m.span())
    return res("check", "지원 자격 정보 없음")
