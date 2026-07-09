

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from vault_saved_item_taxonomy import (
    ALL_NETWORK_LABELS,
    CATEGORY_DEVICE,
    CATEGORY_IMEI,
    CATEGORY_SERIAL_NUMBER,
    CATEGORY_RECOVERY_CODE,
    CATEGORY_BACKUP_CODE,
    CATEGORY_PRIVATE_NOTE,
    CATEGORY_ACCOUNT_NOTE,
    CATEGORY_LOGIN,
    CATEGORY_OTHER,
    CATEGORY_OTHER_SECRET,
    CATEGORY_CRYPTO_WALLET_ADDRESS,
    CATEGORY_CRYPTO_SEED_PHRASE,
    CATEGORY_CRYPTO_PRIVATE_KEY,
    CATEGORY_CRYPTO_RECOVERY_PHRASE,
    CATEGORY_CRYPTO_NOTE,
    CATEGORY_CRYPTO_TRANSACTION_NOTE,
    CATEGORY_CRYPTO_EXCHANGE_NOTE,
    CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE,
    CRYPTO_CATEGORIES,
                                                 
    CATEGORY_LICENSE_KEY,
    CATEGORY_PRODUCT_KEY,
    CATEGORY_ACTIVATION_KEY,
    CATEGORY_PRIVATE_KEY,
    CATEGORY_RECOVERY_PHRASE,
    infer_category_from_message,
)


INTENT_SAVE_SECURE_ITEM:     str = "save_secure_item"
INTENT_RETRIEVE_SECURE_ITEM: str = "retrieve_secure_item"
INTENT_CONFIRM_SAVE:         str = "confirm_save"
INTENT_NONE:                 str = "none"
                                                                 
                                                                     
INTENT_CRYPTO_BALANCE_QUERY: str = "crypto_balance_query"


ALL_SECURE_ITEM_INTENTS: tuple[str, ...] = (
    INTENT_SAVE_SECURE_ITEM,
    INTENT_RETRIEVE_SECURE_ITEM,
    INTENT_CONFIRM_SAVE,
    INTENT_CRYPTO_BALANCE_QUERY,
    INTENT_NONE,
)


FIELD_IMEI:           str = "imei_1"
FIELD_IMEI_2:         str = "imei_2"
FIELD_SERIAL:         str = "serial_number"
FIELD_MAC:            str = "mac_address"
FIELD_PHONE_NUMBER:   str = "phone_number"
FIELD_RECOVERY_CODE:  str = "recovery_code"
FIELD_BACKUP_CODES:   str = "backup_codes"
FIELD_NOTES:          str = "notes"
FIELD_USERNAME:       str = "username"
FIELD_PASSWORD:       str = "password"
FIELD_PRIVATE_VALUE:  str = "private_value"
FIELD_ACCOUNT_NOTE:   str = "account_notes"

                                                           
FIELD_WALLET_ADDRESS:        str = "wallet_address"
FIELD_NETWORK:               str = "network"
FIELD_SEED_PHRASE:           str = "seed_phrase"
FIELD_PRIVATE_KEY:           str = "private_key"
FIELD_RECOVERY_PHRASE:       str = "recovery_phrase"
FIELD_CRYPTO_NOTE:           str = "crypto_note"
FIELD_TRANSACTION_NOTE:      str = "transaction_note"
FIELD_EXCHANGE_NOTE:         str = "exchange_note"
FIELD_HARDWARE_WALLET_NOTE:  str = "hardware_wallet_note"

                                                                
FIELD_LICENSE_KEY:    str = "license_key"
FIELD_PRODUCT_KEY:    str = "product_key"
FIELD_ACTIVATION_KEY: str = "activation_key"


_CRYPTO_MARKER_RE = re.compile(
    r"\b(?:crypto|wallet|wallets|bitcoin|btc|"
    r"ethereum|ether|eth|solana|sol|tron|trx|"
    r"binance|bnb|polygon|matic|"
    r"usdt|usdc|tether|dogecoin|doge|litecoin|ltc|"
    r"cardano|ada|ripple|xrp|monero|xmr|"
    r"seed\s+phrase|hardware\s+wallet|blockchain|web3|"
    r"metamask|trust\s+wallet|coinbase|exchange|"
                                                          
                                                              
    r"ledger|trezor|"
    r"airdrop|stake|staking|nft|defi|dapp|smart\s+contract)\b",
    re.IGNORECASE,
)


def has_crypto_marker(msg: Optional[str]) -> bool:


    if not isinstance(msg, str) or not msg:
        return False
    return bool(_CRYPTO_MARKER_RE.search(msg))


