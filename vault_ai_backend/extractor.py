

import re


SERVICE_PATTERNS = [
    r"\bfor\s+([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})",
    r"\bmy\s+([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+(login|account|credentials|password|username)\b",
    r"\b([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+(login|account|credentials)\b",
]


_STOPWORDS_EN: frozenset[str] = frozenset({
    "save", "store", "remember", "keep", "this", "add", "my",
    "what", "is", "show", "retrieve", "get", "find", "list",
    "username", "user", "email", "password", "pass", "pwd", "pin",
    "login", "logins", "account", "accounts", "credentials",
    "the", "a", "an", "and", "with", "for", "note", "notes",
    "credential", "pdf", "doc", "docs", "document", "documents",
    "file", "files", "spreadsheet", "sheet", "sheets", "photo",
    "photos", "image", "images", "brain", "vault", "vaultai",
    "all", "full", "secret", "secrets",
})

STOPWORDS_BY_LOCALE: dict[str, frozenset[str]] = {
    "en": _STOPWORDS_EN,
    "ar": frozenset({
        "احفظ", "خزن", "تذكر", "أضف", "أظهر", "أعطني", "جد", "اعرض",
        "كلمة", "السر", "المرور", "اسم", "المستخدم", "حساب",
        "اعتماد", "بيانات", "ملف", "ملفات", "صورة", "صور",
        "خزينة", "خزنة", "كل", "كامل", "سر", "أسرار",
    }),
    "fr": frozenset({
        "enregistre", "sauvegarde", "stocke", "ajoute", "garde",
        "rappelle-toi", "montre", "donne", "trouve", "liste",
        "mon", "ma", "mes", "le", "la", "les", "un", "une", "des",
        "et", "avec", "pour", "ce", "cette",
        "mot", "passe", "code", "courriel", "courrier", "utilisateur",
        "identifiant", "compte", "comptes", "fichier", "fichiers",
        "document", "documents", "photo", "photos", "image", "images",
        "coffre", "tout", "tous", "secret", "secrets",
    }),
    "es": frozenset({
        "guarda", "almacena", "recuerda", "agrega", "añade",
        "muestra", "dame", "encuentra", "buscar", "lista",
        "mi", "mis", "el", "la", "los", "las", "un", "una", "unos",
        "y", "con", "para", "este", "esta",
        "contraseña", "clave", "correo", "email", "usuario",
        "cuenta", "cuentas", "archivo", "archivos",
        "documento", "documentos", "foto", "fotos", "imagen",
        "imágenes", "bóveda", "caja", "todo", "todos", "secreto",
        "secretos",
    }),
    "ja": frozenset({
        "保存", "保管", "記憶", "追加", "見せて", "教えて",
        "探す", "検索", "リスト", "私の", "ユーザー", "アカウント",
        "パスワード", "メール", "ファイル", "文書", "写真",
        "金庫", "全部", "秘密",
    }),
    "ko": frozenset({
        "저장", "보관", "기억", "추가", "보여줘", "알려줘",
        "찾아", "검색", "목록", "내", "사용자", "계정",
        "비밀번호", "이메일", "파일", "문서", "사진",
        "금고", "모두", "비밀",
    }),
}


STOPWORDS = set(_STOPWORDS_EN)


def stopwords_for(locale_id: str) -> frozenset[str]:


    extra = STOPWORDS_BY_LOCALE.get((locale_id or "en").lower())
    if not extra or extra is _STOPWORDS_EN:
        return _STOPWORDS_EN
    return _STOPWORDS_EN | extra


_EMAIL_PROVIDERS_EN: frozenset[str] = frozenset({
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "aol.com", "icloud.com", "proton.me", "protonmail.com",
})

EMAIL_PROVIDERS_BY_LOCALE: dict[str, frozenset[str]] = {
    "en": _EMAIL_PROVIDERS_EN,
    "ar": frozenset({
                                                               
                                                                
        "yandex.com", "zoho.com", "mail.com",
    }),
    "fr": frozenset({
        "orange.fr", "laposte.net", "free.fr", "sfr.fr", "wanadoo.fr",
        "neuf.fr", "bbox.fr",
    }),
    "es": frozenset({
        "hotmail.es", "yahoo.es", "outlook.es",
        "telefonica.net", "movistar.com", "live.com.mx",
    }),
    "ja": frozenset({
        "yahoo.co.jp", "docomo.ne.jp", "ezweb.ne.jp", "softbank.ne.jp",
        "rakuten.jp", "nifty.com", "biglobe.ne.jp",
    }),
    "ko": frozenset({
        "naver.com", "daum.net", "hanmail.net", "kakao.com",
        "nate.com", "yahoo.co.kr",
    }),
}


