

from __future__ import annotations


ALLOWED_TAGS: tuple[str, ...] = (
    "travel", "finance", "legal", "medical", "business", "education",
    "identity", "government", "security", "personal", "media",
    "receipt", "tax",
)


ALLOWED_DOC_TYPES: tuple[str, ...] = (
    "passport", "visa", "boarding_pass", "ticket", "hotel_itinerary",
    "receipt", "invoice", "contract", "agreement", "degree",
    "certificate", "insurance", "driver_license", "id_card",
    "tax_document", "medical_record",
)


IDENTITY_DOC_TYPES:  frozenset[str] = frozenset({
    "passport", "id_card", "driver_license",
})
TRAVEL_DOC_TYPES:    frozenset[str] = frozenset({
    "passport", "visa", "boarding_pass", "ticket", "hotel_itinerary",
})
FINANCE_DOC_TYPES:   frozenset[str] = frozenset({
    "receipt", "invoice", "tax_document", "insurance",
})
LEGAL_DOC_TYPES:     frozenset[str] = frozenset({
    "contract", "agreement",
})
MEDICAL_DOC_TYPES:   frozenset[str] = frozenset({
    "insurance", "medical_record",
})
EDUCATION_DOC_TYPES: frozenset[str] = frozenset({
    "degree", "certificate",
})


DOC_TYPE_TO_TAGS: dict[str, tuple[str, ...]] = {
    "passport":        ("identity", "government", "travel"),
    "visa":            ("travel", "government"),
    "boarding_pass":   ("travel",),
    "ticket":          ("travel",),
    "hotel_itinerary": ("travel",),
    "receipt":         ("receipt", "finance"),
    "invoice":         ("receipt", "finance", "business"),
    "contract":        ("legal", "business"),
    "agreement":       ("legal",),
    "degree":          ("education",),
    "certificate":     ("education",),
    "insurance":       ("medical", "finance"),
    "driver_license":  ("identity", "government"),
    "id_card":         ("identity", "government"),
    "tax_document":    ("tax", "finance", "government"),
    "medical_record":  ("medical",),
}


ALLOWED_ASSET_TYPES: tuple[str, ...] = (
    "image", "video", "audio", "pdf", "docx", "spreadsheet",
    "id_image", "id_document", "file",
)

                                                                      
DOC_TYPE_TO_ASSET_TYPE: dict[str, str] = {
    "passport":       "id_document",
    "id_card":        "id_document",
    "driver_license": "id_document",
}


NAMING_TEXT_TO_DOC_TYPE: tuple[tuple[str, tuple[str, ...]], ...] = (
                                 
    ("driver_license", (
        "drivers license", "driver license", "driver's license",
        "driving licence", "driving license", "dl",
    )),
    ("passport", (
        "passport", "passports",
    )),
    ("id_card", (
                                                                   
                                                                
        "national id card", "national identity card", "national id",
        "national identity", "identity card", "identity document",
        "id card", "id document", "ids", "id",
    )),
    ("visa", (
        "schengen visa", "schengen", "visa",
    )),

                        
    ("boarding_pass",   ("boarding pass", "boarding-pass")),
    ("hotel_itinerary", (
        "hotel booking", "hotel reservation", "hotel itinerary",
        "booking confirmation", "reservation confirmation",
    )),
    ("ticket", (
        "event ticket", "concert ticket", "movie ticket", "ticket",
    )),

                         
    ("receipt",      ("receipts", "receipt")),
    ("invoice",      ("invoices", "invoice", "bill")),
    ("tax_document", (
        "tax return", "tax document", "tax form", "tax doc",
        "w-2", "w2 form", "w2", "1099", "irs", "tax",
    )),
    ("insurance",    (
        "insurance policy", "insurance card", "insurance",
    )),

                                  
    ("contract",  ("employment contract", "rental contract", "contract")),
    ("agreement", ("non-disclosure agreement", "nda", "agreement")),

                           
    ("degree",      ("bachelor's degree", "master's degree", "degree", "diploma")),
    ("certificate", ("certificate", "cert")),

                         
    ("medical_record", (
        "medical record", "prescription", "diagnosis", "lab result",
    )),
)


DOC_TYPE_TO_FAMILY: dict[str, str] = {}
for _dt in IDENTITY_DOC_TYPES:
    DOC_TYPE_TO_FAMILY[_dt] = "identity_document"
for _dt in (TRAVEL_DOC_TYPES - IDENTITY_DOC_TYPES):
    DOC_TYPE_TO_FAMILY[_dt] = "travel_document"
for _dt in (FINANCE_DOC_TYPES - IDENTITY_DOC_TYPES):
    DOC_TYPE_TO_FAMILY[_dt] = "financial_document"