_FIELD_KEYWORDS: tuple[tuple[str, str], ...] = (
    (r"\bimei(?:\s+number|\s+1|\s+one)?\b",       FIELD_IMEI),
    (r"\bimei\s+2\b",                             FIELD_IMEI_2),
    (r"\bsecond\s+imei\b",                        FIELD_IMEI_2),
    (r"\bserial(?:\s+number)?\b",                 FIELD_SERIAL),
    (r"\bmac(?:\s+address)?\b",                   FIELD_MAC),
    (r"\bphone\s+number\b",                       FIELD_PHONE_NUMBER),
                                                             
                                                             
    (r"\brecovery\s+phrases?\b",                  FIELD_RECOVERY_PHRASE),
    (r"\brecovery\s+(?:code|key)\b",              FIELD_RECOVERY_CODE),
    (r"\bbackup\s+codes?\b",                      FIELD_BACKUP_CODES),
    (r"\btwo[\-\s]factor\s+codes?\b",             FIELD_BACKUP_CODES),
    (r"\bbitlocker(?:\s+(?:recovery\s+)?key)?\b", FIELD_RECOVERY_CODE),
    (r"\bfilevault(?:\s+(?:recovery\s+)?key)?\b", FIELD_RECOVERY_CODE),
                                                             
                                                              
    (r"\bprivate\s+(?:word|phrase|sentence|secret|note)\b",
                                                   FIELD_PRIVATE_VALUE),
    (r"\bsecret\s+(?:word|phrase|sentence|note)\b",
                                                   FIELD_PRIVATE_VALUE),
                                                               
                                                            
    (r"\baccount\s+notes?\b",                     FIELD_ACCOUNT_NOTE),
                                                          
                                                            
    (r"\bhardware\s+wallet(?:\s+note)?\b",         FIELD_HARDWARE_WALLET_NOTE),
    (r"\b(?:crypto|wallet)\s+seed\s+phrases?\b",   FIELD_SEED_PHRASE),
    (r"\bseed\s+phrases?\b",                        FIELD_SEED_PHRASE),
    (r"\b(?:crypto|wallet)\s+private\s+keys?\b",   FIELD_PRIVATE_KEY),
    (r"\bprivate\s+keys?\b",                        FIELD_PRIVATE_KEY),
    (r"\bcrypto\s+recovery\s+phrases?\b",          FIELD_RECOVERY_PHRASE),
    (r"\b(?:wallet|crypto)\s+recovery\s+phrases?\b", FIELD_RECOVERY_PHRASE),
    (r"\bwallet\s+address(?:es)?\b",                FIELD_WALLET_ADDRESS),
    (r"\bcrypto\s+(?:wallet|address)\b",            FIELD_WALLET_ADDRESS),
                                                             
                                                              
    (r"\breceive\s+address(?:es)?\b",               FIELD_WALLET_ADDRESS),
    (r"\bdeposit\s+address(?:es)?\b",               FIELD_WALLET_ADDRESS),
    (r"\bexchange\s+account\s+notes?\b",           FIELD_EXCHANGE_NOTE),
    (r"\bexchange\s+notes?\b",                     FIELD_EXCHANGE_NOTE),
    (r"\btransaction\s+notes?\b",                  FIELD_TRANSACTION_NOTE),
    (r"\bcrypto\s+notes?\b",                       FIELD_CRYPTO_NOTE),
                                                              
                                                             
    (r"\b(?:product|software|app)\s+keys?\b",      FIELD_PRODUCT_KEY),
    (r"\bactivation\s+keys?\b",                    FIELD_ACTIVATION_KEY),
    (r"\blicense\s+keys?\b",                       FIELD_LICENSE_KEY),
    (r"\bserial\s+keys?\b",                        FIELD_LICENSE_KEY),
                                                                
                                                                 
    (r"\bmy\s+[A-Za-z][A-Za-z0-9]*\s+keys?\b",     FIELD_LICENSE_KEY),
    (r"\b(?:this|the|that|a|an)\s+keys?\b",        FIELD_LICENSE_KEY),
)


_FIELD_RE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), label) for p, label in _FIELD_KEYWORDS
]


_SAVE_VERB_RE = re.compile(
    r"\b(?:save|store|remember|keep|add|put|write\s+down|note\s+down)\b",
    re.IGNORECASE,
)


_RETRIEVE_VERB_RE = re.compile(
    r"\b(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?"
    r"|give\s+me|find|look\s+up|retrieve|get|list)\b",
    re.IGNORECASE,
)


CATEGORY_FILTER_ALL: str = "*"


