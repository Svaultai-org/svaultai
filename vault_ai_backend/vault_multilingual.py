"""Multilingual helpers for VaultAI Chat.

Goals of this module:

  * Detect the language of an incoming chat message using cheap
    unicode-block heuristics + a small set of high-signal
    latin-alphabet stopwords. Deterministic. No network calls.

  * Decide the final reply language given (app_locale header/body,
    detected language). The explicit app/UI locale wins unless the
    user has not supplied one; lightweight Latin keyword detection is
    too weak to override the conversation language.

  * Provide multilingual regex bundles for the highest-signal
    intents and refusal categories: delete-vault, forgot-pin,
    what-is-vaultai, seed / private key / mnemonic secret
    material, PIN bypass, crypto buy / sell / swap / trade,
    Monero scanner.

None of the enforcement logic changes here. Refusals still route
through the existing router; this module just adds language-
agnostic *pre-match* signals so a French user asking "révèle-moi
la seed phrase" gets refused even before the English regex misses.

Log safety: nothing in this module accepts a logger. It is called
BY the request handler; the handler decides what to emit. Raw
message text is only ever seen as an argument, never persisted.
"""

from __future__ import annotations

import re
from typing import Optional


SUPPORTED_REPLY_LANGUAGE_CODES = frozenset({
    "en", "ar", "fr", "es", "ja", "ko", "zh",
    "pt", "de", "it", "hi", "ur", "bn", "ru", "tr", "id",
    "vi", "th", "sw", "ha", "yo", "ig", "so", "am",
})


DEFAULT_REPLY_LANGUAGE = "en"




_UNICODE_BLOCK_LANG: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("ar", ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF),
            (0xFE70, 0xFEFF))),

    ("ja", ((0x3040, 0x309F), (0x30A0, 0x30FF))),

    ("ko", ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))),


    ("zh", ((0x4E00, 0x9FFF),)),

    ("th", ((0x0E00, 0x0E7F),)),
    ("hi", ((0x0900, 0x097F),)),
    ("bn", ((0x0980, 0x09FF),)),
    ("am", ((0x1200, 0x137F),)),
    ("ru", ((0x0400, 0x04FF),)),
)





_LATIN_KEYWORDS_BY_LANG: dict[str, tuple[str, ...]] = {

















    "en":  (" the ", " and ", " with ", " your ", " what ",
            " how ", " you ", " are ", " is a ", " is my ",
            " please ", " thank ", " thanks ",
            " hello ", " hi ", " hey ",
            " i'm ", " it's ", " that's ",
            " can you ", " show me ", " tell me "),
    "fr":  ("le ", "la ", " est ", " je ", " mon ", " ma ", " avec ",
            "être", "voici", "pourquoi", " qu'", "supprim", "coffre",
            " mot de passe", " compte", " comment "),
    "es":  ("el ", "la ", " es ", " yo ", " mi ", " con ", "está",
            "cuál", "cómo", "eliminar", "bóveda", "contraseña",
            "cuenta", " qué "),
    "pt":  (" o ", " a ", "está", "você", "meu", "minha",
            "excluir", "cofre", "conta", "senha", "por que"),
    "de":  (" ist ", " der ", " die ", " ich ", " mein ", "meine",
            "wieso", "löschen", "tresor", "passwort", "konto"),










    "it":  ("il ", "la ", " è ", " io ", " mio ", " mia ",
            "cassaforte", "eliminare"),
    "id":  (" saya ", " adalah ", " apa ", "hapus", "brankas",
            "kata sandi", "akun"),
    "vi":  (" tôi ", " là ", "xóa", "két", "mật khẩu", "tài khoản"),
    "tr":  (" ben ", " nedir ", "sil", "kasa", "şifre", "hesap"),
    "sw":  (" mimi ", " ni ", "futa", "hazina", "nywila", "akaunti"),
    "ur":  (" میں ", " کیا ", "حذف", "پاس ورڈ"),
    "ha":  (" ni ", " ne ", "share", "kalmar sirri"),
    "yo":  (" mo ", " ni ", "pa", "ọrọ igbaniwọle"),
    "ig":  (" m ", "hichapụ", "okwuidozi"),
    "so":  (" waan ", " maxaa ", "tirtir", "furaha sirta"),
}





