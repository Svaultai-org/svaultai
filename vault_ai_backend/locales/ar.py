

from __future__ import annotations

from typing import Optional

from .base import Locale, LocaleFormatter
from .en import EnglishFormatter


RLM = "‏"


_DOC_TYPE_RULES_AR: tuple = (
                                                                     
    ("boarding_pass",   ("بطاقة الصعود", "بطاقة صعود الطائرة")),
    ("hotel_itinerary", ("حجز فندق", "تأكيد الحجز", "حجز الفندق",
                         "تأكيد حجز", "إقامة فندقية")),
    ("passport",        ("جواز سفر", "جواز السفر")),
    ("driver_license",  ("رخصة قيادة", "رخصة القيادة", "رخصة سياقة")),
    ("id_card",         ("بطاقة هوية", "بطاقة الهوية", "هوية وطنية",
                         "بطاقة شخصية")),
    ("visa",            ("تأشيرة", "تأشيرة دخول", "فيزا", "شنغن")),
    ("tax_document",    ("إقرار ضريبي", "إقرار الضريبة",
                         "ضريبة الدخل", "ضريبة القيمة المضافة")),
    ("invoice",         ("فاتورة", "فاتورة ضريبية", "فاتورة بيع")),
    ("receipt",         ("إيصال", "إيصال دفع", "إيصال استلام")),
    ("insurance",       ("بوليصة تأمين", "وثيقة تأمين",
                         "شهادة تأمين", "تأمين صحي")),
    ("contract",        ("عقد", "عقد عمل", "هذا العقد")),
    ("agreement",       ("اتفاقية", "اتفاقية عدم الإفصاح",
                         "مذكرة تفاهم")),
    ("degree",          ("شهادة جامعية", "شهادة بكالوريوس",
                         "شهادة ماجستير", "شهادة دكتوراه", "دبلوم")),
    ("certificate",     ("شهادة", "تشهد بأن", "هذه الشهادة تثبت")),
    ("medical_record",  ("تقرير طبي", "سجل طبي", "روشتة طبية",
                         "وصفة طبية", "تشخيص طبي")),
    ("ticket",          ("تذكرة", "تذكرة حفل", "تذكرة سفر")),
)


_COUNTRY_NAMES_AR: tuple = (
    "مصر", "السعودية", "المملكة العربية السعودية", "الإمارات",
    "الإمارات العربية المتحدة", "قطر", "الكويت", "البحرين", "عمان",
    "اليمن", "العراق", "الأردن", "سوريا", "لبنان", "فلسطين",
    "المغرب", "الجزائر", "تونس", "ليبيا", "السودان", "موريتانيا",
    "الصومال", "جيبوتي", "جزر القمر",
    "تركيا", "إيران", "أفغانستان", "باكستان", "الهند", "بنغلاديش",
    "إندونيسيا", "ماليزيا", "الصين", "اليابان", "كوريا الجنوبية",
    "كوريا الشمالية", "تايلاند", "فيتنام", "الفلبين", "سنغافورة",
    "الولايات المتحدة", "كندا", "المكسيك", "البرازيل", "الأرجنتين",
    "بريطانيا", "المملكة المتحدة", "إنجلترا", "فرنسا", "ألمانيا",
    "إيطاليا", "إسبانيا", "البرتغال", "هولندا", "بلجيكا", "سويسرا",
    "السويد", "النرويج", "الدنمارك", "فنلندا", "أيرلندا",
    "اليونان", "بولندا", "روسيا", "أوكرانيا", "أستراليا",
    "نيوزيلندا", "نيجيريا", "كينيا", "إثيوبيا", "جنوب أفريقيا",
    "غانا", "أوغندا", "تنزانيا", "السنغال",
)


_COUNTRY_SHORT_CANON_AR: dict = {
    "السعودية":   "Saudi Arabia",
    "الإمارات":   "United Arab Emirates",
    "بريطانيا":   "United Kingdom",
    "إنجلترا":    "United Kingdom",
}