_CATEGORY_RETRIEVE_PATTERNS: tuple[tuple[str, str], ...] = (
                             
    (r"\b(?:saved|secure|vault)\s+items?\b",       CATEGORY_FILTER_ALL),
    (r"\bsaved\s+secrets?\b",                       CATEGORY_FILTER_ALL),
    (r"\bvault\s+records?\b",                       CATEGORY_FILTER_ALL),
    (r"\beverything\s+i(?:'|’)?ve\s+saved\b",       CATEGORY_FILTER_ALL),
                         
    (r"\blogins?\b",                                CATEGORY_LOGIN),
    (r"\bsaved\s+credentials?\b",                   CATEGORY_LOGIN),
            
    (r"\bprivate\s+notes?\b",                       CATEGORY_PRIVATE_NOTE),
    (r"\bsecret\s+notes?\b",                        CATEGORY_PRIVATE_NOTE),
    (r"\baccount\s+notes?\b",                       CATEGORY_ACCOUNT_NOTE),
            
    (r"\bbackup\s+codes?\b",                        CATEGORY_BACKUP_CODE),
    (r"\brecovery\s+codes?\b",                      CATEGORY_RECOVERY_CODE),
    (r"\brecovery\s+phrases?\b",                    CATEGORY_RECOVERY_CODE),
                  
    (r"\bserial\s+numbers?\b",                      CATEGORY_SERIAL_NUMBER),
    (r"\bimeis?\b",                                 CATEGORY_IMEI),
                        
    (r"\bcrypto\s+(?:wallets?|address(?:es)?)\b",   CATEGORY_CRYPTO_WALLET_ADDRESS),
    (r"\b(?:my\s+)?wallets?\b",                     CATEGORY_CRYPTO_WALLET_ADDRESS),
    (r"\bseed\s+phrases?\b",                        CATEGORY_CRYPTO_SEED_PHRASE),
    (r"\bprivate\s+keys?\b",                        CATEGORY_CRYPTO_PRIVATE_KEY),
    (r"\brecovery\s+phrases?\b",                    CATEGORY_CRYPTO_RECOVERY_PHRASE),
    (r"\bcrypto\s+notes?\b",                        CATEGORY_CRYPTO_NOTE),
    (r"\btransaction\s+notes?\b",                   CATEGORY_CRYPTO_TRANSACTION_NOTE),
    (r"\bexchange\s+(?:account\s+)?notes?\b",       CATEGORY_CRYPTO_EXCHANGE_NOTE),
    (r"\bhardware\s+wallets?\b",                    CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE),
    (r"\bcrypto\s+records?\b",                      CATEGORY_CRYPTO_WALLET_ADDRESS),
)


_CATEGORY_RETRIEVE_RE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), cat)
    for p, cat in _CATEGORY_RETRIEVE_PATTERNS
)


from vault_pending_draft_confirm import (
    is_pending_draft_confirm_phrase as _shared_is_confirm_save,
)


_CREDENTIAL_GEN_RE = re.compile(
    r"\b(?:create|generate|make|produce)\b.{0,40}\b"
    r"(?:username\s+and\s+password|password\s+and\s+username|"
    r"credential|credentials|login)\b",
    re.IGNORECASE,
)


_TITLE_TOKENS: dict[str, str] = {
    "phone":    "phone",
    "iphone":   "iPhone",
    "android":  "Android phone",
    "laptop":   "laptop",
    "macbook":  "MacBook",
    "pc":       "PC",
    "tablet":   "tablet",
    "ipad":     "iPad",
}


_TITLE_RE = re.compile(
    r"\bmy\s+([A-Za-z0-9 ]{1,40}?)\s+"
    r"(?:imei|serial|mac|phone\s+number|recovery|backup|"
    r"username|password|note|notes)",
    re.IGNORECASE,
)


_DEVICE_NOUN_RE = re.compile(
    r"\b(?:phone|iphone|android|laptop|macbook|pc|tablet|ipad|"
    r"device|computer|chromebook|notebook|watch|"
    r"smartphone|cellphone|mobile)\b",
    re.IGNORECASE,
)


_DEFAULT_TITLE_BY_FIELD: dict[str, str] = {
    FIELD_IMEI:          "Phone IMEI",
    FIELD_IMEI_2:        "Phone IMEI 2",
    FIELD_SERIAL:        "Serial number",
    FIELD_MAC:            "MAC address",
    FIELD_PHONE_NUMBER:  "Phone number",
    FIELD_RECOVERY_CODE: "Recovery code",
    FIELD_BACKUP_CODES:  "Backup codes",
    FIELD_PRIVATE_VALUE: "Private note",
    FIELD_ACCOUNT_NOTE:  "Account note",
                                                   
    FIELD_WALLET_ADDRESS:       "Crypto wallet",
    FIELD_SEED_PHRASE:          "Seed phrase",
    FIELD_PRIVATE_KEY:          "Private key",
    FIELD_RECOVERY_PHRASE:      "Recovery phrase",
    FIELD_CRYPTO_NOTE:          "Crypto note",
    FIELD_TRANSACTION_NOTE:     "Transaction note",
    FIELD_EXCHANGE_NOTE:        "Exchange account note",
    FIELD_HARDWARE_WALLET_NOTE: "Hardware wallet note",
                                             
    FIELD_LICENSE_KEY:    "License key",
    FIELD_PRODUCT_KEY:    "Product key",
    FIELD_ACTIVATION_KEY: "Activation key",
}


_FIELD_TITLE_NOUN: dict[str, str] = {
    FIELD_IMEI:          "IMEI",
    FIELD_IMEI_2:        "IMEI 2",
    FIELD_SERIAL:        "serial number",
    FIELD_MAC:            "MAC address",
    FIELD_PHONE_NUMBER:  "phone number",
    FIELD_RECOVERY_CODE: "recovery code",
    FIELD_RECOVERY_PHRASE: "recovery phrase",
    FIELD_BACKUP_CODES:  "backup codes",
    FIELD_PRIVATE_VALUE: "private note",
    FIELD_ACCOUNT_NOTE:  "account note",
    FIELD_LICENSE_KEY:    "key",
    FIELD_PRODUCT_KEY:    "product key",
    FIELD_ACTIVATION_KEY: "activation key",
    FIELD_PRIVATE_KEY:    "private key",
    FIELD_SEED_PHRASE:    "seed phrase",
    FIELD_CRYPTO_NOTE:    "crypto note",
    FIELD_TRANSACTION_NOTE: "transaction note",
    FIELD_EXCHANGE_NOTE:    "exchange account note",
    FIELD_HARDWARE_WALLET_NOTE: "hardware wallet note",
    FIELD_WALLET_ADDRESS:   "wallet",
}


