

from __future__ import annotations

import re
from typing import Optional


_SERVICE_NAME_LINE_RE = re.compile(
    r"^[A-Z][A-Za-z][A-Za-z0-9 .&\-]{0,38}$"
)
_SERVICE_NAME_REJECT_RE = re.compile(
    r"^(?:https?://|www\.|\d+(?:\.\d+)*|[A-Z]{1,3}\d+)$"
)
_RAW_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
)


_MAX_SERVICE_PREVIEW = 3


_SAMPLE_SCAN_BYTE_CAP = 200_000


def build_safe_file_analysis(
    text: Optional[str],
    *,
    file_name: str,
    metrics: dict,
    purpose_decision: dict,
    show_secret_values: bool = False,
) -> str:


    purpose = (purpose_decision or {}).get("purpose") or "unknown"
    purpose_label = (purpose_decision or {}).get("purpose_label") or ""
    pretty_name = (file_name or "this file").strip() or "this file"

    if not text or not text.strip():
        return _no_text_reply(pretty_name)

    snippet = text[:_SAMPLE_SCAN_BYTE_CAP]

    if purpose in ("saved_login_list", "credential_export"):
        return _credential_list_reply(
            pretty_name=pretty_name,
            snippet=snippet,
            metrics=metrics,
            purpose=purpose,
            show_secret_values=show_secret_values,
        )

    if purpose == "config_secrets":
        return _config_secrets_reply(
            pretty_name=pretty_name,
            metrics=metrics,
            show_secret_values=show_secret_values,
        )

    if purpose == "application_form":
        return (
            f"{pretty_name} appears to be an application form — it "
            "has form fields (applicant name, signature, etc.) and "
            "declaration / authorization language. It does not look "
            "like a saved-login list."
        )

    if purpose == "insurance_form":
        return (
            f"{pretty_name} appears to be an insurance form — it "
            "contains policy / premium / claim / beneficiary "
            "vocabulary. It does not look like a saved-login list."
        )

    if purpose == "government_legal_financial":
        return (
            f"{pretty_name} appears to be a government, legal, or "
            "financial document — it contains markers like federal "
            "form references, tax-year language, or agency names. "
            "It does not look like a saved-login list."
        )

                                              
    return (
        f"{pretty_name} appears to be a general text or document "
        "file. I don't see strong evidence that it's a saved-login "
        "list, a credential export, or a known form type."
    )


def _credential_list_reply(
    *,
    pretty_name: str,
    snippet: str,
    metrics: dict,
    purpose: str,
    show_secret_values: bool,
) -> str:


    blocks = int(metrics.get("credential_block_count") or 0)
    services = int(metrics.get("service_count") or 0)
    cred_lines = int(metrics.get("credential_like_lines") or 0)
    meaningful = int(metrics.get("meaningful_lines") or 0)
    density = float(metrics.get("credential_density") or 0.0)

    if purpose == "credential_export":
        headline = (
            f"{pretty_name} appears to be a password-manager export."
        )
    else:
        headline = (
            f"{pretty_name} appears to be a saved-login list."
        )

    pct = int(round(density * 100)) if density else 0

    detail_bits: list[str] = []
    if blocks > 0:
        detail_bits.append(
            f"I found {blocks} repeated website/app credential "
            f"record{'s' if blocks != 1 else ''}"
        )
    if services and services != blocks:
        detail_bits.append(
            f"{services} distinct service name"
            f"{'s' if services != 1 else ''}"
        )
    if pct > 0:
        detail_bits.append(
            f"about {pct}% of meaningful lines look like "
            "credential records"
        )

    detail_line = ""
    if detail_bits:
        detail_line = " — " + ", ".join(detail_bits) + "."

                                                              
    service_preview = _sample_service_names(snippet)
    preview_line = ""
    if service_preview:
        shown = service_preview[:_MAX_SERVICE_PREVIEW]
        more = max(0, len(service_preview) - len(shown))
        if more > 0:
            preview_line = (
                "\n\nFor example: "
                + ", ".join(shown)
                + f", and {more} more."
            )
        elif len(shown) > 1:
            preview_line = (
                "\n\nFor example: " + ", ".join(shown) + "."
            )
        elif shown:
            preview_line = (
                "\n\nFor example: " + shown[0] + "."
            )

    if show_secret_values:
                                                                   
                                                              
        consent_line = (
            "\n\nYou asked to see the saved values — I can extract "
            "them to your saved-logins surface (one record at a "
            "time, with confirmation per record). Reply \"save "
            "them to my logins\" to proceed."
        )
    else:
        consent_line = (
            "\n\nI can list the service names or extract and save "
            "the records to your saved-logins surface if you "
            "confirm. I won't show any passwords or secret values "
            "by default."
        )

    return headline + detail_line + preview_line + consent_line


