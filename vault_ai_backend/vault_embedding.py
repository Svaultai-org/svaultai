

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from typing import Optional

import vault_document_purpose as vp


logger = logging.getLogger(__name__)


EMBEDDING_STATUS_PENDING     = "pending"
EMBEDDING_STATUS_PROCESSING  = "processing"
EMBEDDING_STATUS_READY       = "ready"
EMBEDDING_STATUS_FAILED      = "failed"
EMBEDDING_STATUS_STALE       = "stale"
EMBEDDING_STATUS_UNSUPPORTED = "unsupported"

EMBEDDING_STATUSES: tuple[str, ...] = (
    EMBEDDING_STATUS_PENDING,
    EMBEDDING_STATUS_PROCESSING,
    EMBEDDING_STATUS_READY,
    EMBEDDING_STATUS_FAILED,
    EMBEDDING_STATUS_STALE,
    EMBEDDING_STATUS_UNSUPPORTED,
)


EMBEDDING_SOURCE_COMBINED       = "combined"
EMBEDDING_SOURCE_SUMMARY        = "summary"
EMBEDDING_SOURCE_SAFE_PREVIEW   = "safe_preview"
EMBEDDING_SOURCE_EXTRACTED_TEXT = "extracted_text"
EMBEDDING_SOURCE_OCR            = "ocr"
EMBEDDING_SOURCE_TRANSCRIPT     = "transcript"

EMBEDDING_SOURCES: tuple[str, ...] = (
    EMBEDDING_SOURCE_COMBINED,
    EMBEDDING_SOURCE_SUMMARY,
    EMBEDDING_SOURCE_SAFE_PREVIEW,
    EMBEDDING_SOURCE_EXTRACTED_TEXT,
    EMBEDDING_SOURCE_OCR,
    EMBEDDING_SOURCE_TRANSCRIPT,
)


try:
    from vault_config import ai as _ai_cfg
    _a = _ai_cfg()
    EMBEDDING_MODEL_DEFAULT = f"openai:{_a.embedding_model}"
    EMBEDDING_DIM = _a.embedding_dim
except Exception:
    EMBEDDING_MODEL_DEFAULT = "openai:text-embedding-3-small"
                                                                      
                                                                      
    EMBEDDING_DIM = 1536


CURRENT_EMBEDDING_ANALYSIS_VERSION = 1


MAX_INPUT_CHARS = 4_000


DEFAULT_STRONG_THRESHOLD = 0.45
DEFAULT_MEDIUM_THRESHOLD = 0.25


_SECRET_LOOKING_TOKEN_RE = re.compile(
    r"^[A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:'\",.<>/?\\|`~]{8,64}$"
)

                                                              
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|token|api[_\-]?key|secret|"
    r"private[_\-]?key|mnemonic|access[_\-]?token|bearer)\s*[:=]\s*\S+"
)

                                                      
_BEARER_RE = re.compile(r"(?i)^bearer\s+\S+")

                                                             
_LONG_ALPHANUM_RE = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


_PURPOSE_EXPANSIONS: dict[str, str] = {
    vp.PURPOSE_SAVED_LOGIN_LIST: (
        "saved login list, password manager export, account "
        "credentials list"
    ),
    vp.PURPOSE_CREDENTIAL_EXPORT: (
        "password manager export, credentials export, vault export"
    ),
    vp.PURPOSE_CONFIG_SECRETS: (
        "configuration file with secrets, api keys, environment "
        "variables, dotenv file"
    ),
    vp.PURPOSE_APPLICATION_FORM: (
        "application form, signed application, application "
        "paperwork"
    ),
    vp.PURPOSE_INSURANCE_FORM: (
        "insurance form, insurance policy paperwork, claim form"
    ),
    vp.PURPOSE_GOVERNMENT_LEGAL: (
        "government legal financial document, official paperwork"
    ),
    vp.PURPOSE_GENERIC_TEXT: "general document",
    vp.PURPOSE_UNKNOWN: "",
}


_TOPIC_EXPANSIONS: dict[str, str] = {
    "travel":       "travel documents, passport, visa, boarding "
                    "pass, itinerary, hotel reservation",
    "finance":      "bank statement, checking account, financial "
                    "records, money, banking, deposits, withdrawals",
    "taxes":        "tax return, w2, 1099, irs, tax filing, "
                    "taxes, refund",
    "identity":     "identity documents, passport, driver license, "
                    "social security number, ssn, id card",
    "legal":        "legal document, contract, agreement, court, "
                    "law, attorney, settlement",
    "medical":      "medical record, prescription, diagnosis, "
                    "healthcare, hospital, doctor",
    "insurance":    "insurance policy, premium, coverage, "
                    "beneficiary, claim, underwriter",
    "credentials":  "saved logins, passwords, account credentials, "
                    "authentication, login list",
    "education":    "transcript, diploma, university, college, "
                    "school records, gpa",
    "real_estate":  "real estate, mortgage, deed, lease, property, "
                    "rental",
}


_EMBEDDING_ENGINE = None                            


def set_embedding_engine(fn) -> None:


    global _EMBEDDING_ENGINE
    _EMBEDDING_ENGINE = fn


def reset_embedding_engine() -> None:


    global _EMBEDDING_ENGINE
    _EMBEDDING_ENGINE = None


class EmbeddingError(Exception):
    pass