_FIELD_CATEGORY_FALLBACK: dict[str, str] = {
    FIELD_IMEI:           CATEGORY_IMEI,
    FIELD_IMEI_2:         CATEGORY_IMEI,
    FIELD_SERIAL:         CATEGORY_SERIAL_NUMBER,
    FIELD_RECOVERY_CODE:  CATEGORY_RECOVERY_CODE,
    FIELD_BACKUP_CODES:   CATEGORY_BACKUP_CODE,
    FIELD_PRIVATE_VALUE:  CATEGORY_PRIVATE_NOTE,
    FIELD_ACCOUNT_NOTE:   CATEGORY_ACCOUNT_NOTE,
                                                             
                                                               
    FIELD_WALLET_ADDRESS:       CATEGORY_CRYPTO_WALLET_ADDRESS,
    FIELD_SEED_PHRASE:          CATEGORY_CRYPTO_SEED_PHRASE,
    FIELD_PRIVATE_KEY:          CATEGORY_CRYPTO_PRIVATE_KEY,
    FIELD_RECOVERY_PHRASE:      CATEGORY_CRYPTO_RECOVERY_PHRASE,
    FIELD_CRYPTO_NOTE:          CATEGORY_CRYPTO_NOTE,
    FIELD_TRANSACTION_NOTE:     CATEGORY_CRYPTO_TRANSACTION_NOTE,
    FIELD_EXCHANGE_NOTE:        CATEGORY_CRYPTO_EXCHANGE_NOTE,
    FIELD_HARDWARE_WALLET_NOTE: CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE,
                                                                 
                              
    FIELD_LICENSE_KEY:    CATEGORY_LICENSE_KEY,
    FIELD_PRODUCT_KEY:    CATEGORY_PRODUCT_KEY,
    FIELD_ACTIVATION_KEY: CATEGORY_ACTIVATION_KEY,
}


_NON_CRYPTO_EQUIVALENT: dict[str, str] = {
    CATEGORY_CRYPTO_PRIVATE_KEY:     CATEGORY_PRIVATE_KEY,
    CATEGORY_CRYPTO_RECOVERY_PHRASE: CATEGORY_RECOVERY_PHRASE,
                                                          
                                                            
}


_NETWORK_ALIASES: tuple[tuple[str, str], ...] = (
    ("bitcoin",      "BTC"),
    ("ethereum",     "ETH"),
    ("ether",        "ETH"),
    ("solana",       "SOL"),
    ("tron",         "TRX"),
    ("binance",      "BNB"),
    ("polygon",      "MATIC"),
    ("dogecoin",     "DOGE"),
    ("litecoin",     "LTC"),
    ("cardano",      "ADA"),
    ("ripple",       "XRP"),
    ("tether",       "USDT TRC20"),                                                
                                                                   
                                                                
    ("monero",       "XMR"),
)


def _build_network_patterns() -> list[tuple[re.Pattern[str], str]]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    for label in ALL_NETWORK_LABELS:
                                                            
                                                             
        parts = [re.escape(p) for p in label.split()]
        pat = r"\b" + r"\s+".join(parts) + r"\b"
        patterns.append((re.compile(pat, re.IGNORECASE), label))
    for alias, canon in _NETWORK_ALIASES:
        pat = r"\b" + re.escape(alias) + r"\b"
        patterns.append((re.compile(pat, re.IGNORECASE), canon))
    return patterns


_NETWORK_PATTERNS: list[tuple[re.Pattern[str], str]] = (
    _build_network_patterns()
)


def detect_network_label(msg: Optional[str]) -> Optional[str]:


    if not isinstance(msg, str) or not msg:
        return None
    for pat, label in _NETWORK_PATTERNS:
        if pat.search(msg):
            return label
    return None


@dataclass(frozen=True)
class SecureItemIntent:
    intent:    str
    category:  Optional[str] = None
    field:     Optional[str] = None
    title:     Optional[str] = None
    value:     Optional[str] = None
                                                                 
                                                             
    network:   Optional[str] = None
                                                                
                                                              
    receive_intent: bool = False


_RECEIVE_INTENT_RE = re.compile(
                                                            
                                               
    r"\breceive(?:\s+address|\s+wallet|\s+code|\s+my|\s+a)?\b"
    r"|\b(?:show\s+)?qr(?:\s+code)?\b"
    r"|\b(?:show\s+)?scan(?:\s+code)?\b"
    r"|\bdeposit(?:\s+address)?\b",
    re.IGNORECASE,
)


def _has_receive_intent(msg: Optional[str]) -> bool:


    if not isinstance(msg, str) or not msg:
        return False
    return bool(_RECEIVE_INTENT_RE.search(msg))


