"""내장 청년정책 코퍼스 (mock 겸 RAG 근거 자료 + 자격 판정 기준).

각 Policy 는 두 얼굴을 가진다:
  ① 검색용 — to_chunk() 로 retrieval.Chunk 로 변환(contextual 블러브 + 본문). BM25 인덱싱 대상.
  ② 판정용 — 구조화된 자격조건 필드(age_min/max, income_*, regions, employment_*, criteria …).
     eligibility.evaluate() 가 UserProfile 대비 조건별로 pass/fail/unknown/manual 판정.

사실 확인(fact-check) 기준일: 2026-07 (WebSearch 조사). 수치·조건은 공고마다 변동될 수 있으므로
각 Policy 에 source(출처) + as_of(기준일)를 명시한다. 확인 안 된 수치는 넣지 않고
criteria(자유텍스트 조건)로 남겨 호스트 LLM/공고 확인에 위임한다.

⚠️ 라이브 API(온통청년) 연동 시에는 clients/youthcenter.py 가 이 코퍼스를 mock 폴백으로 쓴다.
   실제 API 응답 필드 매핑은 clients/youthcenter.py 상단 주석 참고(키 발급 후 라이브 검증 필요).

금액 표기: 원(KRW) 정수. 소득 조건은 '개인 연소득(원)' 상한을 income_max_won 으로,
가구 중위소득%·재산 등 개인 연소득으로 환원 불가한 조건은 criteria 로 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .retrieval import Chunk

# 취업상태 표준값(UserProfile.employment_status 와 매칭). None/미지정은 unknown 처리.
EMP_EMPLOYED = "재직"
EMP_JOBSEEKER = "구직"
EMP_SELF = "자영업"
EMP_STUDENT = "학생"
EMP_UNEMPLOYED = "무직"


@dataclass
class Criterion:
    """자유텍스트(정성) 조건 — 구조화 판정 불가. 호스트 LLM/공고 확인에 위임(manual).

    key: 조건 종류 식별용(예: 'household_income', 'residency_period', 'no_house').
    text: 사람이 읽는 조건 설명(원문 성격).
    ask: 이 조건을 확인하려면 사용자에게 무엇을 물어야 하는지(needs_more_info 질문 후보).
    """
    key: str
    text: str
    ask: str = ""


@dataclass
class Policy:
    id: str
    name: str
    category: str                 # 대분류(주거/일자리/금융/복지·문화 등)
    subcategory: str              # 중분류
    summary: str                  # 정책 설명(무엇인지)
    support_content: str          # 지원 내용(얼마/무엇을)
    blurb: str                    # contextual 블러브(누구 대상·무엇인지 1~2문장) — BM25용
    source: str                   # 출처(주관기관/근거 공고)
    as_of: str                    # 기준일
    apply_url: str = ""           # 신청 URL
    agency: str = ""              # 주관기관
    apply_period: str = ""        # 신청기간
    documents: str = ""           # 필요서류
    how_to_apply: str = ""        # 신청방법

    # ── 구조화 자격조건(결정론 판정용; None = 조건 없음/제한 없음) ──
    age_min: int | None = None
    age_max: int | None = None
    regions: list[str] = field(default_factory=list)  # 거주지 제한(시도명). 비면 전국.
    income_max_won: int | None = None                 # 개인 연소득 상한(원)
    income_note: str = ""                             # 소득조건 부연(가구/재산 등은 criteria)
    employment_in: list[str] = field(default_factory=list)   # 허용 취업상태(비면 무관)
    employment_not: list[str] = field(default_factory=list)  # 배제 취업상태
    criteria: list[Criterion] = field(default_factory=list)  # 정성 조건(manual)

    def to_chunk(self) -> Chunk:
        body = (f"{self.summary} 지원내용: {self.support_content} "
                f"분류: {self.category}/{self.subcategory}. 주관: {self.agency or self.source}. "
                f"연령: {self._age_text()}. 지역: {self._region_text()}. "
                f"소득: {self.income_note or ('개인 연소득 ' + f'{self.income_max_won:,}원 이하' if self.income_max_won else '별도 제한 명시 없음')}.")
        return Chunk(id=self.id, title=self.name, source=f"{self.source} ({self.as_of} 기준)",
                     context=self.blurb, body=body, domain=self.category)

    def _age_text(self) -> str:
        if self.age_min is None and self.age_max is None:
            return "제한 없음"
        lo = self.age_min if self.age_min is not None else "-"
        hi = self.age_max if self.age_max is not None else "-"
        return f"만 {lo}~{hi}세"

    def _region_text(self) -> str:
        return "전국" if not self.regions else "·".join(self.regions)

    def detail(self) -> dict:
        """get_policy_detail 툴 반환용."""
        return {
            "policy_id": self.id,
            "name": self.name,
            "category": self.category,
            "subcategory": self.subcategory,
            "summary": self.summary,
            "support_content": self.support_content,
            "agency": self.agency or self.source,
            "apply_period": self.apply_period or "공고 확인 필요",
            "how_to_apply": self.how_to_apply or "공고 확인 필요",
            "documents": self.documents or "공고 확인 필요",
            "apply_url": self.apply_url,
            "eligibility_summary": {
                "age": self._age_text(),
                "regions": self._region_text(),
                "income": self.income_note or (
                    f"개인 연소득 {self.income_max_won:,}원 이하" if self.income_max_won else "별도 제한 명시 없음"),
                "employment_required": self.employment_in or None,
                "employment_excluded": self.employment_not or None,
                "other_criteria": [c.text for c in self.criteria],
            },
            "source": self.source,
            "as_of": self.as_of,
            "note": "수치·조건은 기준일 이후 변동될 수 있습니다. 신청 전 최신 공고(apply_url)를 반드시 확인하세요.",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 큐레이션된 대표 청년정책 10선 (2026-07 기준 WebSearch 사실확인)
# ─────────────────────────────────────────────────────────────────────────────
POLICIES: list[Policy] = [

    Policy(
        id="youth-monthly-rent",
        name="청년월세 특별지원",
        category="주거",
        subcategory="주거비 지원",
        summary="무주택 청년에게 월세 일부를 지원해 주거비 부담을 덜어주는 국토교통부 사업.",
        support_content="월 최대 20만원씩 최장 24개월간 실제 납부 월세를 지원(생애 1회).",
        blurb="독립해 월세를 내는 만 19~34세 무주택 청년 대상 월세 지원. 소득·재산 기준 충족 시 신청.",
        source="국토교통부 청년월세 특별지원",
        as_of="2026-07",
        agency="국토교통부(복지로 신청)",
        apply_url="https://www.bokjiro.go.kr",
        apply_period="2026년부터 상시 신청(연중). 세부 일정은 복지로 공고 확인.",
        how_to_apply="복지로 온라인 신청 또는 주소지 행정복지센터 방문.",
        documents="월세 임대차계약서, 최근 3개월 월세 이체 증빙, 소득·재산 확인 서류 등.",
        age_min=19, age_max=34,
        income_note=("청년가구 소득 기준 중위소득 60% 이하 + 원가구 100% 이하(부모 포함), "
                     "청년가구 총재산 1.22억원 이하 등 — 가구 단위 판정 필요."),
        criteria=[
            Criterion("no_house", "무주택자여야 함(본인 명의 주택 소유 시 제외).",
                      "현재 본인 명의로 소유한 주택이 있나요?"),
            Criterion("independent_rent", "부모와 별도 거주하며 실제 월세를 납부하는 임차인이어야 함.",
                      "부모님과 따로 살며 월세를 직접 내고 있나요? (보증금·월세 금액은?)"),
            Criterion("household_income",
                      "청년가구 중위소득 60%·원가구 100% 이하 등 가구 소득/재산 기준 충족 필요.",
                      "본인 가구원 수와 가구 월소득, 부모님 가구 소득은 어느 정도인가요?"),
        ],
    ),

    Policy(
        id="youth-leap-account",
        name="청년도약계좌",
        category="금융",
        subcategory="자산형성",
        summary="청년이 매달 납입하면 정부기여금 매칭 + 이자 비과세로 목돈 마련을 돕는 정책형 장기저축.",
        support_content="매월 최대 약 3.3만원의 정부기여금 매칭 + 이자소득 전액 비과세(만기 5년).",
        blurb=("총급여 7,500만원 이하 만 19~34세 청년의 5년 목돈 마련 적금. "
               "⚠️ 신규 가입은 2025-12 종료 — 후속 상품 '청년미래적금'으로 승계."),
        source="서민금융진흥원 청년도약계좌",
        as_of="2026-07",
        agency="서민금융진흥원 / 취급은행",
        apply_url="https://ylaccount.kinfa.or.kr",
        apply_period="신규 가입 종료(2025-12). 2026-06 후속상품 청년미래적금 참고.",
        how_to_apply="취급은행 앱에서 가입 신청 후 자격 심사(신규 접수는 종료 상태).",
        age_min=19, age_max=34,
        income_max_won=75_000_000,
        income_note=("직전 과세기간 총급여 7,500만원 이하(종합소득 6,300만원 이하), "
                     "가구소득 기준 중위소득 이하 요건 병행. 병역기간은 연령에서 제외."),
        criteria=[
            Criterion("household_income", "가구소득 기준 중위소득 이하 요건 병행 확인 필요.",
                      "본인 가구원 수와 가구 소득 수준은 어느 정도인가요?"),
            Criterion("new_signup_closed", "신규 가입 접수는 2025-12 종료. 후속 청년미래적금 가능 여부 확인.",
                      "이미 청년도약계좌에 가입되어 있나요, 아니면 신규 가입을 원하나요?"),
        ],
    ),

    Policy(
        id="youth-future-savings",
        name="청년미래적금",
        category="금융",
        subcategory="자산형성",
        summary="청년도약계좌 후속으로 2026년 출시된 정책형 적금. 정부기여금·비과세 혜택 제공.",
        support_content="정부기여금 매칭 + 비과세(구체 매칭율·한도는 출시 공고 확인).",
        blurb=("만 19~34세, 총급여 7,500만원(종합소득 6,300만원) 이하 또는 연매출 3억원 이하 "
               "소상공인 청년 대상 2026년 신규 자산형성 적금."),
        source="서민금융진흥원 청년미래적금",
        as_of="2026-07",
        agency="서민금융진흥원 / 취급은행",
        apply_url="https://ylaccount.kinfa.or.kr",
        apply_period="2026-06 출시. 세부 신청 일정은 취급은행·서금원 공고 확인.",
        how_to_apply="취급은행 앱에서 가입 신청 후 자격 심사.",
        age_min=19, age_max=34,
        income_max_won=75_000_000,
        income_note=("총급여 7,500만원(종합소득 6,300만원) 이하 또는 연매출 3억원 이하 소상공인. "
                     "가구 기준 중위소득 200%(맞벌이 2인 250%) 이하."),
        criteria=[
            Criterion("household_income", "가구 중위소득 200%(맞벌이 2인 250%) 이하 확인 필요.",
                      "가구원 수와 가구 합산 소득은 어느 정도인가요?"),
            Criterion("exact_terms", "정부기여금 매칭율·한도 등 세부 조건은 출시 공고 확인 필요.", ""),
        ],
    ),

    Policy(
        id="youth-tomorrow-savings",
        name="청년내일저축계좌",
        category="복지",
        subcategory="자산형성",
        summary="일하는 저소득 청년의 자산형성을 돕는 보건복지부 사업. 본인 저축에 정부가 매칭 적립.",
        support_content="본인 월 10만원 저축 시 정부 매칭 적립(3년 만기 시 목돈). 매칭 규모는 소득구간별 상이.",
        blurb=("근로·사업소득이 있는 만 15~39세 저소득 청년의 3년 자산형성 계좌. "
               "2026년부터 가구소득 기준이 중위 50% 이하로 강화."),
        source="보건복지부 청년내일저축계좌",
        as_of="2026-07",
        agency="보건복지부(복지로 신청)",
        apply_url="https://www.bokjiro.go.kr",
        apply_period="연 1회 집중 신청(2026년 예: 5월). 정확한 일정은 복지로 공고 확인.",
        how_to_apply="복지로 온라인 또는 행정복지센터 방문 신청.",
        age_min=15, age_max=39,
        income_note=("본인 월 근로·사업소득 10만원 이상. 가구소득 기준 중위소득 50% 이하"
                     "(2026년 강화). 재산 기준 병행."),
        employment_not=[EMP_UNEMPLOYED],
        criteria=[
            Criterion("working_income", "본인 월 근로·사업소득 10만원 이상 필요.",
                      "현재 일해서 버는 월 소득이 10만원 이상 있나요?"),
            Criterion("household_income", "가구소득 중위 50% 이하(2026 강화) + 재산 기준 확인 필요.",
                      "가구원 수와 가구 소득 수준은 어느 정도인가요?"),
        ],
    ),

    Policy(
        id="national-employment-support",
        name="국민취업지원제도",
        category="일자리",
        subcategory="취업지원",
        summary="구직자에게 취업지원 서비스와 구직촉진수당을 제공하는 고용노동부 한국형 실업부조.",
        support_content="I유형 참여자에게 구직촉진수당 월 50~90만원을 최대 6개월 지원 + 취업지원 서비스.",
        blurb=("취업을 준비하는 만 15~69세 구직자(청년 특례 포함) 대상 취업지원·수당. "
               "소득·재산·취업경험 요건에 따라 I/II 유형으로 구분."),
        source="고용노동부 국민취업지원제도",
        as_of="2026-07",
        agency="고용노동부 / 고용센터",
        apply_url="https://www.work24.go.kr",
        apply_period="상시 신청(연중).",
        how_to_apply="워크넷 구직 등록 후 고용24(work24)에서 취업지원 신청.",
        age_min=15, age_max=69,
        employment_in=[EMP_JOBSEEKER, EMP_UNEMPLOYED],
        income_note=("I유형(요건심사형): 가구 중위소득 60% 이하 + 재산 기준(청년 5억 이하) + "
                     "최근 2년 100일/800시간 취업경험. 청년 특례로 소득·재산 완화 적용."),
        criteria=[
            Criterion("household_income", "가구 중위소득·재산·취업경험 요건으로 유형이 갈림.",
                      "가구 소득 수준과 최근 2년 취업 경험(일한 기간)이 어느 정도인가요?"),
        ],
    ),

    Policy(
        id="seoul-youth-allowance",
        name="서울 청년수당",
        category="일자리",
        subcategory="구직활동지원",
        summary="서울 거주 미취업 청년의 구직활동을 돕는 서울시 사업. 활동지원금 + 성장 프로그램 제공.",
        support_content="매월 50만원을 최대 6개월 지원 + 맞춤형 성장 프로그램(멘토링·특강 등).",
        blurb=("서울에 사는 만 19~34세 미취업·졸업 청년 대상 월 50만원 구직활동 지원금. "
               "가구 중위소득 150% 이하."),
        source="서울시 청년수당(청년몽땅정보통)",
        as_of="2026-07",
        agency="서울특별시",
        apply_url="https://youth.seoul.go.kr",
        apply_period="연 1회 집중 모집(2026년 예: 3월). 청년몽땅정보통 공고 확인.",
        how_to_apply="청년몽땅정보통에서 온라인 신청.",
        regions=["서울", "서울특별시"],
        age_min=19, age_max=34,
        employment_not=[EMP_EMPLOYED, EMP_SELF],
        income_note="가구 소득 기준 중위소득 150% 이하(건강보험료 기준).",
        criteria=[
            Criterion("resident_seoul", "서울시 거주(주민등록) 요건.", "현재 서울에 주민등록이 되어 있나요?"),
            Criterion("graduated_unemployed", "최종학력 졸업 + 미취업 상태(주 30시간 이하 단기근로는 미취업 인정).",
                      "학교는 졸업했나요? 현재 취업(주 30시간 초과 근로) 상태인가요?"),
            Criterion("household_income", "가구 중위소득 150% 이하 확인 필요.",
                      "가구원 수와 가구 소득 수준은 어느 정도인가요?"),
        ],
    ),

    Policy(
        id="youth-housing-dream-account",
        name="청년 주택드림 청약통장",
        category="주거",
        subcategory="주택청약",
        summary="청년의 내 집 마련을 돕는 우대 청약통장. 높은 우대금리 + 소득공제 + 연계 저리대출.",
        support_content="납입 원금에 최대 연 4.5% 우대금리, 무주택 세대주 소득공제(연 최대 300만원 납입의 40%), 주택드림 대출 연계.",
        blurb=("만 19~34세 무주택 청년, 연소득 5,000만원 이하의 우대형 청약통장. "
               "월 최대 100만원 납입 가능."),
        source="주택도시기금 청년 주택드림 청약통장",
        as_of="2026-07",
        agency="국토교통부 / 주택도시기금 취급은행",
        apply_url="https://nhuf.molit.go.kr",
        apply_period="상시 가입.",
        how_to_apply="취급은행(우리·국민 등) 지점·앱에서 가입/전환.",
        age_min=19, age_max=34,
        income_max_won=50_000_000,
        income_note="연소득 5,000만원 이하(근로소득 기준; 종합소득 4,000만원 이하 자영업 포함).",
        criteria=[
            Criterion("no_house", "무주택자여야 함(세대주 여부는 무관, 소득공제는 무주택 세대주에 한함).",
                      "현재 본인 명의로 소유한 주택이 있나요?"),
        ],
    ),

    Policy(
        id="jeonse-guarantee-fee-support",
        name="청년 전세보증금 반환보증 보증료 지원",
        category="주거",
        subcategory="전세지원",
        summary="전세사기 예방을 위한 반환보증 가입 청년에게 보증료를 환급해 주는 사업.",
        support_content="기납부한 전세보증금 반환보증 보증료를 최대 40만원까지 환급.",
        blurb=("전세보증금 3억원 이하, 연소득 5,000만원 이하의 만 19~39세 무주택 임차 청년에게 "
               "반환보증 보증료를 돌려주는 지원."),
        source="국토교통부 / HUG 전세보증금반환보증 보증료 지원",
        as_of="2026-07",
        agency="국토교통부 / 지방자치단체",
        apply_url="https://www.khug.or.kr",
        apply_period="상시(지자체별 예산 소진 시까지).",
        how_to_apply="주소지 지자체 또는 정부24에서 신청, 본인 계좌로 환급.",
        age_min=19, age_max=39,
        income_max_won=50_000_000,
        income_note="청년 연소득 5,000만원 이하(신혼부부 7,500만원, 그 외 6,000만원).",
        criteria=[
            Criterion("no_house", "무주택 임차인이어야 함.", "현재 본인 명의로 소유한 주택이 있나요?"),
            Criterion("jeonse_deposit", "전세보증금 3억원 이하 + 반환보증에 이미 가입(보증료 납부)했어야 함.",
                      "전세보증금이 3억원 이하이고, 전세보증금 반환보증에 가입해 보증료를 냈나요?"),
        ],
    ),

    Policy(
        id="k-pass-youth",
        name="K-패스 (청년 환급)",
        category="복지",
        subcategory="교통비",
        summary="대중교통비 일부를 환급해 주는 국토교통부 사업. 청년은 상향된 환급률 적용.",
        support_content="월 15회 이상 대중교통 이용 시 청년은 이용요금의 30%를 환급.",
        blurb=("전국 만 19~34세 청년의 대중교통비 30% 환급 교통카드 사업. 월 15회 이상 이용 조건."),
        source="국토교통부 대중교통비 환급 지원(K-패스)",
        as_of="2026-07",
        agency="국토교통부 / TS한국교통안전공단",
        apply_url="https://korea-pass.kr",
        apply_period="상시 가입.",
        how_to_apply="K-패스 카드 발급 후 앱/누리집에서 회원가입, 월 15회 이상 이용.",
        age_min=19, age_max=34,
        criteria=[
            Criterion("min_trips", "환급을 받으려면 한 달에 대중교통을 15회 이상 이용해야 함.",
                      "한 달에 대중교통을 15회 이상 이용하나요?"),
        ],
    ),

    Policy(
        id="climate-card-youth",
        name="기후동행카드 청년 할인",
        category="복지",
        subcategory="교통비",
        summary="서울 대중교통 무제한 정기권 기후동행카드의 청년 할인 권종.",
        support_content="만 19~39세 청년은 30일권을 7천원 할인(따릉이 미포함 5.5만원 / 포함 5.8만원)으로 이용.",
        blurb=("서울 대중교통을 무제한 이용하는 기후동행카드의 만 19~39세 청년 할인 권종. "
               "6개월마다 청년 연령 재인증 필요."),
        source="서울시 기후동행카드 청년 할인",
        as_of="2026-07",
        agency="서울특별시 / 티머니",
        apply_url="https://www.t-money.co.kr",
        apply_period="상시.",
        how_to_apply="기후동행카드 구매 후 티머니 앱에서 청년 연령 인증 → 할인 권종 충전.",
        regions=["서울", "서울특별시"],
        age_min=19, age_max=39,
        criteria=[
            Criterion("seoul_transit_use", "주로 서울 대중교통 생활권이어야 실효(서울 지하철·버스 대상).",
                      "주로 서울 지하철·버스로 출퇴근/통학하나요?"),
            Criterion("reverify", "최초 할인 후 6개월마다 청년 연령 재인증 필요.", ""),
        ],
    ),
]

POLICIES_BY_ID: dict[str, Policy] = {p.id: p for p in POLICIES}


def all_chunks() -> list[Chunk]:
    return [p.to_chunk() for p in POLICIES]


def get_policy(policy_id: str) -> Policy | None:
    return POLICIES_BY_ID.get((policy_id or "").strip())
