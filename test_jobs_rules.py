# -*- coding: utf-8 -*-
"""jobs_rules 판정 예시. `python test_jobs_rules.py` 로 실행한다.

문구는 실제 공고(링커리어·학교 공지)에서 가져왔다. 기준일은 2026-11-01 (3학년, 5학기 이수·6학기 중).
"""
import unittest
from datetime import date

from jobs_rules import auto_group, classify, grade_on, job_matches, semesters_done, strip_company, title_excluded

TODAY = date(2026, 11, 1)


class Eligibility(unittest.TestCase):
    def check(self, text, expected, title=""):
        got = classify(text, title, TODAY)
        self.assertEqual(got["status"], expected, f"{text!r} -> {got}")

    def test_graduation_dates(self):
        # 기아 26년 하반기 전환형 인턴
        self.check("[지원 자격] - 2027년 8월 졸업 예정이신 분 (2026. 11.4 기준 4학년 2학기 미만 재학생 및 휴학생)", "no")
        # 한온시스템 하반기 채용연계형
        self.check("· 4년제 정규대학 이상 기졸업자 또는 2027년 2월 졸업예정자 · 2027년 1월 중 입사 가능하신 분", "no")
        self.check("4년제 대학 졸업(예정)자, 예정자의 경우 학점 수료자(27년 2월 이내 졸업 예정자)", "no")
        self.check("2026년 8월 ~ 2027년 8월 졸업(예정)자", "no")
        self.check("졸업예정자(2027년 2월)", "no")
        self.check("2027년도 4년제 정규 대학교 졸업예정자 또는 인턴 경험이 있으신 분", "no")
        self.check("2028년 2월 졸업예정자", "ok")
        self.check("28년 2월 이전 졸업 예정자", "ok")
        self.check("2027년 8월 이후 졸업예정자", "ok")
        self.check("2027년 2월 또는 2028년 2월 졸업 예정자", "ok")
        self.check("2027학년도 졸업예정자", "ok")
        self.check("2028.02 졸업 예정자", "ok")
        # OCR 결과처럼 글자 사이에 공백이 끼어도
        self.check("2 0 2 8 년 2 월 졸 업 예 정 자", "ok")

    def test_period_is_not_graduation(self):
        # '2027년 상반기 인턴'의 2027은 졸업 시기가 아니다
        self.check("2027년 상반기 인턴 모집. 졸업예정자 지원 가능", "check")

    def test_semester_and_grade(self):
        self.check("자격 : 지원 시점 기준 6학기 이상 필수 이수", "ok")
        self.check("7학기 이상 이수자", "no")
        self.check("3학년 이상 재학생", "ok")
        self.check("4학년 재학생", "check")
        self.check("○ 참여자격: 성균관대학교 2학년 이상 재학생 중 2026학년도 겨울학기 학점 인정이 가능한 학생", "ok")

    def test_status_words(self):
        self.check("국내외 4년제 대학 재학생 또는 졸업예정자", "ok")
        self.check("신입 · 재학생 · 휴학생 · 졸업예정자 · 졸업생 · 전공 무관", "ok")
        self.check("정규직 전환 후 계속 근무가 가능하신 분 (졸업자 or 졸업예정자)", "check")
        self.check("(1년이내) 기졸업자 및 졸업예정자", "check")
        self.check("대학졸업(4년) 이상(졸업예정자 가능)", "check")
        self.check("자격요건 학력 대학졸업(4년) 이상 근무조건 급여 회사 내규에 따름", "no")
        self.check("자격조건 - 대학졸업(2,3년)이상", "no")
        self.check("영문 이력서, 대학&대학교 재학 또는 졸업증명서, 성적증명서", "check")
        self.check("", "check")

    def test_education(self):
        self.check("고등학교 졸업 이상 또는 이에 준하는 학력 소지자", "ok")
        self.check("[지원자격] - 학사 이상 - 웹사이트 구축·운영 경력을 보유하신 분", "no")
        # SK케미칼: '년도' 와 따옴표
        self.check("학력 : 학사 이상(‘27년도 2월 졸업예정자 및 취업계 사용 인원 지원 가능)", "no")
        # 경창산업: 제로폭 공백(U+200B)이 섞인 본문
        self.check("- 학력 : ​4년제 ​대학졸업 ​(기계/자동차/산업공학/전기전자 전공)", "no")
        # 슈나이더 일렉트릭: 학점 연계 현장실습
        self.check("· 학점 연계 현장실습 인턴으로 겨울방학 + 1학기 모두 학점 등록이 가능한 자", "ok")

    def test_master(self):
        self.check("연구 인턴", "no", title="2026년 하계 석/박사 인턴 모집")
        self.check("", "check", title="학사·석사 인턴 모집")