_DELETE_VAULT_PATTERNS_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        r"\bdelete\s+(?:my\s+)?vault\b",
        r"\bwipe\s+(?:my\s+)?vault\b",
        r"\bhow\s+do\s+i\s+delete\b",
    ),
    "ar": (
        r"احذف\s+(?:خزينتي|خزنتي|الخزينة|الخزنة)",
        r"حذف\s+(?:خزينتي|خزنتي|الخزينة|الخزنة)",
        r"امسح\s+(?:خزينتي|خزنتي|الخزينة|الخزنة)",
    ),
    "fr": (
        r"supprim(?:er|e)\s+(?:mon\s+)?coffre",
        r"effacer\s+(?:mon\s+)?coffre",
        r"comment\s+supprimer\s+(?:mon\s+)?coffre",
    ),
    "es": (
        r"eliminar\s+(?:mi\s+)?b[óo]veda",
        r"borrar\s+(?:mi\s+)?b[óo]veda",
        r"c[óo]mo\s+eliminar\s+(?:mi\s+)?b[óo]veda",
    ),
    "ja": (
        r"保管庫を(?:完全に)?削除",
        r"金庫を(?:完全に)?削除",
        r"ボールトを(?:完全に)?削除",
    ),
    "ko": (
        r"보관소를?\s*삭제",
        r"금고를?\s*삭제",
        r"볼트를?\s*삭제",
    ),
    "zh": (
        r"删除(?:我的)?保险库",
        r"删除(?:我的)?保管库",
        r"注销(?:我的)?保险库",
    ),
    "pt": (
        r"excluir\s+(?:meu\s+)?cofre",
        r"apagar\s+(?:meu\s+)?cofre",
    ),
    "de": (
        r"tresor\s+l[öo]schen",
        r"meinen\s+tresor\s+l[öo]schen",
    ),
    "it": (
        r"eliminare\s+(?:la\s+)?cassaforte",
        r"cancellare\s+(?:la\s+)?cassaforte",
    ),
}


_WHAT_IS_VAULTAI_PATTERNS_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        r"\bwhat\s+is\s+vault\s*ai\b",
        r"\bhow\s+does\s+vault\s*ai\s+work\b",
    ),
    "ar": (
        r"ما\s+هو\s+vault\s*ai",
        r"ما\s+هي\s+vault\s*ai",
    ),
    "fr": (
        r"qu(?:'|’)est[- ]ce\s+que\s+vault\s*ai",
        r"c(?:'|’)est\s+quoi\s+vault\s*ai",
    ),
    "es": (
        r"qu[ée]\s+es\s+vault\s*ai",
        r"para\s+qu[ée]\s+sirve\s+vault\s*ai",
    ),
    "ja": (
        r"vault\s*ai\s*(?:とは|って何|とは何)",
    ),
    "ko": (
        r"vault\s*ai\s*(?:가|이)?\s*뭐(?:야|예요|입니까)",
        r"vault\s*ai\s*무엇",
    ),
    "zh": (
        r"vault\s*ai\s*(?:是什么|是啥|是干什么的)",
    ),
    "pt": (
        r"o\s+que\s+é\s+vault\s*ai",
    ),
    "de": (
        r"was\s+ist\s+vault\s*ai",
    ),
    "it": (
        r"cos(?:'|’)?è\s+vault\s*ai",
    ),
}


_FORGOT_PIN_PATTERNS_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        r"\bforgot\s+(?:my\s+)?pin\b",
        r"\blost\s+(?:my\s+)?pin\b",
    ),
    "ar": (
        r"نسيت\s+(?:رمز\s+)?(?:ال)?pin",
        r"فقدت\s+(?:رمز\s+)?(?:ال)?pin",
    ),
    "fr": (
        r"j(?:'|’)ai\s+oubli[ée]\s+(?:mon\s+)?pin",
        r"pin\s+oubli[ée]",
    ),
    "es": (
        r"olvid[ée]\s+(?:mi\s+)?pin",
        r"perd[íi]\s+(?:mi\s+)?pin",
    ),
    "ja": (
        r"pin\s*(?:を|が)?\s*(?:忘れ|わすれ)",
    ),
    "ko": (
        r"pin\s*(?:을|를)?\s*(?:잊|잃)",
    ),
    "zh": (
        r"忘记\s*(?:我的)?pin",
        r"忘了\s*(?:我的)?pin",
    ),
}





