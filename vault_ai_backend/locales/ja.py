

from __future__ import annotations

from .base import Locale, LocaleFormatter
from .en import EnglishFormatter


_DOC_TYPE_RULES_JA: tuple = (
    ("boarding_pass",   ("搭乗券", "ボーディングパス")),
    ("hotel_itinerary", ("ホテル予約", "宿泊予約", "予約確認")),
    ("passport",        ("パスポート", "旅券")),
    ("driver_license",  ("運転免許証", "運転免許")),
    ("id_card",         ("身分証明書", "マイナンバーカード",
                         "個人番号カード", "在留カード")),
    ("visa",            ("ビザ", "査証", "シェンゲン")),
    ("tax_document",    ("確定申告", "源泉徴収票", "所得税",
                         "消費税申告書", "住民税")),
    ("invoice",         ("請求書", "インボイス", "請求番号")),
    ("receipt",         ("領収書", "レシート", "領収証")),
    ("insurance",       ("保険証券", "保険証書", "健康保険証",
                         "保険契約")),
    ("contract",        ("契約書", "業務委託契約", "この契約")),
    ("agreement",       ("合意書", "覚書", "秘密保持契約")),
    ("degree",          ("卒業証書", "卒業証明書", "学士",
                         "修士", "博士", "ディプロマ")),
    ("certificate",     ("証明書", "を証明する", "認定証")),
    ("medical_record",  ("診療録", "カルテ", "処方箋",
                         "診断書", "医療記録")),
    ("ticket",          ("コンサートチケット", "イベントチケット",
                         "チケット")),
)


_COUNTRY_NAMES_JA: tuple = (
    "日本", "アメリカ", "アメリカ合衆国", "米国", "中国",
    "韓国", "大韓民国", "北朝鮮", "台湾", "香港",
    "イギリス", "英国", "フランス", "ドイツ", "イタリア",
    "スペイン", "ポルトガル", "オランダ", "ベルギー", "スイス",
    "オーストリア", "スウェーデン", "ノルウェー", "デンマーク",
    "フィンランド", "アイルランド", "ギリシャ", "ポーランド",
    "ロシア", "ウクライナ", "トルコ", "イスラエル", "サウジアラビア",
    "アラブ首長国連邦", "カタール", "クウェート", "オマーン",
    "イラン", "イラク", "ヨルダン", "レバノン", "エジプト",
    "モロッコ", "アルジェリア", "チュニジア", "南アフリカ",
    "ナイジェリア", "ケニア", "エチオピア", "ガーナ", "セネガル",
    "ブラジル", "メキシコ", "アルゼンチン", "チリ", "コロンビア",
    "ペルー", "ベネズエラ", "カナダ", "オーストラリア",
    "ニュージーランド", "インド", "パキスタン", "バングラデシュ",
    "スリランカ", "ネパール", "ミャンマー", "タイ", "ベトナム",
    "フィリピン", "インドネシア", "マレーシア", "シンガポール",
    "カンボジア",
)


_COUNTRY_SHORT_CANON_JA: dict = {
    "アメリカ":         "United States",
    "アメリカ合衆国":   "United States",
    "米国":             "United States",
    "イギリス":         "United Kingdom",
    "英国":             "United Kingdom",
    "アラブ首長国連邦": "United Arab Emirates",
    "日本":             "Japan",
    "中国":             "China",
    "韓国":             "South Korea",
    "大韓民国":         "South Korea",
    "ドイツ":           "Germany",
    "フランス":         "France",
    "スペイン":         "Spain",
}


_MONTH_MAP_JA: dict = {
                                    
    "1月": 1, "01月": 1,  "2月": 2,  "02月": 2,  "3月": 3,  "03月": 3,
    "4月": 4, "04月": 4,  "5月": 5,  "05月": 5,  "6月": 6,  "06月": 6,
    "7月": 7, "07月": 7,  "8月": 8,  "08月": 8,  "9月": 9,  "09月": 9,
    "10月": 10, "11月": 11, "12月": 12,
                                                                 
            
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


JAPANESE_LOCALE: Locale = Locale(
    locale_id="ja",
    direction="ltr",
    doc_type_rules=_DOC_TYPE_RULES_JA,
    country_names=_COUNTRY_NAMES_JA,
    country_short_canon=_COUNTRY_SHORT_CANON_JA,
    month_map=_MONTH_MAP_JA,
    expiry_anchors=("有効期限", "期限", "有効期間", "満了日", "expir"),
    issue_anchors=("発行日", "交付日", "発効日", "issue"),
    due_anchors=("支払期日", "お支払い期限", "請求期日", "due"),
    boarding_anchors=("出発", "出発日", "搭乗", "boarding"),
    check_in_anchors=("チェックイン", "到着", "到着日", "check-in"),
    check_out_anchors=("チェックアウト", "出発", "出発日", "check-out"),
    purchase_anchors=("購入日", "ご利用日", "発行日", "日付", "purchase"),
    effective_anchors=("発効日", "開始日", "適用開始日", "effective"),
    renewal_anchors=("更新日", "更新", "renewal", "expir"),
    passport_num_labels=("旅券番号", "パスポート番号",
                         "passport no", "passport number"),
    id_num_labels=("身分証明書番号", "個人番号",
                   "national id", "id no", "id number"),
    license_num_labels=("免許証番号", "運転免許証番号",
                        "license no", "license number"),
    policy_num_labels=("証券番号", "保険証券番号",
                       "policy no", "policy number"),
    invoice_num_labels=("請求書番号", "請求番号",
                        "invoice no", "invoice number"),
    education_field_phrases=(
        "情報工学", "計算機科学", "コンピューターサイエンス",
        "工学", "数学", "物理学", "経営学", "法学", "医学",
        "生物学", "化学", "経済学",
    ),
    tax_form_keywords={
        "確定申告":       "RETURN",
        "源泉徴収票":     "WITHHOLDING_SLIP",
        "所得税":         "INCOME_TAX",
        "消費税申告書":   "VAT",
        "住民税":         "RESIDENT_TAX",
    },
    date_disambiguation="YMD",
)


class JapaneseFormatter(EnglishFormatter):


    locale_id = "ja"

    def severity_label(self, level: str) -> str:
        return {
            "critical": "重要",
            "warning":  "警告",
            "info":     "情報",
        }.get((level or "").lower(), (level or "").title())

    def expiry_phrase(self, doc_label: str, days_until: int) -> str:
        if days_until < 0:
            return f"{doc_label}は{abs(days_until)}日前に期限切れになりました"
        if days_until == 0:
            return f"{doc_label}は本日期限切れです"
        return f"{doc_label}はあと{days_until}日で期限切れになります"

    def doc_type_label(self, doc_type: str) -> str:
        return {
            "passport":         "パスポート",
            "visa":             "ビザ",
            "id_card":          "身分証明書",
            "driver_license":   "運転免許証",
            "boarding_pass":    "搭乗券",
            "hotel_itinerary":  "ホテル予約",
            "ticket":           "チケット",
            "invoice":          "請求書",
            "receipt":          "領収書",
            "contract":         "契約書",
            "agreement":        "合意書",
            "degree":           "学位証書",
            "certificate":      "証明書",
            "insurance":        "保険",
            "tax_document":     "税務書類",
            "medical_record":   "診療記録",
        }.get(doc_type, super().doc_type_label(doc_type))


JAPANESE_FORMATTER: LocaleFormatter = JapaneseFormatter()