class Matching(unittest.TestCase):
    def test_auto_group(self):
        self.assertEqual(auto_group("현대자동차"), "현대자동차그룹")
        self.assertEqual(auto_group("기아"), "현대자동차그룹")
        self.assertEqual(auto_group("현대카드/현대커머셜"), "현대자동차그룹")
        self.assertEqual(auto_group("HL클레무브(주)"), "HL그룹")
        self.assertEqual(auto_group("에이치엘만도 주식회사"), "HL그룹")
        self.assertEqual(auto_group("한온시스템"), "기타 자동차")
        for other in ("현대종합금속", "HD현대", "현대백화점그룹", "기아대책", "현대해상화재보험"):
            self.assertEqual(auto_group(other), "", other)

    def test_jobs(self):
        self.assertIn("품질관리(QC/QA)", job_matches("총무", categories=["품질관리(QC/QA)"]))
        self.assertTrue(job_matches("선행 전장품 개발 (S/W, H/W, Motor)"))
        self.assertTrue(job_matches("생산기술"))
        self.assertTrue(job_matches("[R&D] 차량용 임베디드 SW 개발"))
        self.assertFalse(job_matches("전자상거래 MD 인턴"))
        self.assertFalse(job_matches("공정거래 법무 인턴"))
        self.assertFalse(job_matches("Performance marketing intern"))  # 'rf' 오인 방지
        self.assertFalse(job_matches(strip_company("[LG전자] 브랜드 마케팅 인턴", "LG전자")))
        self.assertFalse(job_matches("글로벌 2차전지 부품 제조기업 인사·총무 채용 (숙소+차량 지원)"))
        self.assertTrue(job_matches("차량용 반도체 검증"))

    def test_title_excluded(self):
        self.assertTrue(title_excluded("[미국인턴/앨라배마] 완성차 부품 제조 및 물류기업 - 인턴 채용"))
        self.assertTrue(title_excluded("[미국] 자동차 부품 제조 회사 아진 USA 구매팀 채용"))
        self.assertTrue(title_excluded("2026 생산직 인턴 모집"))
        self.assertTrue(title_excluded("2026년 [캐나다] Ski-Resort 호텔 취업(인턴) 프로그램"))
        self.assertFalse(title_excluded("[서울/울산/대구/창원] AX PM 인턴"))
        self.assertFalse(title_excluded("[현대자동차] 2027 하계 인턴십"))


class TollgateTitles(unittest.TestCase):
    """현장실습 시스템 공지 제목에서 실습 기관 뽑기 (제목은 실제 게시글)."""

    def test_company(self):
        from jobs import tollgate_company
        cases = {
            "2026년 겨울학기 국립생물자원관 현장실습생 모집(~11.17)": "국립생물자원관",
            "[공지]2026년 겨울학기 '비상교육' 현장실습생 모집 안내(~11.15.)": "비상교육",
            "2026년 겨울학기 '지속가능발전기업협의회[KBCSD]' 현장실습생 모집 안내(~11.22.)": "지속가능발전기업협의회[KBCSD]",
            "2026년 하반기 (주)샘표식품 현장실습생 모집 안내(~5.3.)": "(주)샘표식품",
            "2026학년도 1학기 삼성전자 DS부문 장기현장실습 참여 학생 모집 안내(~1/30, 13:00, 기한 엄수)": "삼성전자 DS부문",
            "2026년 1학기 성균관대학교 HD현대 채용연계형 현장실습학기제 참여 학생 모집(~1/22, 15:00)": "HD현대",
            "[GC녹십자] 2025학년도 겨울학기 표준현장실습 학기 학생 지원신청 안내(~11.12.)": "GC녹십자",
            # 학교 전체 모집 안내는 기관이 없다
            "2026학년도 겨울학기 현장실습 학생 지원 신청 안내(~11/29)": "",
            "2026학년도 1학기 표준 현장실습학기제 프로그램 참여 학생 모집(~2/4)": "",
            '2025학년도 겨울학기 "표준 현장실습학기제" 프로그램 참여 학생 모집(~11.30)': "",
        }
        for title, company in cases.items():
            self.assertEqual(tollgate_company(title), company, title)

    def test_company_name_is_not_a_job(self):
        from jobs import without_company
        body = "지속가능발전기업협의회 [KBCSD] 에서 2026 년 겨울학기 현장실습에 참여할 학생을 모집합니다"
        self.assertFalse(job_matches(without_company(body, "지속가능발전기업협의회[KBCSD]")))


class Profile(unittest.TestCase):
    def test_profile(self):
        self.assertEqual((grade_on(TODAY), semesters_done(TODAY)), (3, 5))
        self.assertEqual((grade_on(date(2027, 1, 10)), semesters_done(date(2027, 1, 10))), (3, 6))
        self.assertEqual((grade_on(date(2027, 4, 1)), semesters_done(date(2027, 4, 1))), (4, 6))


if __name__ == "__main__":
    unittest.main(verbosity=1)