def _extract_value_for_field(
    message: str, field: str,
) -> Optional[str]:


    keyword_patterns = [p for p, lbl in _FIELD_KEYWORDS if lbl == field]
                                                               
                                 
    always_free_text_fields = {
        FIELD_PRIVATE_VALUE, FIELD_ACCOUNT_NOTE,
        FIELD_SEED_PHRASE, FIELD_CRYPTO_NOTE,
        FIELD_TRANSACTION_NOTE, FIELD_EXCHANGE_NOTE,
        FIELD_HARDWARE_WALLET_NOTE,
    }
                                                                  
                                                                 
    conditionally_free_text_fields = {
        FIELD_PRIVATE_KEY, FIELD_RECOVERY_PHRASE,
    }
    msg_has_crypto = has_crypto_marker(message)
    free_text_fields = set(always_free_text_fields)
    if msg_has_crypto:
        free_text_fields |= conditionally_free_text_fields
    for kp in keyword_patterns:
        m = re.search(kp, message, re.IGNORECASE)
        if m is None:
            continue
        tail = message[m.end():]
                                                          
        tail = re.sub(
            r"^\s*(?::|-|—|\bis\b|\bof\b)\s*", "", tail,
            flags=re.IGNORECASE,
        )
        tail = tail.strip()
        if field in free_text_fields:
                                                                    
            m_val = re.match(
                r"['\"“]?\s*([^\"'\n.!?“”]{1,400})"
                r"\s*['\"”]?\s*[.!?]?\s*$",
                tail,
            )
            if not m_val:
                m_val = re.match(
                    r"['\"“]?\s*([^\"'\n.!?“”]{1,400})",
                    tail,
                )
            if m_val:
                raw = re.sub(r"\s+", " ", m_val.group(1)).strip()
                raw = raw.rstrip(".,;:!?”\"'")
                return raw or None
            continue
        if field == FIELD_WALLET_ADDRESS:
                                                             
                                                              
            m_val = re.search(
                r"['\"]?([A-Za-z0-9_]{16,120})['\"]?",
                tail,
            )
            if m_val:
                raw = m_val.group(1).strip().rstrip(".,;:!?")
                return raw or None
            continue
                                                            
         
        candidates = re.findall(
            r"\b([A-Z0-9][A-Z0-9_\-]{5,})\b",
            tail, re.IGNORECASE,
        )
        if candidates:
            digit_bearing = [
                c for c in candidates
                if any(ch.isdigit() for ch in c)
            ]
            chosen = (
                digit_bearing[-1] if digit_bearing
                else candidates[-1]
            )
            raw = chosen.strip().rstrip(".,;:!?")
            return raw or None
                                                            
                                                              
    if field == FIELD_WALLET_ADDRESS:
        for m in re.finditer(
            r"['\"]?([A-Za-z0-9_]{16,120})['\"]?", message,
        ):
            raw = m.group(1).strip().rstrip(".,;:!?")
            return raw or None
    return None


def _extract_title(message: str) -> Optional[str]:

    m = _TITLE_RE.search(message)
    if not m:
        return None
    tokens = re.findall(r"[A-Za-z0-9]+", m.group(1).lower())
                                          
    for t in tokens:
        if t in _TITLE_TOKENS:
            return _TITLE_TOKENS[t]
                                   
    raw = m.group(1).strip()
    return raw or None


_FOR_CONTEXT_RE = re.compile(
    r"\bfor\s+(?:my\s+)?"
    r"([A-Za-z][A-Za-z0-9]*"
    r"(?:\s+[A-Za-z][A-Za-z0-9]*){0,4})",
    re.IGNORECASE,
)


_MY_BRAND_BEFORE_NOUN_RE = re.compile(
    r"\bmy\s+"
    r"([A-Za-z][A-Za-z0-9]*"
    r"(?:\s+[A-Za-z][A-Za-z0-9]*){0,3})\s+"
    r"(?:key|keys|license|product|activation|"
    r"code|codes|phrase|phrases)\b",
    re.IGNORECASE,
)


_CONTEXT_FILLER_TOKENS: frozenset[str] = frozenset({
    "the", "a", "an", "this", "that", "these", "those",
    "secret", "secrets",
    "vault", "storage", "save", "store", "keep", "remember",
    "now", "please", "value", "values",
})


def _looks_like_value_token(token: str) -> bool:


    if not token or len(token) < 4:
        return False
    has_digit = any(ch.isdigit() for ch in token)
    has_upper = any(ch.isupper() for ch in token)
    has_lower = any(ch.islower() for ch in token)
                                                              
                                                              
    if "-" in token or "_" in token:
        return True
                                                                
                                                                
    if has_upper and not has_lower and len(token) >= 4:
        return True
                                                
    if len(token) >= 10 and has_digit:
        return True
                                                           
    if has_digit and has_upper and has_lower:
        return True
    return False


def _strip_value_tail(text: str) -> str:


    if not text:
        return ""
    parts = text.split()
    while parts and _looks_like_value_token(parts[-1]):
        parts.pop()
                                                            
                                                                
    while len(parts) > 1 and parts[-1].lower() in _CONTEXT_FILLER_TOKENS:
        parts.pop()
    return " ".join(parts).strip()