def _config_secrets_reply(
    *,
    pretty_name: str,
    metrics: dict,
    show_secret_values: bool,
) -> str:
    cred_lines = int(metrics.get("credential_like_lines") or 0)
    headline = (
        f"{pretty_name} appears to be a configuration or secrets "
        "file — it contains labelled credential fields "
        "(api keys / tokens / passwords) without form-style "
        "applicant or claim fields."
    )
    detail = ""
    if cred_lines > 0:
        detail = (
            f" I counted {cred_lines} labelled credential "
            f"field{'s' if cred_lines != 1 else ''}."
        )
    consent = (
        "\n\nI can list the field names or save them to your "
        "saved-logins surface if you confirm. I won't show the "
        "actual key / token values by default."
    )
    return headline + detail + consent


def _no_text_reply(pretty_name: str) -> str:
    return (
        f"I don't have extracted text for {pretty_name} yet, so I "
        "can't tell you what's inside. If you uploaded it "
        "recently, give the background analyser a minute and try "
        "again — or open the file from the vault to view it."
    )


def _sample_service_names(text: str) -> list[str]:


    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if "@" in stripped:
            continue
        if not _SERVICE_NAME_LINE_RE.match(stripped):
            continue
        if _SERVICE_NAME_REJECT_RE.match(stripped):
            continue
        if _looks_password_shaped(stripped):
                                                              
                                                            
            continue
        if any(c.isdigit() for c in stripped) and len(stripped) <= 6:
                                                             
            continue
        key = stripped.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(stripped)
        if len(out) >= 20:
            break
    return out


def _looks_password_shaped(line: str) -> bool:


    digit_count = sum(1 for c in line if c.isdigit())
    if digit_count == 0:
        return False
    if digit_count >= 3:
        return True
    if any(
        (not c.isalnum()) and c not in " .&-"
        for c in line
    ):
        return True
                                                                  
    has_upper = any(c.isupper() for c in line)
    has_lower = any(c.islower() for c in line)
    if has_upper and has_lower and digit_count >= 1:
                                                                   
                                                                  
        stripped_digits = line.rstrip("0123456789")
        if not stripped_digits:
            return True
                                                                     
        words = stripped_digits.split()
        if all(w and w[0].isupper() for w in words):
            return False
        return True
    return False


_EXPLICIT_VALUE_REQUEST_RE = re.compile(
    r"(?i)\b(?:"
    r"show\s+(?:me\s+)?the\s+(?:passwords?|secrets?|values?|tokens?|keys?)|"
    r"reveal\s+the\s+(?:passwords?|secrets?|values?|tokens?|keys?)|"
    r"extract\s+(?:every|all|the)\s+(?:passwords?|secrets?|values?|tokens?|keys?)|"
    r"dump\s+(?:every|all|the)\s+(?:passwords?|secrets?|values?|tokens?|keys?)|"
    r"print\s+(?:every|all|the)\s+(?:passwords?|secrets?|values?|tokens?|keys?)"
    r")\b"
)


def user_explicitly_requested_values(message: Optional[str]) -> bool:


    if not message:
        return False
    return bool(_EXPLICIT_VALUE_REQUEST_RE.search(message))
