

from __future__ import annotations

from .base import Locale, LocaleFormatter
from .en import EnglishFormatter


_DOC_TYPE_RULES_ES: tuple = (
    ("boarding_pass",   ("tarjeta de embarque", "pase de abordar")),
    ("hotel_itinerary", ("reserva de hotel", "confirmación de reserva",
                         "reserva hotelera", "itinerario de hotel")),
    ("passport",        ("pasaporte",)),
    ("driver_license",  ("permiso de conducir", "licencia de conducir",
                         "licencia de manejo", "carnet de conducir")),
    ("id_card",         ("documento nacional de identidad", "dni",
                         "cédula de identidad", "cédula", "ine",
                         "tarjeta de identidad")),
    ("visa",            ("visado", "visa", "schengen")),
    ("tax_document",    ("declaración de impuestos",
                         "declaración de la renta",
                         "declaración de renta",
                         "declaración anual",
                         "impuesto sobre la renta",
                         "irpf")),
    ("invoice",         ("factura", "factura electrónica",
                         "núm. factura", "número de factura")),
    ("receipt",         ("recibo", "comprobante de pago",
                         "ticket de compra", "justificante")),
    ("insurance",       ("póliza de seguro", "póliza",
                         "tarjeta de seguro", "certificado de seguro")),
    ("contract",        ("contrato", "este contrato", "presente contrato")),
    ("agreement",       ("acuerdo", "convenio", "acuerdo de confidencialidad")),
    ("degree",          ("título universitario", "diploma",
                         "licenciatura", "máster", "doctorado",
                         "ingeniería en", "grado en")),
    ("certificate",     ("certificado", "se certifica que",
                         "hace constar que")),
    ("medical_record",  ("historia clínica", "historial médico",
                         "receta médica", "diagnóstico médico",
                         "informe médico")),
    ("ticket",          ("entrada de concierto", "entrada de evento",
                         "boleto", "entrada")),
)


_COUNTRY_NAMES_ES: tuple = (
    "afganistán", "albania", "alemania", "andorra", "angola",
    "arabia saudí", "arabia saudita", "argelia", "argentina", "armenia",
    "australia", "austria", "azerbaiyán", "baréin", "bangladés",
    "bélgica", "belice", "benín", "bielorrusia", "bolivia",
    "bosnia", "botsuana", "brasil", "bulgaria", "burkina faso",
    "burundi", "bután", "cabo verde", "camboya", "camerún", "canadá",
    "chad", "chile", "china", "chipre", "colombia", "comoras",
    "congo", "corea del norte", "corea del sur", "costa de marfil",
    "costa rica", "croacia", "cuba", "dinamarca", "ecuador",
    "egipto", "el salvador", "emiratos árabes unidos", "eslovaquia",
    "eslovenia", "españa", "estados unidos", "estonia", "etiopía",
    "filipinas", "finlandia", "francia", "gabón", "gambia", "georgia",
    "ghana", "grecia", "guatemala", "guinea", "haití", "honduras",
    "hungría", "india", "indonesia", "irán", "iraq", "irlanda",
    "islandia", "israel", "italia", "jamaica", "japón", "jordania",
    "kazajistán", "kenia", "kuwait", "letonia", "líbano", "liberia",
    "libia", "lituania", "luxemburgo", "madagascar", "malasia",
    "malí", "malta", "marruecos", "mauritania", "méxico", "moldavia",
    "mónaco", "mongolia", "montenegro", "mozambique", "namibia",
    "nepal", "níger", "nigeria", "noruega", "nueva zelanda",
    "omán", "países bajos", "pakistán", "palestina", "panamá",
    "paraguay", "perú", "polonia", "portugal", "qatar",
    "reino unido", "república checa", "república dominicana",
    "ruanda", "rumanía", "rusia", "senegal", "serbia", "singapur",
    "siria", "somalia", "sri lanka", "sudáfrica", "sudán", "suecia",
    "suiza", "tailandia", "taiwán", "tanzania", "tayikistán",
    "togo", "trinidad", "túnez", "turquía", "ucrania", "uganda",
    "uruguay", "uzbekistán", "venezuela", "vietnam", "yemen", "zambia",
    "zimbabue",
)


_COUNTRY_SHORT_CANON_ES: dict = {
    "estados unidos":         "United States",
    "reino unido":            "United Kingdom",
    "emiratos árabes unidos": "United Arab Emirates",
    "españa":                 "Spain",
    "alemania":               "Germany",
    "francia":                "France",
    "japón":                  "Japan",
    "china":                  "China",
    "méxico":                 "Mexico",
    "corea del sur":          "South Korea",
}


