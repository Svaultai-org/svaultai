

from __future__ import annotations

from .base import Locale, LocaleFormatter
from .en import EnglishFormatter


_DOC_TYPE_RULES_FR: tuple = (
    ("boarding_pass",   ("carte d'embarquement", "carte d embarquement",
                         "carte de débarquement")),
    ("hotel_itinerary", ("réservation d'hôtel", "réservation hôtel",
                         "confirmation de réservation",
                         "confirmation de séjour")),
    ("passport",        ("passeport",)),
    ("driver_license",  ("permis de conduire", "permis conduire")),
    ("id_card",         ("carte nationale d'identité",
                         "carte d'identité", "carte identite",
                         "carte d identite", "cni")),
    ("visa",            ("visa", "schengen")),
    ("tax_document",    ("déclaration d'impôts", "déclaration impôts",
                         "avis d'imposition", "feuille d'impôts",
                         "impôt sur le revenu")),
    ("invoice",         ("facture", "facturer à", "n° facture")),
    ("receipt",         ("reçu", "ticket de caisse", "justificatif")),
    ("insurance",       ("police d'assurance", "contrat d'assurance",
                         "carte d'assurance", "attestation d'assurance")),
    ("contract",        ("contrat", "ce contrat", "présent contrat")),
    ("agreement",       ("accord", "convention", "accord de confidentialité")),
    ("degree",          ("diplôme", "licence", "master", "doctorat",
                         "baccalauréat")),
    ("certificate",     ("certificat", "atteste que", "certifie que")),
    ("medical_record",  ("dossier médical", "ordonnance",
                         "prescription médicale", "diagnostic")),
    ("ticket",          ("billet d'événement", "billet de concert",
                         "billet")),
)


_COUNTRY_NAMES_FR: tuple = (
    "afghanistan", "afrique du sud", "albanie", "algérie", "allemagne",
    "andorre", "angleterre", "angola", "arabie saoudite", "argentine",
    "arménie", "australie", "autriche", "azerbaïdjan", "bahreïn",
    "bangladesh", "belgique", "bénin", "bolivie", "brésil",
    "bulgarie", "burkina faso", "cambodge", "cameroun", "canada",
    "chili", "chine", "chypre", "colombie", "corée du nord",
    "corée du sud", "costa rica", "côte d'ivoire", "croatie", "cuba",
    "danemark", "djibouti", "égypte", "émirats arabes unis",
    "équateur", "espagne", "estonie", "états-unis", "éthiopie",
    "finlande", "france", "gabon", "géorgie", "ghana", "grèce",
    "guatemala", "guinée", "haïti", "honduras", "hongrie", "inde",
    "indonésie", "iran", "iraq", "irlande", "islande", "israël",
    "italie", "jamaïque", "japon", "jordanie", "kazakhstan", "kenya",
    "koweït", "laos", "lettonie", "liban", "libye", "lituanie",
    "luxembourg", "madagascar", "malaisie", "mali", "malte", "maroc",
    "mauritanie", "mexique", "moldavie", "mongolie", "monténégro",
    "mozambique", "namibie", "nepal", "népal", "niger", "nigéria",
    "norvège", "nouvelle-zélande", "oman", "ouganda", "ouzbékistan",
    "pakistan", "palestine", "panama", "paraguay", "pays-bas", "pérou",
    "philippines", "pologne", "portugal", "qatar", "république tchèque",
    "roumanie", "royaume-uni", "russie", "rwanda", "sénégal",
    "serbie", "singapour", "slovaquie", "slovénie", "somalie",
    "soudan", "sri lanka", "suède", "suisse", "syrie", "taïwan",
    "tchad", "thaïlande", "togo", "tunisie", "turquie", "ukraine",
    "uruguay", "venezuela", "vietnam", "yémen", "zambie", "zimbabwe",
)


_COUNTRY_SHORT_CANON_FR: dict = {
    "états-unis":          "United States",
    "royaume-uni":         "United Kingdom",
    "émirats arabes unis": "United Arab Emirates",
    "allemagne":           "Germany",
    "espagne":             "Spain",
    "italie":              "Italy",
    "japon":               "Japan",
    "chine":               "China",
    "corée du sud":        "South Korea",
}


