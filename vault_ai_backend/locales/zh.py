

from __future__ import annotations

from .base import Locale, LocaleFormatter
from .en import EnglishFormatter


_DOC_TYPE_RULES_ZH: tuple = (
    ("boarding_pass",   ("登机牌",)),
    ("hotel_itinerary", ("酒店预订", "宾馆预订", "预订确认")),
    ("passport",        ("护照",)),
    ("driver_license",  ("驾驶证", "驾照", "机动车驾驶证")),
    ("id_card",         ("身份证", "居民身份证")),
    ("visa",            ("签证", "申根签证")),
    ("tax_document",    ("个人所得税申报",
                         "个人所得税",
                         "增值税申报",
                         "纳税申报")),
    ("invoice",         ("发票", "增值税发票", "电子发票")),
    ("receipt",         ("收据", "收条")),
    ("insurance",       ("保险单", "保险合同",
                         "健康保险卡", "保险凭证")),
    ("contract",        ("合同", "本合同", "劳动合同")),
    ("agreement",       ("协议", "保密协议", "谅解备忘录")),
    ("degree",          ("毕业证书", "学位证书", "学士",
                         "硕士", "博士", "文凭")),
    ("certificate",     ("证书", "兹证明", "证明")),
    ("medical_record",  ("病历", "处方", "诊断书",
                         "医疗记录")),
    ("ticket",          ("音乐会门票", "活动门票", "门票")),
)


_COUNTRY_NAMES_ZH: tuple = (
    "中国", "中华人民共和国", "香港", "澳门", "台湾",
    "日本", "韩国", "大韩民国", "朝鲜", "蒙古",
    "美国", "美利坚合众国", "加拿大", "墨西哥", "巴西",
    "阿根廷", "英国", "英格兰", "法国", "德国",
    "意大利", "西班牙", "葡萄牙", "荷兰", "比利时",
    "瑞士", "奥地利", "瑞典", "挪威", "丹麦",
    "芬兰", "爱尔兰", "希腊", "波兰", "捷克",
    "匈牙利", "俄罗斯", "乌克兰", "土耳其", "以色列",
    "沙特阿拉伯", "阿联酋", "卡塔尔", "科威特", "阿曼",
    "伊朗", "伊拉克", "约旦", "黎巴嫩", "埃及",
    "摩洛哥", "阿尔及利亚", "突尼斯", "南非", "尼日利亚",
    "肯尼亚", "埃塞俄比亚", "加纳",
    "印度", "巴基斯坦", "孟加拉国", "斯里兰卡", "尼泊尔",
    "缅甸", "泰国", "越南", "菲律宾", "印度尼西亚",
    "马来西亚", "新加坡", "柬埔寨",
    "澳大利亚", "新西兰",
)


_COUNTRY_SHORT_CANON_ZH: dict = {
    "美国":         "United States",
    "美利坚合众国": "United States",
    "英国":         "United Kingdom",
    "英格兰":       "United Kingdom",
    "阿联酋":       "United Arab Emirates",
    "中国":         "China",
    "中华人民共和国": "China",
    "日本":         "Japan",
    "韩国":         "South Korea",
    "大韩民国":     "South Korea",
    "德国":         "Germany",
    "法国":         "France",
    "西班牙":       "Spain",
    "卡塔尔":       "Qatar",
}


_MONTH_MAP_ZH: dict = {
                                   
    "1月": 1, "01月": 1,  "2月": 2,  "02月": 2,  "3月": 3,  "03月": 3,
    "4月": 4, "04月": 4,  "5月": 5,  "05月": 5,  "6月": 6,  "06月": 6,
    "7月": 7, "07月": 7,  "8月": 8,  "08月": 8,  "9月": 9,  "09月": 9,
    "10月": 10, "11月": 11, "12月": 12,
                                                                       
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


CHINESE_LOCALE: Locale = Locale(
    locale_id="zh",
    direction="ltr",
    doc_type_rules=_DOC_TYPE_RULES_ZH,
    country_names=_COUNTRY_NAMES_ZH,
    country_short_canon=_COUNTRY_SHORT_CANON_ZH,
    month_map=_MONTH_MAP_ZH,
    expiry_anchors=("有效期至", "到期日", "失效日期", "有效期", "expir"),
    issue_anchors=("签发日期", "发证日期", "颁发日期", "issue"),
    due_anchors=("到期日", "应付日期", "支付截止", "due"),
    boarding_anchors=("起飞", "出发日期", "登机", "boarding"),
    check_in_anchors=("入住", "到达日期", "check-in"),
    check_out_anchors=("退房", "离开日期", "check-out"),
    purchase_anchors=("购买日期", "交易日期", "日期", "purchase"),
    effective_anchors=("生效日期", "起始日期", "开始日期", "effective"),
    renewal_anchors=("续签日期", "续期", "renewal", "expir"),
    passport_num_labels=("护照号码", "护照号",
                         "passport no", "passport number"),
    id_num_labels=("身份证号", "公民身份号码",
                   "national id", "id no", "id number"),
    license_num_labels=("驾照号码", "驾驶证号",
                        "license no", "license number"),
    policy_num_labels=("保单号", "保险单号",
                       "policy no", "policy number"),
    invoice_num_labels=("发票号码", "发票号",
                        "invoice no", "invoice number"),
    education_field_phrases=(
        "计算机科学", "计算机", "软件工程", "信息工程",
        "工程", "数学", "物理学", "工商管理", "法学",
        "医学", "生物学", "化学", "经济学",
    ),
    tax_form_keywords={
        "个人所得税申报": "RETURN",
        "增值税申报":     "VAT",
        "个人所得税":     "INCOME_TAX",
    },
    date_disambiguation="YMD",
)


class ChineseFormatter(EnglishFormatter):


    locale_id = "zh"

    def severity_label(self, level: str) -> str:
        return {
            "critical": "紧急",
            "warning":  "警告",
            "info":     "信息",
        }.get((level or "").lower(), (level or "").title())

    def expiry_phrase(self, doc_label: str, days_until: int) -> str:
        if days_until < 0:
            return f"{doc_label}已于{abs(days_until)}天前过期"
        if days_until == 0:
            return f"{doc_label}今天到期"
        return f"{doc_label}将在{days_until}天后到期"

    def doc_type_label(self, doc_type: str) -> str:
        return {
            "passport":         "护照",
            "visa":             "签证",
            "id_card":          "身份证",
            "driver_license":   "驾驶证",
            "boarding_pass":    "登机牌",
            "hotel_itinerary":  "酒店预订",
            "ticket":           "门票",
            "invoice":          "发票",
            "receipt":          "收据",
            "contract":         "合同",
            "agreement":        "协议",
            "degree":           "毕业证书",
            "certificate":      "证书",
            "insurance":        "保险",
            "tax_document":     "税务文件",
            "medical_record":   "病历",
        }.get(doc_type, super().doc_type_label(doc_type))


CHINESE_FORMATTER: LocaleFormatter = ChineseFormatter()