_MONTH_MAP_ES: dict = {
    "ene": 1, "enero": 1,
    "feb": 2, "febrero": 2,
    "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6,
    "jul": 7, "julio": 7,
    "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "septiembre": 9,
    "oct": 10, "octubre": 10,
    "nov": 11, "noviembre": 11,
    "dic": 12, "diciembre": 12,
}


SPANISH_LOCALE: Locale = Locale(
    locale_id="es",
    direction="ltr",
    doc_type_rules=_DOC_TYPE_RULES_ES,
    country_names=_COUNTRY_NAMES_ES,
    country_short_canon=_COUNTRY_SHORT_CANON_ES,
    month_map=_MONTH_MAP_ES,
    expiry_anchors=("fecha de caducidad", "caduca el", "válido hasta",
                    "valido hasta", "fecha de vencimiento",
                    "vence el", "expir"),
    issue_anchors=("fecha de emisión", "emitido el", "fecha de expedición",
                   "expedido el", "issue"),
    due_anchors=("fecha de vencimiento", "vence el", "a pagar antes",
                 "due"),
    boarding_anchors=("salida", "fecha de salida", "embarque",
                      "boarding"),
    check_in_anchors=("llegada", "fecha de llegada", "registro",
                      "check-in"),
    check_out_anchors=("salida", "fecha de salida", "check-out"),
    purchase_anchors=("fecha de compra", "fecha de la factura",
                      "fecha", "purchase"),
    effective_anchors=("fecha efectiva", "entra en vigor",
                       "fecha de inicio", "effective"),
    renewal_anchors=("fecha de renovación", "renovación",
                     "renewal", "expir"),
    passport_num_labels=("número de pasaporte", "núm. pasaporte",
                         "no. de pasaporte", "pasaporte no",
                         "passport no", "passport number"),
    id_num_labels=("número de identidad", "núm. dni",
                   "número de cédula", "national id",
                   "id no", "id number"),
    license_num_labels=("número de licencia", "núm. permiso",
                        "license no", "license number"),
    policy_num_labels=("número de póliza", "núm. póliza",
                       "policy no", "policy number"),
    invoice_num_labels=("número de factura", "núm. factura",
                        "factura no", "invoice no", "invoice number"),
    education_field_phrases=(
        "informática", "ciencias de la computación", "ingeniería",
        "matemáticas", "física", "administración de empresas",
        "derecho", "medicina", "biología", "química", "economía",
        "filosofía",
    ),
                                                    
    tax_form_keywords={
        "declaración de la renta": "RETURN",
        "declaración anual":       "RETURN",
        "irpf":                    "INCOME_TAX",
        "iva":                     "VAT",
        "isr":                     "INCOME_TAX",
        "rfc":                     "RFC",
    },
    date_disambiguation="DMY",
)


class SpanishFormatter(EnglishFormatter):


    locale_id = "es"

    def severity_label(self, level: str) -> str:
        return {
            "critical": "Crítico",
            "warning":  "Advertencia",
            "info":     "Info",
        }.get((level or "").lower(), (level or "").title())

    def expiry_phrase(self, doc_label: str, days_until: int) -> str:
        if days_until < 0:
            n = abs(days_until)
            unit = "día" if n == 1 else "días"
            return f"{doc_label} expiró hace {n} {unit}"
        if days_until == 0:
            return f"{doc_label} expira hoy"
        unit = "día" if days_until == 1 else "días"
        return f"{doc_label} expira en {days_until} {unit}"

    def doc_type_label(self, doc_type: str) -> str:
        return {
            "passport":         "Pasaporte",
            "visa":             "Visado",
            "id_card":          "DNI",
            "driver_license":   "Permiso de conducir",
            "boarding_pass":    "Tarjeta de embarque",
            "hotel_itinerary":  "Reserva de hotel",
            "ticket":           "Entrada",
            "invoice":          "Factura",
            "receipt":          "Recibo",
            "contract":         "Contrato",
            "agreement":        "Acuerdo",
            "degree":           "Título universitario",
            "certificate":      "Certificado",
            "insurance":        "Seguro",
            "tax_document":     "Documento fiscal",
            "medical_record":   "Historial médico",
        }.get(doc_type, super().doc_type_label(doc_type))


SPANISH_FORMATTER: LocaleFormatter = SpanishFormatter()