def _extract_title_context(message: str) -> Optional[str]:


    if not isinstance(message, str) or not message:
        return None
    m = _FOR_CONTEXT_RE.search(message)
    if m is not None:
        ctx = _strip_value_tail(m.group(1).strip())
        tokens = [t for t in ctx.split() if t]
                                          
        if tokens and any(
            t.lower() not in _CONTEXT_FILLER_TOKENS for t in tokens
        ):
            return " ".join(tokens)
    m = _MY_BRAND_BEFORE_NOUN_RE.search(message)
    if m is not None:
        ctx = _strip_value_tail(m.group(1).strip())
        tokens = [t for t in ctx.split() if t]
        if tokens and any(
            t.lower() not in _CONTEXT_FILLER_TOKENS for t in tokens
        ):
            return " ".join(tokens)
    return None


def _compose_title_for_field(
    message: str, field: str,
) -> Optional[str]:


    ctx = _extract_title_context(message)
    if not ctx:
        return None
                                                      
                                                
    noun = _FIELD_TITLE_NOUN.get(field, "")
    if not noun:
        return normalize_secure_item_title(ctx)
                                                               
                                                       
    ctx_tokens  = ctx.lower().split()
    noun_tokens = noun.lower().split()
    overlap = 0
    max_check = min(len(ctx_tokens), len(noun_tokens))
    for k in range(max_check, 0, -1):
        if ctx_tokens[-k:] == noun_tokens[:k]:
            overlap = k
            break
    remaining_noun = noun_tokens[overlap:]
    if remaining_noun:
        composed = f"{ctx} {' '.join(remaining_noun)}"
    else:
        composed = ctx
    return normalize_secure_item_title(composed)


def _is_confirm_save(msg: str) -> bool:


    return _shared_is_confirm_save(msg)


def _refine_category(
    *, raw_category: str, field: str, msg: str,
) -> str:


    has_device_noun = bool(_DEVICE_NOUN_RE.search(msg))
    if has_device_noun and raw_category == CATEGORY_DEVICE:
        return CATEGORY_DEVICE
    fallback = _FIELD_CATEGORY_FALLBACK.get(field)
    if fallback is not None:
                                                             
                                                               
        downgrade = _NON_CRYPTO_EQUIVALENT.get(fallback)
        if downgrade is not None and not has_crypto_marker(msg):
            return downgrade
        return fallback
    return raw_category or CATEGORY_OTHER


_RETRIEVE_TITLE_TAIL_NOUNS: tuple[str, ...] = (
    "saved items", "saved item",
    "secure items", "secure item",
    "vault items", "vault item",
    "vault records", "vault record",
    "private notes", "private note",
    "account notes", "account note",
    "backup codes", "backup code",
    "recovery codes", "recovery code",
    "recovery phrases", "recovery phrase",
    "seed phrases", "seed phrase",
    "wallet addresses", "wallet address",
                                                             
                                                              
    "receive addresses", "receive address",
    "deposit addresses", "deposit address",
    "addresses", "address",
    "private keys", "private key",
    "license keys", "license key",
    "product keys", "product key",
    "activation keys", "activation key",
    "phone numbers", "phone number",
    "mac addresses", "mac address",
    "serial numbers", "serial number",
    "imeis", "imei",
    "logins", "login",
    "credentials", "credential",
    "passwords", "password",
    "usernames", "username",
    "notes", "note",
    "keys", "key",
    "wallets", "wallet",
)


_RETRIEVE_BROAD_CATEGORY_QUALIFIERS: frozenset[str] = frozenset({
    "", "all", "bank", "banking", "bank account",
    "saved", "every", "every saved",
    "full",
    "private", "secret", "account", "personal",
    "phone", "mobile", "device",
    "wallet", "crypto",
    "backup", "recovery",
    "license", "product", "activation",
    "seed", "hardware", "transaction", "exchange",
})