_MONTH_MAP_FR: dict = {
    "janv": 1, "janvier": 1,
    "févr": 2, "fevr": 2, "février": 2, "fevrier": 2,
    "mars": 3,
    "avr": 4, "avril": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7, "juillet": 7,
    "août": 8, "aout": 8,
    "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10,
    "nov": 11, "novembre": 11,
    "déc": 12, "dec": 12, "décembre": 12, "decembre": 12,
}


FRENCH_LOCALE: Locale = Locale(
    locale_id="fr",
    direction="ltr",
    doc_type_rules=_DOC_TYPE_RULES_FR,
    country_names=_COUNTRY_NAMES_FR,
    country_short_canon=_COUNTRY_SHORT_CANON_FR,
    month_map=_MONTH_MAP_FR,
    expiry_anchors=("date d'expiration", "expire le", "valable jusqu'au",
                    "valable jusqu", "fin de validité", "expir"),
    issue_anchors=("date de délivrance", "délivré le", "émis le",
                   "date d'émission", "issue"),
    due_anchors=("date d'échéance", "échéance", "à régler avant",
                 "due"),
    boarding_anchors=("départ", "embarquement", "date de départ",
                      "boarding"),
    check_in_anchors=("arrivée", "date d'arrivée", "enregistrement",
                      "check-in"),
    check_out_anchors=("départ", "date de départ", "check-out"),
    purchase_anchors=("date d'achat", "date de la facture",
                      "date", "purchase"),
    effective_anchors=("date d'effet", "prend effet le",
                       "entrée en vigueur", "effective"),
    renewal_anchors=("date de renouvellement", "renouvellement",
                     "renewal", "expir"),
    passport_num_labels=("numéro de passeport", "n° passeport",
                         "passeport n°", "passport no", "passport number"),
    id_num_labels=("numéro d'identité", "n° d'identité",
                   "numéro de carte", "national id", "id no", "id number"),
    license_num_labels=("numéro de permis", "n° permis",
                        "license no", "license number"),
    policy_num_labels=("numéro de police", "n° police",
                       "policy no", "policy number"),
    invoice_num_labels=("numéro de facture", "n° facture",
                        "invoice no", "invoice number"),
    education_field_phrases=(
        "informatique", "ingénierie", "mathématiques", "physique",
        "commerce", "droit", "médecine", "biologie", "chimie",
        "économie", "lettres", "philosophie",
    ),
                                                     
    tax_form_keywords={
        "déclaration d'impôts":  "RETURN",
        "avis d'imposition":     "ASSESSMENT",
        "impôt sur le revenu":   "INCOME_TAX",
        "tva":                   "VAT",
        "t4":                    "T4",
        "t1":                    "T1",
    },
    date_disambiguation="DMY",
)


class FrenchFormatter(EnglishFormatter):


    locale_id = "fr"

    def severity_label(self, level: str) -> str:
        return {
            "critical": "Critique",
            "warning":  "Avertissement",
            "info":     "Info",
        }.get((level or "").lower(), (level or "").title())

    def expiry_phrase(self, doc_label: str, days_until: int) -> str:
        if days_until < 0:
            n = abs(days_until)
            unit = "jour" if n == 1 else "jours"
            return f"{doc_label} a expiré il y a {n} {unit}"
        if days_until == 0:
            return f"{doc_label} expire aujourd'hui"
        unit = "jour" if days_until == 1 else "jours"
        return f"{doc_label} expire dans {days_until} {unit}"

    def doc_type_label(self, doc_type: str) -> str:
        return {
            "passport":         "Passeport",
            "visa":             "Visa",
            "id_card":          "Carte d'identité",
            "driver_license":   "Permis de conduire",
            "boarding_pass":    "Carte d'embarquement",
            "hotel_itinerary":  "Réservation d'hôtel",
            "ticket":           "Billet",
            "invoice":          "Facture",
            "receipt":          "Reçu",
            "contract":         "Contrat",
            "agreement":        "Accord",
            "degree":           "Diplôme",
            "certificate":      "Certificat",
            "insurance":        "Assurance",
            "tax_document":     "Document fiscal",
            "medical_record":   "Dossier médical",
        }.get(doc_type, super().doc_type_label(doc_type))


FRENCH_FORMATTER: LocaleFormatter = FrenchFormatter()
