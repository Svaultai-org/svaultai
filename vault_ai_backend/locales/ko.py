

from __future__ import annotations

from .base import Locale, LocaleFormatter
from .en import EnglishFormatter


_DOC_TYPE_RULES_KO: tuple = (
    ("boarding_pass",   ("탑승권", "보딩패스")),
    ("hotel_itinerary", ("호텔 예약", "호텔예약", "예약 확인")),
    ("passport",        ("여권",)),
    ("driver_license",  ("운전면허증", "운전면허")),
    ("id_card",         ("주민등록증", "신분증", "외국인등록증")),
    ("visa",            ("비자", "사증", "셰겐")),
    ("tax_document",    ("종합소득세 신고", "소득세 신고서",
                         "부가가치세", "근로소득원천징수영수증")),
    ("invoice",         ("청구서", "세금계산서", "인보이스")),
    ("receipt",         ("영수증", "현금영수증")),
    ("insurance",       ("보험증권", "보험증서",
                         "건강보험증", "보험계약")),
    ("contract",        ("계약서", "근로계약서", "이 계약")),
    ("agreement",       ("합의서", "양해각서", "비밀유지계약")),
    ("degree",          ("졸업증서", "졸업증명서", "학사",
                         "석사", "박사", "디플로마")),
    ("certificate",     ("증명서", "확인서", "인증서",
                         "사업자등록증", "을 증명함")),
    ("medical_record",  ("진료기록", "처방전", "진단서",
                         "의료기록")),
    ("ticket",          ("콘서트 티켓", "공연 티켓", "티켓",
                         "입장권")),
)


_COUNTRY_NAMES_KO: tuple = (
    "한국", "대한민국", "북한", "조선민주주의인민공화국",
    "일본", "중국", "대만", "홍콩", "미국", "미합중국",
    "캐나다", "멕시코", "브라질", "아르헨티나",
    "영국", "잉글랜드", "프랑스", "독일", "이탈리아",
    "스페인", "포르투갈", "네덜란드", "벨기에", "스위스",
    "오스트리아", "스웨덴", "노르웨이", "덴마크", "핀란드",
    "아일랜드", "그리스", "폴란드", "체코", "헝가리",
    "러시아", "우크라이나", "터키", "이스라엘", "사우디아라비아",
    "아랍에미리트", "카타르", "쿠웨이트", "오만",
    "이란", "이라크", "요르단", "레바논", "이집트",
    "모로코", "알제리", "튀니지", "남아프리카공화국",
    "나이지리아", "케냐", "에티오피아", "가나",
    "인도", "파키스탄", "방글라데시", "스리랑카", "네팔",
    "미얀마", "태국", "베트남", "필리핀", "인도네시아",
    "말레이시아", "싱가포르", "캄보디아",
    "호주", "뉴질랜드",
)


_COUNTRY_SHORT_CANON_KO: dict = {
    "미국":         "United States",
    "미합중국":     "United States",
    "영국":         "United Kingdom",
    "잉글랜드":     "United Kingdom",
    "아랍에미리트": "United Arab Emirates",
    "한국":         "South Korea",
    "대한민국":     "South Korea",
    "일본":         "Japan",
    "중국":         "China",
    "독일":         "Germany",
    "프랑스":       "France",
    "스페인":       "Spain",
}


_MONTH_MAP_KO: dict = {
                                  
    "1월": 1, "01월": 1,  "2월": 2,  "02월": 2,  "3월": 3,  "03월": 3,
    "4월": 4, "04월": 4,  "5월": 5,  "05월": 5,  "6월": 6,  "06월": 6,
    "7월": 7, "07월": 7,  "8월": 8,  "08월": 8,  "9월": 9,  "09월": 9,
    "10월": 10, "11월": 11, "12월": 12,
                                                                   
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


KOREAN_LOCALE: Locale = Locale(
    locale_id="ko",
    direction="ltr",
    doc_type_rules=_DOC_TYPE_RULES_KO,
    country_names=_COUNTRY_NAMES_KO,
    country_short_canon=_COUNTRY_SHORT_CANON_KO,
    month_map=_MONTH_MAP_KO,
    expiry_anchors=("유효기간", "만료일", "유효기한", "expir"),
    issue_anchors=("발급일", "발행일", "교부일", "issue"),
    due_anchors=("납부기한", "지급기일", "결제기한", "due"),
    boarding_anchors=("출발", "출발일", "탑승", "boarding"),
    check_in_anchors=("체크인", "도착", "도착일", "check-in"),
    check_out_anchors=("체크아웃", "출발", "출발일", "check-out"),
    purchase_anchors=("구매일", "결제일", "발행일", "날짜", "purchase"),
    effective_anchors=("발효일", "개시일", "시행일", "effective"),
    renewal_anchors=("갱신일", "갱신", "renewal", "expir"),
    passport_num_labels=("여권번호", "여권 번호",
                         "passport no", "passport number"),
    id_num_labels=("주민등록번호", "신분증 번호", "외국인등록번호",
                   "national id", "id no", "id number"),
    license_num_labels=("면허번호", "운전면허번호",
                        "license no", "license number"),
    policy_num_labels=("증권번호", "보험증권번호",
                       "policy no", "policy number"),
    invoice_num_labels=("청구서 번호", "세금계산서 번호",
                        "invoice no", "invoice number"),
    education_field_phrases=(
        "컴퓨터공학", "전산학", "공학", "수학", "물리학",
        "경영학", "법학", "의학", "생물학", "화학", "경제학",
    ),
    tax_form_keywords={
        "종합소득세 신고":         "RETURN",
        "근로소득원천징수영수증":  "WITHHOLDING_SLIP",
        "부가가치세":              "VAT",
        "소득세":                  "INCOME_TAX",
    },
    date_disambiguation="YMD",
)


class KoreanFormatter(EnglishFormatter):


    locale_id = "ko"

    def severity_label(self, level: str) -> str:
        return {
            "critical": "긴급",
            "warning":  "경고",
            "info":     "정보",
        }.get((level or "").lower(), (level or "").title())

    def expiry_phrase(self, doc_label: str, days_until: int) -> str:
        if days_until < 0:
            return f"{doc_label}이(가) {abs(days_until)}일 전에 만료되었습니다"
        if days_until == 0:
            return f"{doc_label}이(가) 오늘 만료됩니다"
        return f"{doc_label}이(가) {days_until}일 후에 만료됩니다"

    def doc_type_label(self, doc_type: str) -> str:
        return {
            "passport":         "여권",
            "visa":             "비자",
            "id_card":          "신분증",
            "driver_license":   "운전면허증",
            "boarding_pass":    "탑승권",
            "hotel_itinerary":  "호텔 예약",
            "ticket":           "티켓",
            "invoice":          "청구서",
            "receipt":          "영수증",
            "contract":         "계약서",
            "agreement":        "합의서",
            "degree":           "졸업증서",
            "certificate":      "증명서",
            "insurance":        "보험",
            "tax_document":     "세무 서류",
            "medical_record":   "진료 기록",
        }.get(doc_type, super().doc_type_label(doc_type))


KOREAN_FORMATTER: LocaleFormatter = KoreanFormatter()
