# SKKU 공지 모아보기

성균관대 공지 게시판 4곳(학교 공지, 정보통신대학, 전자전기공학부, 미래자동차)을 한 페이지에서 본다.

- `scrape.py`: 게시판마다 최근 30건(3페이지)을 긁어 `docs/notices.json`, `docs/notices.js` 로 저장한다. 표준 라이브러리만 쓴다.
- `docs/index.html`: 저장된 목록을 날짜순으로 보여 준다. 게시판 필터, 검색, 고정 공지 숨기기를 지원한다.
- `.github/workflows/update.yml`: GitHub Actions 가 매시간 `scrape.py` 를 돌리고 결과를 커밋한다.

## 로컬에서 보기

```bash
python scrape.py
# docs/index.html 을 브라우저로 연다
```

## 배포 (GitHub Pages, 서버 불필요)

1. 이 폴더를 GitHub 저장소로 올린다 (무료 계정은 공개 저장소여야 Pages 사용 가능).
2. 저장소 Settings → Pages → Source 를 `Deploy from a branch`, 브랜치 `main` / 폴더 `/docs` 로 지정한다.
3. Actions 탭에서 `공지 갱신` 워크플로를 한 번 수동 실행(Run workflow)해 동작을 확인한다.

이후 `https://<아이디>.github.io/<저장소>/` 에서 볼 수 있고, 목록은 매시간 자동 갱신된다.

## 게시판 추가

`scrape.py` 의 `SOURCES` 에 같은 학교 CMS 게시판 주소를 추가하고, `docs/index.html` 의 `COLORS` 에 색을 하나 지정한다.

## 인턴 공고 레이더 (`docs/jobs.html`)

링커리어·자소설닷컴·학교 공지·현장실습 시스템에서 인턴 공고를 모아, 2028년 2월 졸업(3학년) 기준으로 지원 가능한지 판정하고 새 공고를 알린다.

- `jobs.py`: 수집 → 판정 → `docs/jobs.json`·`docs/jobs.js`(사이트), `docs/jobs.ics`(마감일 캘린더), 알림 전송.
- `jobs_rules.py`: **조건을 바꿀 때 고치는 파일.** 졸업 시기·입학 연도, 직무 키워드, 자동차 회사 목록, 제외할 제목(해외 J-1 인턴 등), 지원 자격 판정 규칙.
- `test_jobs_rules.py`: 실제 공고 문구로 만든 판정 예시. 규칙을 고친 뒤 `python test_jobs_rules.py` 로 확인한다.
- `cache/jobs_cache.json`: 읽은 상세 페이지·OCR 결과·알림 보낸 기록 (같은 공고를 다시 읽거나 두 번 알리지 않게).
- `.github/workflows/jobs.yml`: 3시간마다 실행. 이미지로 된 공고(자소설닷컴 대부분)는 tesseract OCR 로 글자를 읽는다.

**보여 주는 공고**: 자동차 회사(현대자동차그룹·HL그룹·한온시스템 등)는 직무와 상관없이 전부, 그 밖의 회사는 반도체·임베디드·회로·펌웨어·자율주행·생산기술·구매·품질 등 직무만.
**판정**: 조건 충족 / 확인 필요(자격 정보 없음, 졸업 시기 미기재) / 불일치(2027년 졸업자만, 졸업자만, 석·박사). 알림은 충족과 확인 필요만 보낸다.

**현장실습 시스템** (tollgate.skku.edu): 로그인 없이 보이는 공지사항 게시판만 읽는다. 학기별 '현장실습 학생 지원 신청 안내'는 항상, 기관별 '현장실습생 모집' 글은 위와 같은 직무·자동차 회사 기준으로 보여 준다. 실습 기관 전체 목록(기관 조회)은 학교 통합로그인이 필요해서 수집하지 않는다.

### 알림 연결 (Gmail)

보내는 계정은 개인 Gmail 을 쓴다 (학교·기관 Google Workspace 계정은 관리자가 앱 비밀번호를 막아 둔 경우가 많다).

1. Google 계정 → 보안 → **2단계 인증**을 켠다 (앱 비밀번호의 전제 조건).
2. https://myaccount.google.com/apppasswords 에서 앱 이름(예: `skku-notice`)을 넣고 만들면 16자리 비밀번호가 나온다. 한 번만 보이니 바로 복사한다.
3. 저장소 Settings → Secrets and variables → Actions → New repository secret 으로 등록한다.
   - `MAIL_USER`: 보내는 Gmail 주소
   - `MAIL_APP_PASSWORD`: 위 16자리 (공백이 있어도 된다)
   - `MAIL_TO` (선택): 받을 주소. 없으면 `MAIL_USER` 로 보낸다.
4. Actions 탭에서 `인턴 공고 확인` 을 수동 실행(Run workflow)하면 "알림이 연결됐습니다" 요약 메일이 온다. 이후에는 새 공고와 마감 임박 공고만 온다.

메일이 안 오면 Actions 실행 로그에서 `알림 전송 실패` 줄을 확인한다 (보낸 기록이 남지 않아 다음 실행에서 다시 보낸다).

### 마감일 캘린더

구글 캘린더 → 다른 캘린더 추가 → URL로 추가 → `https://<아이디>.github.io/<저장소>/jobs.ics`.
조건 충족·확인 필요 공고의 마감일이 하루 일정으로 들어간다 (구글이 몇 시간마다 다시 읽는다).