def generate_embedding(
    text: str, *, model: str = EMBEDDING_MODEL_DEFAULT,
) -> list[float]:


    if text is None or not str(text).strip():
        raise EmbeddingError("no text to embed")
    engine = _EMBEDDING_ENGINE
    if engine is None:
        engine = _default_engine
    try:
        vec = engine(str(text))
    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError(f"embedding engine error: {exc}") from exc
    if not isinstance(vec, list):
        raise EmbeddingError("engine returned non-list vector")
    if not vec:
        raise EmbeddingError("engine returned empty vector")
                                                          
    try:
        return [float(x) for x in vec]
    except Exception as exc:
        raise EmbeddingError(
            f"engine returned non-numeric vector: {exc}"
        ) from exc


def _default_engine(text: str) -> list[float]:


    try:
        from openai import OpenAI                
    except Exception as exc:
        raise EmbeddingError(
            f"openai SDK unavailable: {exc}"
        ) from exc
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise EmbeddingError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=api_key)
    trimmed = text[:MAX_INPUT_CHARS]
    try:
        from vault_config import ai as _ai_cfg
        _model = _ai_cfg().embedding_model
    except Exception:
        _model = EMBEDDING_MODEL_DEFAULT.split(":", 1)[-1]
    resp = client.embeddings.create(
        model=_model,
        input=trimmed,
    )
    return list(resp.data[0].embedding)


def hash_safe_input(text: str) -> str:


    if not text:
        return ""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def cosine_similarity(a: list, b: list) -> float:


    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        try:
            xf = float(x)
            yf = float(y)
        except Exception:
            return 0.0
        dot += xf * yf
        na += xf * xf
        nb += yf * yf
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(dot / (math.sqrt(na) * math.sqrt(nb)))


def build_embedding_input(
    understanding: Optional[dict] = None,
    *,
    file_name: Optional[str] = None,
    raw_text: Optional[str] = None,
    summary: Optional[str] = None,
    safe_preview: Optional[str] = None,
    max_chars: int = MAX_INPUT_CHARS,
) -> str:


    parts: list[str] = []

    def _add(label: str, value: Optional[str]) -> None:
        if not value:
            return
        clean = _redact_secret_shaped_lines(str(value)).strip()
        if not clean:
            return
        if label:
            parts.append(f"{label}: {clean}")
        else:
            parts.append(clean)

    purpose = ""
    purpose_label = ""
    purpose_expansion = ""
    is_credential_bearing = False
    topics: list[str] = []
    categories: list[str] = []
    entities: dict = {}

    if understanding:
        purpose = str(understanding.get("document_purpose") or "")
        purpose_label = str(understanding.get("purpose_label") or "")
        purpose_expansion = _PURPOSE_EXPANSIONS.get(purpose, "")
        is_credential_bearing = purpose in (
            vp.PURPOSE_SAVED_LOGIN_LIST,
            vp.PURPOSE_CREDENTIAL_EXPORT,
            vp.PURPOSE_CONFIG_SECRETS,
        )
        topics = list(understanding.get("topics") or [])
        categories = list(understanding.get("detected_categories") or [])
        entities = understanding.get("entities") or {}

                                                                  
    if file_name:
        base = str(file_name).rsplit(".", 1)[0]
        _add("File name", base)

                                                                 
    if purpose_label:
        _add("Document purpose", purpose_label)
    if purpose_expansion:
        _add("", purpose_expansion)

                                                               
    topic_strings: list[str] = []
    for t in topics:
        expansion = _TOPIC_EXPANSIONS.get(str(t).lower())
        if expansion:
            topic_strings.append(expansion)
        else:
            topic_strings.append(str(t))
    if topic_strings:
        _add("Topics", "; ".join(topic_strings))

                                                              
    if categories:
        _add("Categories", ", ".join(str(c) for c in categories))

                                                          
    names = entities.get("names") if isinstance(entities, dict) else None
    if isinstance(names, list) and names:
        _add("Names mentioned", ", ".join(str(n) for n in names[:24]))
    email_domains = (
        entities.get("email_domains")
        if isinstance(entities, dict) else None
    )
    if isinstance(email_domains, list) and email_domains:
        _add("Email domains", ", ".join(
            str(d) for d in email_domains[:24]
        ))

                                                                
    if not is_credential_bearing:
        if summary:
            _add("Summary", summary)
        if safe_preview:
            _add("Preview", safe_preview)

                                                                   
    if not is_credential_bearing and raw_text and (
        not understanding or not summary
    ):
        snippet = _redact_secret_shaped_lines(str(raw_text))[:1_000]
        _add("Extracted text", snippet)

    output = " | ".join(p for p in parts if p)
    if max_chars and len(output) > max_chars:
        output = output[: max_chars]
    return output


def _redact_secret_shaped_lines(text: str) -> str:


    if not text:
        return ""
    out_lines: list[str] = []
    for raw in str(text).splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
                                                         
                                                                 
        if _INLINE_SECRET_RE.search(line):
            continue
        if _BEARER_RE.match(line.strip()):
            continue
                                                              
                                                      
        stripped = line.strip()
        if _SECRET_LOOKING_TOKEN_RE.match(stripped) and _is_secret_shape(
            stripped
        ):
            continue
                                                                  
        cleaned = _LONG_ALPHANUM_RE.sub("[redacted-token]", line)
        out_lines.append(cleaned)
    return "\n".join(out_lines)


def _is_secret_shape(token: str) -> bool:


    if not token:
        return False
    digits = sum(1 for ch in token if ch.isdigit())
    if digits >= 3:
        return True
    if any(ch in token for ch in "!@#$%^&*()+=[]{};:'\"<>/?\\|`~"):
        return True
                                                                    
                                                                    
    has_upper = any(ch.isupper() for ch in token)
    has_lower = any(ch.islower() for ch in token)
    if has_upper and has_lower and digits >= 1:
        return True
    return False
