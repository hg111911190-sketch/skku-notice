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