_RETRIEVE_HEAD_RE = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:show|reveal|tell\s+me|what(?:\s+is|(?:'|’)?s)?"
    r"|give\s+me|find|look\s+up|retrieve|get|list|open)"
    r"\s+",
    re.IGNORECASE,
)


_RETRIEVE_POSSESSIVE_RE = re.compile(
    r"^(?:me|my|the|a|an|that|this|some)\s+",
    re.IGNORECASE,
)


_RETRIEVE_REVEAL_QUALIFIER_RE = re.compile(
    r"^(?:full|complete|entire|whole)\s+",
    re.IGNORECASE,
)


def _extract_retrieve_title(message: str) -> Optional[str]:


    if not isinstance(message, str) or not message:
        return None
    msg = message.strip()
                         
    head_m = _RETRIEVE_HEAD_RE.match(msg)
    if head_m is None:
        return None
    rest = msg[head_m.end():].strip()
                                                             
                                                           
    for _ in range(5):
        poss_m = _RETRIEVE_POSSESSIVE_RE.match(rest)
        if poss_m is not None:
            rest = rest[poss_m.end():].strip()
            continue
        rev_m = _RETRIEVE_REVEAL_QUALIFIER_RE.match(rest)
        if rev_m is not None:
            rest = rest[rev_m.end():].strip()
            continue
        break
    if not rest:
        return None
    rest_lower = rest.lower()
                                                                   
                                                              
    best_tail: Optional[str] = None
    best_tail_start: int = -1
    best_tail_end: int = -1
    for noun in _RETRIEVE_TITLE_TAIL_NOUNS:
                                                                
                                                              
        idx = rest_lower.rfind(noun)
        if idx < 0:
            continue
                                                
        left_ok = (idx == 0) or not rest_lower[idx - 1].isalnum()
        end_idx = idx + len(noun)
        right_ok = (end_idx >= len(rest_lower)) or not rest_lower[end_idx].isalnum()
        if not (left_ok and right_ok):
            continue
                                                            
                                                            
        if end_idx > best_tail_end or (
            end_idx == best_tail_end and idx < best_tail_start
        ):
            best_tail = noun
            best_tail_start = idx
            best_tail_end = end_idx
    if best_tail is None:
                                                          
                                  
        candidate = rest_lower.strip(".,;:!?\"'`()[]{}")
    else:
        candidate = rest_lower[:best_tail_start].strip()
        candidate = candidate.strip(".,;:!?\"'`()[]{}")
                                                               
                                                             
    if candidate in _RETRIEVE_BROAD_CATEGORY_QUALIFIERS:
        return None
                          
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if not candidate:
        return None
    return candidate


def classify_secure_item_intent(
    user_message: Optional[str],
) -> SecureItemIntent:


    if not isinstance(user_message, str) or not user_message:
        return SecureItemIntent(intent=INTENT_NONE)
    msg = user_message.strip()

                                                                   
    try:
        from crypto_balance_query import is_crypto_balance_query
        if is_crypto_balance_query(msg):
            return SecureItemIntent(
                intent=INTENT_CRYPTO_BALANCE_QUERY,
            )
    except Exception:
                                                               
                                                                 
        pass

                                                                
    if _is_confirm_save(msg):
        return SecureItemIntent(intent=INTENT_CONFIRM_SAVE)

                                                                   
    if _CREDENTIAL_GEN_RE.search(msg):
        return SecureItemIntent(intent=INTENT_NONE)

                                                               
    detected_field: Optional[str] = None
    for pat, label in _FIELD_RE:
        if pat.search(msg):
            detected_field = label
            break

                                                                
    if detected_field is None:
        if detect_network_label(msg) and re.search(
            r"\b(?:address(?:es)?|wallets?|"
            r"qr(?:\s+code)?|receive(?:\s+(?:qr|address))?|"
            r"deposit)\b",
            msg, re.IGNORECASE,
        ):
            detected_field = FIELD_WALLET_ADDRESS

                                                              
    save_m     = _SAVE_VERB_RE.search(msg)
    retrieve_m = _RETRIEVE_VERB_RE.search(msg)
    if save_m and retrieve_m:
        if retrieve_m.start() < save_m.start():
            save_match, retrieve_match = False, True
        else:
            save_match, retrieve_match = True, False
    else:
        save_match    = bool(save_m)
        retrieve_match = bool(retrieve_m)

    if detected_field is None:
                                                                   
                                                              
        if retrieve_match:
            net = detect_network_label(msg)
            for pat, cat in _CATEGORY_RETRIEVE_RE:
                if pat.search(msg):
                                                            
                                                               
                    receive_flag = (
                        cat == CATEGORY_CRYPTO_WALLET_ADDRESS
                        and _has_receive_intent(msg)
                    )
                    return SecureItemIntent(
                        intent=INTENT_RETRIEVE_SECURE_ITEM,
                        category=cat,
                        field=None,
                        title=_extract_retrieve_title(msg),
                        network=net,
                        receive_intent=receive_flag,
                    )
        return SecureItemIntent(intent=INTENT_NONE)

    raw_category = (
        infer_category_from_message(msg)
        or CATEGORY_OTHER
    )
    category = _refine_category(
        raw_category=raw_category, field=detected_field, msg=msg,
    )

    network = detect_network_label(msg)

    if save_match:
                                                
         
        title = (
            _compose_title_for_field(msg, detected_field)
            or _extract_title(msg)
            or _DEFAULT_TITLE_BY_FIELD.get(detected_field)
        )
                                                               
                                                      
        if network and detected_field == FIELD_WALLET_ADDRESS:
            title = f"{network} wallet"
        value = _extract_value_for_field(msg, detected_field)
        return SecureItemIntent(
            intent=INTENT_SAVE_SECURE_ITEM,
            category=category,
            field=detected_field,
            title=title,
            value=value,
            network=network,
        )
    if retrieve_match:
                                                                 
                                                                
        title = _extract_retrieve_title(msg)
                                                                  
                                                              
        receive_flag = (
            detected_field == FIELD_WALLET_ADDRESS
            and _has_receive_intent(msg)
        )
        return SecureItemIntent(
            intent=INTENT_RETRIEVE_SECURE_ITEM,
            category=category,
            field=detected_field,
            title=title,
            network=network,
            receive_intent=receive_flag,
        )
    return SecureItemIntent(intent=INTENT_NONE)


_COMMAND_VERB_RE = re.compile(
    r"^\s*(?:save|store|remember|keep|add|put|write|note|"
    r"show|reveal|tell|find|get|give|look|retrieve|"
    r"create|generate|make|produce|update|delete|remove|"
    r"forget|drop|share|send|open|list|hide|"
    r"what|where|when|why|how|who|which|"
    r"can|could|would|will|do|does|is|are|am|"
    r"please|pls|pls\.|hey|hi|hello|ok|okay|"
    r"yes|no|yep|nope|sure|"
    r"i\b|i(?:'|’)m\b|i(?:'|’)ll\b|i(?:'|’)ve\b)\b",
    re.IGNORECASE,
)


_TITLE_HINT_TOKENS: frozenset[str] = frozenset({
             
    "phone", "iphone", "android", "samsung", "google", "pixel",
    "laptop", "macbook", "pc", "tablet", "ipad", "watch",
    "chromebook", "notebook", "device", "computer",
                         
    "imei", "serial", "mac", "number", "key", "code", "codes",
    "recovery", "backup", "password", "username", "credential",
    "credentials", "login", "note", "notes", "secret", "phrase",
    "word", "tag",
                             
    "work", "personal", "home", "office", "main", "spare",
    "old", "new", "primary", "secondary", "backup",
    "my", "your", "ours",
})


_WORD_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def looks_like_secure_item_title_update(
    user_message: Optional[str],
) -> bool:


    if not isinstance(user_message, str):
        return False
    msg = user_message.strip()
    if not msg or len(msg) > 60:
        return False
    if msg.endswith("?"):
        return False
    if _is_confirm_save(msg):
        return False
    if _COMMAND_VERB_RE.match(msg):
        return False
    tokens = _WORD_TOKEN_RE.findall(msg)
    if not tokens or len(tokens) > 8:
        return False
                                                                 
                         
    cls = classify_secure_item_intent(msg)
    if cls.intent in (
        INTENT_SAVE_SECURE_ITEM,
        INTENT_RETRIEVE_SECURE_ITEM,
        INTENT_CONFIRM_SAVE,
    ):
        return False
    return any(t.lower() in _TITLE_HINT_TOKENS for t in tokens)


_TITLE_TOKEN_CASE: dict[str, str] = {
    "imei":     "IMEI",
    "mac":      "MAC",
    "pc":       "PC",
    "id":       "ID",
    "usa":      "USA",
    "uk":       "UK",
    "ssh":      "SSH",
    "vpn":      "VPN",
    "wifi":     "Wi-Fi",
    "iphone":   "iPhone",
    "ipad":     "iPad",
    "macbook":  "MacBook",
    "samsung":  "Samsung",
    "google":   "Google",
    "pixel":    "Pixel",
    "android":  "Android",
    "windows":  "Windows",
    "chromebook": "Chromebook",
    "apple":    "Apple",
}


def normalize_secure_item_title(user_text: Optional[str]) -> str:


    if not isinstance(user_text, str):
        return ""
    msg = re.sub(r"\s+", " ", user_text.strip())
    if not msg:
        return ""

                                                                    
    if re.search(r"\bserial\s*$", msg, re.IGNORECASE):
        msg = re.sub(r"\bserial\s*$", "serial number", msg, flags=re.IGNORECASE)

    parts: list[str] = []
    first_token_was_canonical = False
    for idx, tok in enumerate(msg.split(" ")):
        lower = tok.lower().strip(".,;:!?")
        canon = _TITLE_TOKEN_CASE.get(lower)
        if canon is not None:
            parts.append(canon + tok[len(lower):])
            if idx == 0:
                first_token_was_canonical = True
        else:
            parts.append(tok)

    out = " ".join(parts)
    if out and not first_token_was_canonical:
                                                                
                                                              
        head = out[0]
        if head.isalpha() and head.islower():
            out = head.upper() + out[1:]
    return out


__all__ = [
    "INTENT_SAVE_SECURE_ITEM",
    "INTENT_RETRIEVE_SECURE_ITEM",
    "INTENT_CONFIRM_SAVE",
    "INTENT_NONE",
    "ALL_SECURE_ITEM_INTENTS",
    "FIELD_IMEI", "FIELD_IMEI_2", "FIELD_SERIAL",
    "FIELD_MAC", "FIELD_PHONE_NUMBER",
    "FIELD_RECOVERY_CODE", "FIELD_BACKUP_CODES",
    "FIELD_NOTES", "FIELD_USERNAME", "FIELD_PASSWORD",
    "FIELD_PRIVATE_VALUE", "FIELD_ACCOUNT_NOTE",
                               
    "FIELD_WALLET_ADDRESS", "FIELD_NETWORK",
    "FIELD_SEED_PHRASE", "FIELD_PRIVATE_KEY",
    "FIELD_RECOVERY_PHRASE", "FIELD_CRYPTO_NOTE",
    "FIELD_TRANSACTION_NOTE", "FIELD_EXCHANGE_NOTE",
    "FIELD_HARDWARE_WALLET_NOTE",
                                           
    "FIELD_LICENSE_KEY", "FIELD_PRODUCT_KEY",
    "FIELD_ACTIVATION_KEY",
                                                                  
    "has_crypto_marker",
    "SecureItemIntent",
    "CATEGORY_FILTER_ALL",
    "classify_secure_item_intent",
    "looks_like_secure_item_title_update",
    "normalize_secure_item_title",
    "detect_network_label",
]
