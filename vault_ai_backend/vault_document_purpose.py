

from __future__ import annotations

import re
from typing import Optional


PURPOSE_SAVED_LOGIN_LIST = "saved_login_list"
PURPOSE_CREDENTIAL_EXPORT = "credential_export"
PURPOSE_CONFIG_SECRETS = "config_secrets"
PURPOSE_APPLICATION_FORM = "application_form"
PURPOSE_INSURANCE_FORM = "insurance_form"
PURPOSE_GOVERNMENT_LEGAL = "government_legal_financial"
PURPOSE_GENERIC_TEXT = "generic_text"
PURPOSE_UNKNOWN = "unknown"


PURPOSE_RANK: dict[str, int] = {
    PURPOSE_SAVED_LOGIN_LIST:    0,
    PURPOSE_CREDENTIAL_EXPORT:   0,
    PURPOSE_CONFIG_SECRETS:      1,
    PURPOSE_GENERIC_TEXT:        2,
    PURPOSE_UNKNOWN:             2,
    PURPOSE_APPLICATION_FORM:    3,
    PURPOSE_INSURANCE_FORM:      3,
    PURPOSE_GOVERNMENT_LEGAL:    3,
}


_PURPOSE_SCAN_BYTE_CAP = 200_000


_FORM_FIELD_LINE_RE = re.compile(
    r"(?im)^\s*(?:"
    r"applicant(?:'s)?(?:\s+name)?|"
    r"full\s+name|first\s+name|last\s+name|middle\s+name|"
    r"date\s+of\s+birth|dob|place\s+of\s+birth|"
    r"sex|gender|marital\s+status|"
    r"phone(?:\s+number)?|mobile|home\s+phone|work\s+phone|fax|"
    r"address|street(?:\s+address)?|city|state|"
    r"zip(?:\s+code)?|postal\s+code|country|"
    r"signature|signed\s+by|date\s+signed|witness|notary|"
    r"relationship\s+to|"
    r"reference\s+number|reference\s+id|"
    r"policy\s+number|policy\s+id|policy\s+holder|policyholder|"
    r"claim\s+number|claim\s+id|"
    r"application\s+(?:id|number|reference|date)|"
    r"case\s+number|file\s+number|"
    r"account\s+holder|account\s+number|"
    r"emergency\s+contact|next\s+of\s+kin|"
    r"occupation|employer|employer\s+name"
    r")\s*[:_\.]"
)

                                                                    
_FORM_DECLARATION_RE = re.compile(
    r"(?i)\b(?:"
    r"i\s+hereby\s+(?:certify|declare|acknowledge|state)|"
    r"under\s+penalty\s+of\s+perjury|"
    r"by\s+signing\s+below|"
    r"i\s+have\s+read\s+and\s+(?:understand|agree)|"
    r"i\s+authorize\s+(?:the\s+release|disclosure|payment)|"
    r"i\s+consent\s+to|"
    r"acknowledg(?:e|ment)\s+of\s+disclosure|"
    r"declaration\s+of|"
    r"waiver\s+and\s+release|"
    r"please\s+(?:complete|fill\s+out|return\s+this\s+form)|"
    r"page\s+\d+\s+of\s+\d+"
    r")"
)


_GOVERNMENT_RE = re.compile(
    r"(?i)\b(?:"
    r"internal\s+revenue\s+service|i\.?r\.?s\.?|"
    r"department\s+of\s+(?:health|labor|justice|state|defense|"
    r"homeland\s+security|veterans\s+affairs|education|"
    r"transportation|housing|treasury|agriculture|the\s+interior)|"
    r"federal\s+emergency\s+management\s+agency|\bfema\b|"
    r"social\s+security\s+(?:administration|number|card)|"
    r"medicare|medicaid|"
    r"u\.?s\.?\s+citizenship\s+and\s+immigration|"
    r"selective\s+service|"
    r"form\s+(?:w-?2|w-?4|w-?9|1040|1099|i-?9|i-?94|i-?129|i-?130|"
    r"da\s+\d+|sf\s+\d+|"
    r"\d{3,5})\b|"
    r"omb\s+(?:control\s+)?(?:no\.?|number)|"
    r"tax\s+year\s+\d{4}|"
    r"do\s+not\s+write\s+in\s+this\s+space|"
    r"this\s+is\s+an?\s+official\s+(?:government|federal)\s+document"
    r")"
)


_INSURANCE_TOKENS: tuple[str, ...] = (
    "policy holder", "policy number", "policyholder", "policy term",
    "named insured", "additional insured", "co-insured",
    "premium", "deductible", "coverage limit", "claim number",
    "claims department", "beneficiary", "underwriter",
    "loss payee", "endorsement", "rider", "schedule of benefits",
    "agent name", "agent number", "broker", "carrier",
    "explanation of benefits", "subrogation",
)


_PWD_MANAGER_HEADER_PATTERNS: tuple[re.Pattern[str], ...] = (
                                                      
    re.compile(
        r"(?im)^\s*name\s*[,\t]\s*url\s*[,\t]\s*username\s*[,\t]\s*password",
    ),
                                            
    re.compile(
        r"(?im)^\s*url\s*[,\t]\s*username\s*[,\t]\s*password",
    ),
                                                          
    re.compile(
        r"(?im)^\s*url\s*[,\t]\s*login[_\-]?username\s*[,\t]\s*login[_\-]?password",
    ),
                                                        
    re.compile(
        r"(?im)^\s*title\s*[,\t]\s*website\s*[,\t]\s*username\s*[,\t]\s*password",
    ),
                           
    re.compile(
        r"(?im)^\s*folder\s*[,\t]\s*favorite\s*[,\t]\s*type\s*[,\t]"
        r"\s*name\s*[,\t]\s*notes\s*[,\t]\s*fields\s*[,\t]\s*login[_\-]?uri",
    ),
                  
    re.compile(
        r"(?im)^\s*url\s*[,\t]\s*username\s*[,\t]\s*password\s*[,\t]"
        r"\s*(?:totp|extra|name|grouping)",
    ),
                                                                 
    re.compile(
        r"(?i)<KeePassFile>",
    ),
)