EMAIL_PROVIDER_DOMAINS = set(_EMAIL_PROVIDERS_EN)


def email_providers_for(locale_id: str) -> frozenset[str]:


    extra = EMAIL_PROVIDERS_BY_LOCALE.get((locale_id or "en").lower())
    if not extra or extra is _EMAIL_PROVIDERS_EN:
        return _EMAIL_PROVIDERS_EN
    return _EMAIL_PROVIDERS_EN | extra


def clean_service_name(service: str) -> str:
    service = service.strip().lower()
    service = re.sub(r"\s+", " ", service)
    service = re.sub(r"[^\w\-\.\s&]", "", service)
    return service.strip() or "general"


def _extract_email_domain(text: str) -> str | None:
    match = re.search(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", text)
    if match:
        return match.group(1).lower()
    return None


def _looks_like_service_candidate(candidate: str) -> bool:
    candidate = clean_service_name(candidate)
    if not candidate or candidate == "general":
        return False
    if candidate in STOPWORDS:
        return False
    if candidate in EMAIL_PROVIDER_DOMAINS:
        return False
    if len(candidate) < 2:
        return False
    if candidate.isdigit():
        return False
    return True


def _strip_leading_noise(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^(save|store|remember|add)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(my|the)\s+", "", text, flags=re.IGNORECASE)
    return text.strip()


def detect_service(text: str) -> str:
    text = _strip_leading_noise(text)

    leading_patterns = [
        r"^\s*([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+(?:user|username|email|password|pass|pwd|pin)\s*[:=]",
        r"^\s*([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    ]
    for pattern in leading_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = clean_service_name(match.group(1))
            if _looks_like_service_candidate(candidate):
                return candidate

    for pattern in SERVICE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = clean_service_name(match.group(1))
            if _looks_like_service_candidate(candidate):
                return candidate

    retrieval_patterns = [
        r"\bwhat\s+is\s+my\s+([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+(login|account|password|credentials|username)\b",
        r"\bshow\s+my\s+([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+(login|account|credentials|password|username)\b",
        r"\bget\s+my\s+([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+(login|account|credentials|password|username)\b",
        r"\bretrieve\s+my\s+([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+(login|account|credentials|password|username)\b",
        r"\bfind\s+my\s+([a-zA-Z0-9][a-zA-Z0-9_\-\.& ]{1,50})\s+(login|account|credentials|password|username)\b",
    ]
    for pattern in retrieval_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = clean_service_name(match.group(1))
            if _looks_like_service_candidate(candidate):
                return candidate

    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    if first_line and len(first_line) <= 60:
        first_line_clean = clean_service_name(first_line)
        if (
            _looks_like_service_candidate(first_line_clean)
            and not re.search(r"(username|email|password|pass|pwd|pin)\s*[:=]", first_line, re.IGNORECASE)
            and "@" not in first_line
        ):
            return first_line_clean

    email_domain = _extract_email_domain(text)

    tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_\-\.&]{2,}\b", text)
    for token in tokens:
        candidate = clean_service_name(token)
        if not _looks_like_service_candidate(candidate):
            continue
        if email_domain and candidate == email_domain:
            continue
        return candidate

    if email_domain and email_domain not in EMAIL_PROVIDER_DOMAINS:
        return email_domain

    return "general"


def _normalize_extracted_identity(username: str | None, email: str | None) -> tuple[str | None, str | None]:
    if username:
        username = username.strip()
    if email:
        email = email.strip().lower()

    if username and email and username.strip().lower() == email.strip().lower():
        return username, None

    return username, email


def _clean_field(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().strip(",;|")
    value = re.sub(r"\s+", " ", value)
    return value or None


def extract_credentials(text: str):
    service = detect_service(text)
    username = None
    password = None
    email = None
    pin = None
    note = None

    username_patterns = [
        r"\busername\s*(?:is|=|:)\s*([^\s,;|]+)",
        r"\buser\s*(?:is|=|:)\s*([^\s,;|]+)",
        r"\blogin\s*(?:is|=|:)\s*([^\s,;|]+)",
        r"\baccount\s*(?:is|=|:)\s*([^\s,;|]+)",
    ]
    for pattern in username_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            username = _clean_field(match.group(1))
            break

    email_patterns = [
        r"\bemail\s*(?:is|=|:)\s*([^\s,;|]+@[^\s,;|]+)",
    ]
    for pattern in email_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            email = _clean_field(match.group(1))
            break

    password_patterns = [
        r"\bpassword\s*(?:is|=|:)?\s*([^\s,;|]+)",
        r"\bpass\s*(?:is|=|:)?\s*([^\s,;|]+)",
        r"\bpwd\s*(?:is|=|:)?\s*([^\s,;|]+)",
    ]
    for pattern in password_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            password = _clean_field(match.group(1))
            break

    pin_patterns = [
        r"\bpin\s*(?:is|=|:)?\s*([^\s,;|]+)",
    ]
    for pattern in pin_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            pin = _clean_field(match.group(1))
            break

    note_patterns = [
        r"\bnote\s*(?:is|=|:)?\s*(.+)$",
        r"\bremember\s+this\s*[:\-]?\s*(.+)$",
    ]
    for pattern in note_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            note = _clean_field(match.group(1))
            break

    username, email = _normalize_extracted_identity(username, email)

    has_potential_secret = bool(username or email or password or pin or note)

    return {
        "service": service,
        "username": username,
        "email": email,
        "password": password,
        "pin": pin,
        "note": note,
        "has_potential_secret": has_potential_secret,
    }


def _split_into_chunks(text: str) -> list[str]:
    if not text or not text.strip():
        return []

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    chunks = re.split(r"\n\s*\n+", normalized)

    expanded = []
    for chunk in chunks:
        parts = re.split(r"(?=^[A-Z][A-Za-z0-9 ._\-&]{2,50}$)", chunk, flags=re.MULTILINE)
        for part in parts:
            part = part.strip()
            if part:
                expanded.append(part)

    return expanded


def extract_multiple_credentials(text: str) -> list[dict]:
    results = []
    if not text or not text.strip():
        return results

    chunks = _split_into_chunks(text)
    seen = set()

    for raw_chunk in chunks:
        chunk = raw_chunk.strip()
        if not chunk:
            continue

        inline_parts = [p.strip() for p in re.split(r"\n(?=[A-Z][A-Za-z0-9 ._\-&]{2,50}$)", chunk) if p.strip()]
        if not inline_parts:
            inline_parts = [chunk]

        for part in inline_parts:
            extracted = extract_credentials(part)
            if not extracted.get("has_potential_secret"):
                continue

            service = clean_service_name(extracted.get("service") or "general")
            if not _looks_like_service_candidate(service):
                continue

            username, email = _normalize_extracted_identity(
                extracted.get("username"),
                extracted.get("email"),
            )

            fields = {}
            if username:
                fields["username"] = username
            if email:
                fields["email"] = email
            if extracted.get("password"):
                fields["password"] = extracted["password"]
            if extracted.get("pin"):
                fields["pin"] = extracted["pin"]
            if extracted.get("note"):
                fields["note"] = extracted["note"]

            if not fields:
                continue

            dedupe_key = (
                service,
                fields.get("username"),
                fields.get("email"),
                fields.get("password"),
                fields.get("pin"),
                fields.get("note"),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            results.append({
                "secret_type": "login",
                "service": service,
                "fields": fields,
            })

    return results


_REDACTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
                                                  
    ("password", (
                 
        "password", "passwords", "passwd", "pwd", "pass",
                
        "كلمة المرور", "كلمة السر", "كلمات المرور",
                                            
        "密码", "密碼", "口令",
                  
        "パスワード", "パス",
                
        "비밀번호", "비번", "패스워드",
                
        "mot de passe", "mdp",
                 
        "contraseña", "contrasena", "clave", "palabra clave",
    )),

                                             
    ("pin", (
        "pin", "pin code", "pin number",
        "الرمز السري", "رقم سري",
        "密码 pin", "pin 码", "暗号", "暗証",
        "暗証番号",
        "비밀번호 pin", "핀번호", "핀 번호",
        "code pin", "code secret",
        "número pin", "numero pin", "código pin", "codigo pin",
    )),

                                                                       
    ("otp", (
        "otp", "one time password", "one-time password",
        "verification code", "verify code", "auth code",
        "two factor code", "2fa", "2fa code",
        "رمز التحقق", "رمز التأكيد", "كلمة المرور لمرة واحدة",
        "验证码", "驗證碼", "动态密码", "一次性密码",
        "認証コード", "確認コード", "ワンタイムパスワード", "二段階認証",
        "인증코드", "인증 코드", "확인 코드", "일회용 비밀번호",
        "code de vérification", "code de verification",
        "code de confirmation", "code à usage unique",
        "código de verificación", "codigo de verificacion",
        "código de confirmación", "codigo de confirmacion",
    )),

                                                                
    ("seed", (
        "recovery phrase", "seed phrase", "mnemonic phrase",
        "mnemonic", "backup phrase", "secret phrase", "seed",
        "عبارة الاسترداد", "عبارة الاستعادة", "العبارة السرية",
        "助记词", "助記詞", "种子短语", "種子短語", "恢复短语",
        "復元フレーズ", "シードフレーズ", "リカバリーフレーズ",
        "복구 문구", "시드 문구", "복구구문", "시드구문",
        "phrase de récupération", "phrase de recuperation",
        "phrase secrète", "phrase secrete", "phrase mnémonique",
        "frase de recuperación", "frase de recuperacion",
        "frase semilla", "frase mnemónica", "frase mnemonica",
    )),

                                                
    ("secret", (
        "secret", "secret key", "private key", "api key", "api token",
        "السر", "المفتاح السري", "المفتاح الخاص",
        "秘密", "密钥", "密鑰", "私钥", "私鑰",
        "秘密鍵", "秘密キー", "プライベートキー",
        "비밀", "비밀 키", "비밀키", "개인 키", "개인키",
        "secret", "clé secrète", "cle secrete",
        "clé privée", "cle privee",
        "secreto", "clave secreta", "clave privada", "llave privada",
    )),

                                                    
    ("credential", (
        "credential", "credentials", "creds",
        "بيانات الاعتماد", "بيانات الاعتماد",
        "凭证", "凭据", "憑證", "憑據",
        "資格情報", "ログイン情報",
        "자격 증명", "로그인 정보",
        "identifiants", "informations de connexion",
        "credenciales", "datos de acceso",
    )),

                                                                             
    ("login", (
        "login", "log in", "logon", "log-in",
        "تسجيل الدخول",
        "登录", "登錄", "登入",
        "ログイン",
        "로그인",
        "connexion", "identifiant",
        "inicio de sesión", "acceso",
    )),
)


def _make_value_redactor(noun: str, label: str) -> tuple[str, str]:


    n = re.escape(noun)
                                                                 
                                                           
    pattern = (
        rf"(?<![A-Za-z0-9_])"
        rf"{n}"
        rf"(?![A-Za-z0-9_])"
        rf"\s*(?:is|=|:|的|는|은|이|가|est|son|es)?\s*"
        rf"([^\s,;|]+)"
    )
    replacement = f"{label}=***"
    return pattern, replacement


_COMPILED_RULES: list[tuple[re.Pattern, str]] = []
for _label, _nouns in _REDACTION_RULES:
                                                     
    for _noun in sorted(set(_nouns), key=len, reverse=True):
        _pat_str, _repl = _make_value_redactor(_noun, _label)
        _COMPILED_RULES.append((
            re.compile(_pat_str, flags=re.IGNORECASE | re.UNICODE),
            _repl,
        ))


_EMAIL_GLOBAL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    flags=re.IGNORECASE,
)
_USERNAME_EN = re.compile(
    r"\buser(name)?\s*(?:is|=|:)?\s*[^\s,;|]+",
    flags=re.IGNORECASE,
)
_EMAIL_LABEL = re.compile(
    r"\b(email|e-mail|courriel|correo|البريد الإلكتروني|邮箱|郵箱|メール|이메일)"
    r"\s*(?:is|=|:)?\s*[^\s,;|]+",
    flags=re.IGNORECASE | re.UNICODE,
)


def redact_message(text: str) -> str:


    if not text:
        return text
    try:
                                                    
        text = _USERNAME_EN.sub("username=***", text)
        text = _EMAIL_LABEL.sub("email=***", text)
        text = _EMAIL_GLOBAL.sub("***@***.***", text)
                                                     
        for pat, repl in _COMPILED_RULES:
            text = pat.sub(repl, text)
        return text
    except Exception:
        return text