for _dt in (LEGAL_DOC_TYPES - FINANCE_DOC_TYPES):
    DOC_TYPE_TO_FAMILY.setdefault(_dt, "legal_document")
for _dt in (MEDICAL_DOC_TYPES - FINANCE_DOC_TYPES):
    DOC_TYPE_TO_FAMILY.setdefault(_dt, "medical_document")
for _dt in EDUCATION_DOC_TYPES:
    DOC_TYPE_TO_FAMILY.setdefault(_dt, "education_document")
del _dt


ALLOWED_KEYS_BY_DOC_TYPE: dict[str, frozenset[str]] = {
    "passport":        frozenset({"country", "passport_number_last4", "expiry_date", "issue_date"}),
    "visa":            frozenset({"country", "expiry_date", "entry_type"}),
    "boarding_pass":   frozenset({"airline", "flight_number", "departure_date", "origin", "destination"}),
    "ticket":          frozenset({"vendor", "event_date", "location"}),
    "hotel_itinerary": frozenset({"hotel", "check_in", "check_out", "location"}),
    "receipt":         frozenset({"merchant", "amount", "currency", "purchase_date"}),
    "invoice":         frozenset({"vendor", "amount", "currency", "due_date", "invoice_number"}),
    "contract":        frozenset({"parties", "effective_date", "renewal_date"}),
    "agreement":       frozenset({"parties", "effective_date"}),
    "degree":          frozenset({"institution", "year", "field"}),
    "certificate":     frozenset({"issuer", "issue_date", "expiry_date"}),
    "insurance":       frozenset({"provider", "policy_number_last4", "expiry_date"}),
    "driver_license":  frozenset({"country", "license_number_last4", "expiry_date", "license_class"}),
    "id_card":         frozenset({"country", "id_number_last4", "expiry_date"}),
    "tax_document":    frozenset({"tax_year", "country", "form_type"}),
    "medical_record":  frozenset({"provider", "record_type", "record_date"}),
}


ITEM_TYPE_TO_TAGS: dict[str, tuple[str, ...]] = {
    "bank":   ("finance",),
    "card":   ("finance",),
    "id":     ("identity", "government"),
    "seed":   ("security",),
    "backup": ("security",),
    "note":   ("personal",),
    "login":  (),                                           
}


ALLOWED_MEMORY_TYPES: tuple[str, ...] = (
    "identity", "travel", "preference", "project", "company",
    "goal", "location", "relationship", "note",
    "family", "date", "life_event",
)


SERVICE_CATEGORIES: tuple[str, ...] = (
    "bank", "wallet", "exchange", "social", "travel", "commerce",
    "media", "government", "business",
)

SERVICE_CATEGORY_TO_TAGS: dict[str, tuple[str, ...]] = {
    "bank":       ("finance",),
    "wallet":     ("finance", "security"),
    "exchange":   ("finance",),
    "social":     ("personal",),
    "travel":     ("travel",),
    "commerce":   ("receipt", "finance"),
    "media":      ("media",),
    "government": ("government",),
    "business":   ("business",),
}


RELATION_TYPES: tuple[str, ...] = (
    "travel_related",
    "identity_related",
    "business_related",
    "finance_related",
    "tax_related",
    "medical_related",
    "family_related",
    "security_related",
    "media_related",
    "inheritance_related",
)


TAG_TO_RELATION: dict[str, str] = {
    "travel":     "travel_related",
    "finance":    "finance_related",
    "receipt":    "finance_related",
    "legal":      "business_related",
    "medical":    "medical_related",
    "business":   "business_related",
    "education":  "business_related",
    "identity":   "identity_related",
    "government": "identity_related",
    "security":   "security_related",
    "personal":   "family_related",
    "media":      "media_related",
    "tax":        "tax_related",
}

                                                                    
DOC_FAMILY_TO_RELATION: dict[str, str] = {
    "IDENTITY":  "identity_related",
    "TRAVEL":    "travel_related",
    "FINANCE":   "finance_related",
    "LEGAL":     "business_related",
    "MEDICAL":   "medical_related",
    "EDUCATION": "business_related",
}

                                                                      
SERVICE_CATEGORY_TO_RELATION: dict[str, str] = {
    "bank":       "finance_related",
    "wallet":     "finance_related",
    "exchange":   "finance_related",
    "social":     "family_related",
    "travel":     "travel_related",
    "commerce":   "finance_related",
    "media":      "media_related",
    "government": "identity_related",
    "business":   "business_related",
}


SUPPORTED_LOCALES: tuple[str, ...] = ("en", "ar", "fr", "es", "ja", "ko", "zh")

                                                                    
LOCALE_REGISTRY: tuple[str, ...] = (
    "en", "ar", "fr", "es", "ja", "ko", "zh",
)