def classify_document_purpose(
    text: Optional[str],
    *,
    metrics: Optional[dict] = None,
) -> dict:


    metrics = metrics or {}

    if not text or not text.strip():
        return _decision(
            PURPOSE_UNKNOWN, confidence=0.0,
            evidence=[], label="",
        )

    snippet = text[:_PURPOSE_SCAN_BYTE_CAP]
    low = snippet.lower()

                                                                 
    for pat in _PWD_MANAGER_HEADER_PATTERNS:
        if pat.search(snippet):
            return _decision(
                PURPOSE_CREDENTIAL_EXPORT, confidence=0.95,
                evidence=[
                    "appears to be a password-manager export"
                ],
                label="a password-manager export",
            )

                                                                
    form_field_hits = len(_FORM_FIELD_LINE_RE.findall(snippet))
    form_declaration_hit = bool(_FORM_DECLARATION_RE.search(snippet))
    gov_hit = bool(_GOVERNMENT_RE.search(snippet))
    insurance_hits = sum(1 for tok in _INSURANCE_TOKENS if tok in low)

                                                                
    extra_signals = {
        "form_field_hits":      int(form_field_hits),
        "form_declaration_hit": bool(form_declaration_hit),
        "gov_hit":              bool(gov_hit),
        "insurance_hits":       int(insurance_hits),
    }

                                                             
    gov_match_count = len(_GOVERNMENT_RE.findall(snippet))
    if gov_match_count >= 2 or (gov_hit and form_field_hits >= 2):
        return _decision(
            PURPOSE_GOVERNMENT_LEGAL, confidence=0.88,
            evidence=[
                "appears to be a government, legal, or financial "
                "document"
            ],
            label="a government, legal, or financial document",
            extra=extra_signals,
        )

                                                                  
    if (insurance_hits >= 3) or (
        insurance_hits >= 2 and form_field_hits >= 2
    ):
        return _decision(
            PURPOSE_INSURANCE_FORM, confidence=0.85,
            evidence=["appears to be an insurance form"],
            label="an insurance form",
            extra=extra_signals,
        )

                                                              
    if form_field_hits >= 6 or (
        form_field_hits >= 3 and form_declaration_hit
    ):
        return _decision(
            PURPOSE_APPLICATION_FORM, confidence=0.80,
            evidence=["appears to be an application form"],
            label="an application form",
            extra=extra_signals,
        )

                                                       
    blocks = int(metrics.get("credential_block_count") or 0)
    density = float(metrics.get("credential_density") or 0.0)
    cred_lines = int(metrics.get("credential_like_lines") or 0)
    meaningful = int(metrics.get("meaningful_lines") or 0)
    service_count = int(metrics.get("service_count") or 0)

                                                             
    if blocks >= 3 and density >= 0.50 and service_count >= 3:
        return _decision(
            PURPOSE_SAVED_LOGIN_LIST, confidence=0.92,
            evidence=[
                "most of the document appears to be saved "
                "website/app login records"
            ],
            label="saved website/app login records",
            extra=extra_signals,
        )

                                                                 
    if blocks >= 5 and density >= 0.30:
        return _decision(
            PURPOSE_SAVED_LOGIN_LIST, confidence=0.78,
            evidence=[
                "looks like a list of saved login records "
                "(multiple service/account/password entries)"
            ],
            label="saved website/app login records",
            extra=extra_signals,
        )

                                                                          
    if cred_lines >= 6 and form_field_hits <= 1 and not gov_hit:
        return _decision(
            PURPOSE_CONFIG_SECRETS, confidence=0.75,
            evidence=[
                "appears to be a configuration or secrets file "
                "(api keys / tokens / credential fields)"
            ],
            label="a config / secrets file",
            extra=extra_signals,
        )

                                                  
    if meaningful >= 5:
        return _decision(
            PURPOSE_GENERIC_TEXT, confidence=0.5,
            evidence=[], label="",
            extra=extra_signals,
        )
    return _decision(
        PURPOSE_UNKNOWN, confidence=0.0,
        evidence=[], label="",
        extra=extra_signals,
    )


def purpose_is_credential_bearing(purpose: str) -> bool:


    return purpose in (
        PURPOSE_SAVED_LOGIN_LIST,
        PURPOSE_CREDENTIAL_EXPORT,
        PURPOSE_CONFIG_SECRETS,
    )


def purpose_is_form_like(purpose: str) -> bool:


    return purpose in (
        PURPOSE_APPLICATION_FORM,
        PURPOSE_INSURANCE_FORM,
        PURPOSE_GOVERNMENT_LEGAL,
    )


def _decision(
    purpose: str,
    *,
    confidence: float,
    evidence: list,
    label: str,
    extra: Optional[dict] = None,
) -> dict:
    out = {
        "purpose":       purpose,
        "confidence":    round(float(confidence), 4),
        "evidence":      list(evidence),
        "purpose_label": label,
        "purpose_rank":  PURPOSE_RANK.get(purpose, 2),
        "form_field_hits":      0,
        "form_declaration_hit": False,
        "gov_hit":              False,
        "insurance_hits":       0,
    }
    if extra:
        for key in ("form_field_hits", "form_declaration_hit",
                    "gov_hit", "insurance_hits"):
            if key in extra:
                out[key] = extra[key]
    return out