_SECRET_MATERIAL_PATTERNS_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        r"\bseed\s+phrase\b",
        r"\bmnemonic\b",
        r"\bprivate\s+key\b",
        r"\bspend\s+key\b",
        r"\bview\s+key\b",
    ),
    "ar": (
        r"(?:عبارة|كلمات)\s+البذرة",
        r"مفتاح\s+خاص",
        r"عبارة\s+الاسترداد",
    ),
    "fr": (
        r"phrase\s+(?:de\s+r[ée]cup[ée]ration|de\s+r[ée]cup|seed)",
        r"cl[ée]\s+priv[ée]e",
        r"phrase\s+mn[ée]monique",
    ),
    "es": (
        r"frase\s+(?:semilla|de\s+recuperaci[óo]n)",
        r"clave\s+privada",
        r"palabras\s+de\s+recuperaci[óo]n",
    ),
    "ja": (
        r"シード\s*フレーズ",
        r"リカバリー\s*フレーズ",
        r"秘密\s*鍵",
        r"プライベート\s*キー",
    ),
    "ko": (
        r"시드\s*(?:구|문|프레이즈|문구)",
        r"복구\s*(?:구|문|프레이즈|문구)",
        r"개인\s*키",
    ),
    "zh": (
        r"助记词",
        r"种子短语",
        r"私钥",
        r"恢复短语",
    ),
    "pt": (
        r"frase\s+(?:semente|de\s+recupera[çc][ãa]o)",
        r"chave\s+privada",
    ),
    "de": (
        r"seed\s*phrase",
        r"wiederherstellungsphrase",
        r"private\s+schl[üu]ssel",
    ),
}


_PIN_BYPASS_PATTERNS_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        r"\bbypass\s+(?:the\s+)?pin\b",
        r"\bskip\s+(?:the\s+)?pin\b",
        r"\bwithout\s+(?:the\s+)?pin\b",
    ),
    "ar": (
        r"تخط(?:ي|ى)\s+(?:رمز\s+)?(?:ال)?pin",
        r"تجاوز\s+(?:رمز\s+)?(?:ال)?pin",
        r"بدون\s+(?:رمز\s+)?(?:ال)?pin",
    ),
    "fr": (
        r"contourner\s+(?:le\s+)?pin",
        r"sans\s+(?:le\s+)?pin",
        r"passer\s+(?:le\s+)?pin",
    ),
    "es": (
        r"omit(?:ir|e|a|as)\s+(?:el\s+)?pin",
        r"salt(?:ar|e|a|as)\s+(?:el\s+)?pin",
        r"sin\s+(?:el\s+)?pin",
    ),
    "ja": (
        r"pin\s*(?:を)?\s*(?:スキップ|バイパス|回避)",
        r"pin\s*なしで",
    ),
    "ko": (
        r"pin\s*(?:을|를)?\s*(?:건너뛰|우회|생략)",
        r"pin\s*없이",
    ),
    "zh": (
        r"绕过\s*pin",
        r"跳过\s*pin",
        r"不(?:输入|使用)\s*pin",
    ),
}


_CRYPTO_ACTION_PATTERNS_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        r"\bbuy\s+(?:btc|eth|sol|xmr|crypto)\b",
        r"\bsell\s+(?:btc|eth|sol|xmr|crypto)\b",
        r"\bswap\b",
        r"\btrade\s+(?:crypto|btc|eth)\b",
        r"\bstake\b",
    ),
    "ar": (
        r"اشتري?\s+(?:btc|eth|sol|xmr|بيتكوين|إيثريوم|كريبتو)",
        r"بع\s+(?:btc|eth|sol|xmr|بيتكوين|إيثريوم|كريبتو)",
        r"استبدل\s+(?:btc|eth|sol|xmr|كريبتو)",
    ),
    "fr": (
        r"acheter\s+(?:btc|eth|sol|xmr|des\s+crypto)",
        r"vendre\s+(?:btc|eth|sol|xmr|des\s+crypto)",
        r"[ée]changer\s+(?:btc|eth|sol|xmr)",
    ),
    "es": (
        r"comprar\s+(?:btc|eth|sol|xmr|cripto)",
        r"vender\s+(?:btc|eth|sol|xmr|cripto)",
        r"intercambiar\s+(?:btc|eth|sol|xmr)",
    ),
    "ja": (
        r"(?:btc|eth|sol|xmr|ビットコイン|イーサリアム|仮想通貨)\s*を?\s*(?:買|売|交換|スワップ)",
    ),
    "ko": (
        r"(?:btc|eth|sol|xmr|비트코인|이더리움|암호화폐)\s*(?:을|를)?\s*(?:사|팔|교환|스왑)",
    ),
    "zh": (
        r"(?:购买|买入|买)\s*(?:btc|eth|sol|xmr|加密货币|比特币)",
        r"(?:出售|卖出|卖)\s*(?:btc|eth|sol|xmr|加密货币|比特币)",
        r"兑换\s*(?:btc|eth|sol|xmr)",
    ),
}