_MONTH_MAP_AR: dict = {
            
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4,
    "مايو": 5, "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8,
    "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
                                                                         
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


ARABIC_LOCALE: Locale = Locale(
    locale_id="ar",
    direction="rtl",
    doc_type_rules=_DOC_TYPE_RULES_AR,
    country_names=_COUNTRY_NAMES_AR,
    country_short_canon=_COUNTRY_SHORT_CANON_AR,
    month_map=_MONTH_MAP_AR,
    expiry_anchors=("تاريخ الانتهاء", "تنتهي في", "ينتهي في",
                    "صالح حتى", "صلاحية", "expir"),
    issue_anchors=("تاريخ الإصدار", "صدرت في", "صادر في",
                   "تاريخ الاصدار", "issue"),
    due_anchors=("تاريخ الاستحقاق", "مستحق في", "due"),
    boarding_anchors=("المغادرة", "تاريخ المغادرة", "الإقلاع",
                      "boarding", "depart"),
    check_in_anchors=("تسجيل الوصول", "الوصول", "check-in",
                      "check in"),
    check_out_anchors=("تسجيل المغادرة", "المغادرة", "check-out",
                       "check out"),
    purchase_anchors=("تاريخ الشراء", "تاريخ الفاتورة",
                      "تاريخ", "purchase"),
    effective_anchors=("تاريخ السريان", "ساري من", "يبدأ في",
                       "effective"),
    renewal_anchors=("تاريخ التجديد", "يجدد في", "تجديد",
                     "renewal", "expir"),
    passport_num_labels=("رقم الجواز", "رقم جواز السفر",
                         "passport no", "passport number"),
    id_num_labels=("رقم الهوية", "رقم البطاقة", "رقم وطني",
                   "national id", "id no", "id number"),
    license_num_labels=("رقم الرخصة", "رقم رخصة القيادة",
                        "license no", "license number"),
    policy_num_labels=("رقم البوليصة", "رقم الوثيقة",
                       "policy no", "policy number"),
    invoice_num_labels=("رقم الفاتورة", "فاتورة رقم",
                        "invoice no", "invoice number"),
    education_field_phrases=(
        "علوم الحاسب", "هندسة", "هندسة كهربائية", "هندسة مدنية",
        "رياضيات", "فيزياء", "إدارة أعمال", "قانون", "طب",
        "صيدلة", "أحياء", "كيمياء", "اقتصاد",
    ),
                                                          
    tax_form_keywords={
        "إقرار ضريبي": "RETURN",
        "ضريبة القيمة المضافة": "VAT",
        "ضريبة الدخل": "INCOME_TAX",
        "زكاة": "ZAKAT",
    },
    date_disambiguation="DMY",
)


class ArabicFormatter(EnglishFormatter):


    locale_id = "ar"

    def _rtl(self, s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        return RLM + s

                   
    def expiry_status_absolute(self, iso_date):
        return self._rtl(super().expiry_status_absolute(iso_date))

    def date_relative(self, field, days_delta):
        return self._rtl(super().date_relative(field, days_delta))

                     
    def found_login(self, pretty_service):
        return self._rtl(super().found_login(pretty_service))

    def found_login_decrypt_failed(self, service_title):
        return self._rtl(super().found_login_decrypt_failed(service_title))

    def field_label(self, key):
        return self._rtl(super().field_label(key))

           
    def vault_empty(self):
        return self._rtl(super().vault_empty())

    def vault_list_header(self):
        return self._rtl(super().vault_list_header())

    def no_saved_logins(self):
        return self._rtl(super().no_saved_logins())

    def saved_logins_header(self):
        return self._rtl(super().saved_logins_header())

    def remember_header(self):
        return self._rtl(super().remember_header())

    def tag_list_header(self, tag):
        return self._rtl(super().tag_list_header(tag))

    def files_section_header(self):
        return self._rtl(super().files_section_header())

    def logins_section_header(self):
        return self._rtl(super().logins_section_header())

    def and_more_files(self, n):
        return self._rtl(super().and_more_files(n))

    def and_more_logins(self, n):
        return self._rtl(super().and_more_logins(n))

                                                 
    def severity_label(self, level: str) -> str:
        return self._rtl({
            "critical": "حرج",
            "warning":  "تحذير",
            "info":     "معلومات",
        }.get((level or "").lower(), (level or "").title()))

    def expiry_phrase(self, doc_label: str, days_until: int) -> str:
        if days_until < 0:
            n = abs(days_until)
            return self._rtl(f"{doc_label} انتهت صلاحيته منذ {n} يوم")
        if days_until == 0:
            return self._rtl(f"{doc_label} ينتهي اليوم")
        return self._rtl(f"{doc_label} ينتهي خلال {days_until} يوم")

    def doc_type_label(self, doc_type: str) -> str:
        return self._rtl({
            "passport":         "جواز السفر",
            "visa":             "التأشيرة",
            "id_card":          "بطاقة الهوية",
            "driver_license":   "رخصة القيادة",
            "boarding_pass":    "بطاقة الصعود",
            "hotel_itinerary":  "حجز الفندق",
            "ticket":           "التذكرة",
            "invoice":          "الفاتورة",
            "receipt":          "الإيصال",
            "contract":         "العقد",
            "agreement":        "الاتفاقية",
            "degree":           "الشهادة الجامعية",
            "certificate":      "الشهادة",
            "insurance":        "التأمين",
            "tax_document":     "المستند الضريبي",
            "medical_record":   "السجل الطبي",
        }.get(doc_type, super().doc_type_label(doc_type)))


ARABIC_FORMATTER: LocaleFormatter = ArabicFormatter()