_XMR_SCANNER_PATTERNS_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": (
        r"\bwhy\s+(?:can(?:not|'t)|is\s+not)\s+(?:i\s+)?see\s+(?:my\s+)?xmr\b",
        r"\bmonero\s+balance\b",
        r"\bxmr\s+balance\b",
    ),
    "ar": (
        r"(?:رصيد|ميزان)\s+(?:xmr|مونيرو)",
        r"لماذا\s+لا\s+أرى\s+(?:xmr|مونيرو)",
    ),
    "fr": (
        r"solde\s+(?:xmr|monero)",
        r"pourquoi\s+je\s+ne\s+vois\s+pas\s+(?:xmr|monero)",
    ),
    "es": (
        r"saldo\s+(?:xmr|monero)",
        r"por\s+qu[ée]\s+no\s+veo\s+(?:xmr|monero)",
    ),
    "ja": (
        r"(?:xmr|monero|モネロ)\s*(?:の)?\s*(?:残高|バランス)",
    ),
    "ko": (
        r"(?:xmr|monero|모네로)\s*잔(?:액|고)",
    ),
    "zh": (
        r"(?:xmr|monero|门罗)\s*(?:的)?\s*(?:余额|余额是多少)",
    ),
}





def _compile_bundle(
    src: dict[str, tuple[str, ...]],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for lang, patterns in src.items():
        for p in patterns:
            out.append((lang, re.compile(p, re.IGNORECASE | re.UNICODE)))
    return tuple(out)


_DELETE_VAULT_COMPILED = _compile_bundle(_DELETE_VAULT_PATTERNS_BY_LANG)
_WHAT_IS_COMPILED = _compile_bundle(_WHAT_IS_VAULTAI_PATTERNS_BY_LANG)
_FORGOT_PIN_COMPILED = _compile_bundle(_FORGOT_PIN_PATTERNS_BY_LANG)
_SECRET_MATERIAL_COMPILED = _compile_bundle(
    _SECRET_MATERIAL_PATTERNS_BY_LANG)
_PIN_BYPASS_COMPILED = _compile_bundle(_PIN_BYPASS_PATTERNS_BY_LANG)
_CRYPTO_ACTION_COMPILED = _compile_bundle(_CRYPTO_ACTION_PATTERNS_BY_LANG)
_XMR_SCANNER_COMPILED = _compile_bundle(_XMR_SCANNER_PATTERNS_BY_LANG)




def detect_language(text: str) -> Optional[str]:
    """Return a 2-letter code guess for the message, or None."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None


    counts: dict[str, int] = {}
    for ch in s:
        cp = ord(ch)
        for lang, ranges in _UNICODE_BLOCK_LANG:
            for lo, hi in ranges:
                if lo <= cp <= hi:
                    counts[lang] = counts.get(lang, 0) + 1
                    break
    if counts:

        return max(counts.items(), key=lambda kv: kv[1])[0]


    padded = f" {s.lower()} "
    for lang, kws in _LATIN_KEYWORDS_BY_LANG.items():
        for kw in kws:
            needle = str(kw or "").lower()
            bare = needle.strip()
            if (
                bare
                and len(bare) <= 3
                and re.fullmatch(r"[a-z]+", bare)
            ):
                if re.search(rf"(?<![a-z]){re.escape(bare)}(?![a-z])", padded):
                    return lang
                continue
            if needle in padded:
                return lang

    return None


def normalise_locale_code(raw: Optional[str]) -> Optional[str]:
    """Normalise a locale string (e.g. 'ko-KR', 'zh_Hans_TW') to a 2-letter
    supported code, or None if unsupported / empty."""
    if not raw:
        return None
    if not isinstance(raw, str):
        return None
    lowered = raw.strip().lower()
    if not lowered:
        return None

    lang = re.split(r"[-_,;]", lowered, maxsplit=1)[0][:2]
    if lang in SUPPORTED_REPLY_LANGUAGE_CODES:
        return lang
    return None


def resolve_reply_language(
    *,
    detected_from_message: Optional[str],
    app_locale_hint: Optional[str],
    header_locale_hint: Optional[str] = None,
) -> str:
    """Decide what language VaultAI should reply in.

    Priority (highest wins):
      1. Detected non-English language of the current message.
      2. The user's explicit app_locale (Settings selection).
      3. English.

    The HTTP Accept-Language header is deliberately not used for
    chat replies. Device/browser locale should not make an English
    conversation drift after a short sentence or a person's name.
    """
    if detected_from_message and (
        detected_from_message in SUPPORTED_REPLY_LANGUAGE_CODES
        and detected_from_message != DEFAULT_REPLY_LANGUAGE
    ):
        return detected_from_message
    norm = normalise_locale_code(app_locale_hint)
    if norm:
        return norm
    return DEFAULT_REPLY_LANGUAGE




def _match_bundle(
    bundle: tuple[tuple[str, re.Pattern[str]], ...],
    text: str,
) -> Optional[str]:
    if not isinstance(text, str) or not text.strip():
        return None
    for lang, pat in bundle:
        if pat.search(text):
            return lang
    return None


def matches_delete_vault_intent(text: str) -> Optional[str]:
    """Return the language whose delete-vault pattern matched, or None."""
    return _match_bundle(_DELETE_VAULT_COMPILED, text)


def matches_what_is_vaultai_intent(text: str) -> Optional[str]:
    return _match_bundle(_WHAT_IS_COMPILED, text)


def matches_forgot_pin_intent(text: str) -> Optional[str]:
    return _match_bundle(_FORGOT_PIN_COMPILED, text)


def matches_secret_material_request(text: str) -> Optional[str]:
    return _match_bundle(_SECRET_MATERIAL_COMPILED, text)


def matches_pin_bypass_request(text: str) -> Optional[str]:
    return _match_bundle(_PIN_BYPASS_COMPILED, text)


def matches_crypto_action_request(text: str) -> Optional[str]:
    return _match_bundle(_CRYPTO_ACTION_COMPILED, text)


def matches_xmr_scanner_question(text: str) -> Optional[str]:
    return _match_bundle(_XMR_SCANNER_COMPILED, text)




_REFUSAL_COPY: dict[str, dict[str, str]] = {
    "secret_material": {
        "en": "I can never reveal seed phrases, mnemonics, or private "
              "keys, even inside your vault. That protects your funds "
              "if this session is ever compromised. Open the wallet "
              "directly, unlock with your PIN, and reveal there.",
        "ar": "لا يمكنني أبدًا الكشف عن عبارات البذرة أو المفاتيح "
              "الخاصة، حتى داخل خزينتك. افتح المحفظة مباشرة وأدخل "
              "رمز PIN لعرضها هناك.",
        "fr": "Je ne peux jamais révéler la phrase de récupération, "
              "les mnémoniques ni les clés privées, même dans votre "
              "coffre. Ouvrez le portefeuille, entrez votre PIN, et "
              "consultez-la depuis là.",
        "es": "Nunca puedo revelar frases semilla, mnemónicas ni "
              "claves privadas, ni siquiera dentro de tu bóveda. Abre "
              "la billetera, ingresa tu PIN y consúltala allí.",
        "ja": "シードフレーズ、ニーモニック、秘密鍵は保管庫内でも"
              "決してお見せできません。ウォレットを開き、PIN で"
              "アンロックしてご確認ください。",
        "ko": "시드 문구, 니모닉, 개인 키는 보관소 안에서도 절대 "
              "공개할 수 없습니다. 지갑을 직접 열고 PIN 으로 잠금 "
              "해제한 뒤 확인하세요.",
        "zh": "我永远不能显示助记词、种子短语或私钥,即使在你的"
              "保险库内。请直接打开钱包并使用 PIN 解锁查看。",
    },
    "pin_bypass": {
        "en": "The PIN gate cannot be skipped. It is what proves the "
              "unlock is really you.",
        "ar": "لا يمكن تخطي رمز PIN. هو الذي يثبت أن فتح الخزينة أنت.",
        "fr": "Le PIN ne peut pas être contourné. C'est ce qui prouve "
              "que le déverrouillage vient bien de vous.",
        "es": "El PIN no se puede omitir. Es lo que demuestra que "
              "quien desbloquea eres tú.",
        "ja": "PIN の入力は省略できません。それがロック解除が"
              "本人であることの証拠です。",
        "ko": "PIN 인증은 건너뛸 수 없습니다. 잠금 해제가 본인인지를 "
              "증명하는 절차입니다.",
        "zh": "无法跳过 PIN 步骤。它证明解锁的确是你本人。",
    },
    "crypto_action": {
        "en": "VaultAI does not buy, sell, swap, trade, stake, or "
              "bridge crypto. It stores encrypted wallet records only "
              "and never signs or broadcasts transactions.",
        "ar": "لا يقوم VaultAI بشراء أو بيع أو تبادل أو تداول أو "
              "رهن العملات المشفرة. يخزّن فقط سجلات محفظة مشفّرة ولا "
              "يوقّع ولا يبث المعاملات.",
        "fr": "VaultAI n'achète, ne vend, n'échange, ne trade, ne "
              "stake ni ne fait de bridge de crypto. Il stocke "
              "uniquement des enregistrements chiffrés et ne signe "
              "ni ne diffuse jamais de transactions.",
        "es": "VaultAI no compra, vende, intercambia, opera, hace "
              "staking ni bridge de crypto. Solo guarda registros "
              "cifrados y nunca firma ni transmite transacciones.",
        "ja": "VaultAI は暗号資産の売買・スワップ・取引・"
              "ステーキング・ブリッジは行いません。暗号化された"
              "ウォレット記録の保管のみで、署名や送信は一切しません。",
        "ko": "VaultAI 는 암호화폐를 사거나 팔거나 교환하거나 "
              "거래하거나 스테이킹하거나 브리징하지 않습니다. "
              "암호화된 지갑 기록만 저장하며 서명이나 전송을 하지 "
              "않습니다.",
        "zh": "VaultAI 不会买入、卖出、兑换、交易、质押或桥接加密"
              "货币。它只存储加密的钱包记录,永不签名或广播交易。",
    },
}


def localised_refusal_copy(category: str, reply_lang: str) -> str:
    """Return refusal copy for the requested category in the requested
    language, falling back to English."""
    per_lang = _REFUSAL_COPY.get(category, {})
    if reply_lang in per_lang:
        return per_lang[reply_lang]
    return per_lang.get("en", "")


def translate_to_english_router_query(text: str) -> Optional[str]:
    """If the message matches a known multilingual intent, return the
    canonical English string that the router understands. Return None
    if no multilingual pattern matched — in which case the raw text is
    already whatever the caller intended.

    This intentionally maps to a SHORT high-signal English phrase, not
    an actual translation. The goal is only to trip the router's
    intent regex, not to produce a natural-language rewrite.

    Priority (safety first — refusals come before FAQ intents so a
    French user asking "révèle-moi la seed phrase" refuses before it
    ever tries the FAQ router):
      * secret material    → "reveal my seed phrase"
      * PIN bypass         → "bypass the pin"
      * crypto buy/sell    → "buy bitcoin"
      * delete vault       → "delete my vault"
      * forgot PIN         → "forgot my pin"
      * what-is-vaultai    → "what is vaultai"
      * XMR scanner        → "why can't i see my monero balance"
    """
    if not isinstance(text, str) or not text.strip():
        return None

    if matches_secret_material_request(text):
        return "reveal my seed phrase"
    if matches_pin_bypass_request(text):
        return "bypass the pin"
    if matches_crypto_action_request(text):

        return "buy eth"
    if matches_delete_vault_intent(text):
        return "delete my vault"
    if matches_forgot_pin_intent(text):
        return "forgot my pin"
    if matches_what_is_vaultai_intent(text):
        return "what is vaultai"
    if matches_xmr_scanner_question(text):
        return "why can't i see my monero balance"
    return None


__all__ = [
    "SUPPORTED_REPLY_LANGUAGE_CODES",
    "DEFAULT_REPLY_LANGUAGE",
    "detect_language",
    "normalise_locale_code",
    "resolve_reply_language",
    "matches_delete_vault_intent",
    "matches_what_is_vaultai_intent",
    "matches_forgot_pin_intent",
    "matches_secret_material_request",
    "matches_pin_bypass_request",
    "matches_crypto_action_request",
    "matches_xmr_scanner_question",
    "translate_to_english_router_query",
    "localised_refusal_copy",
]
