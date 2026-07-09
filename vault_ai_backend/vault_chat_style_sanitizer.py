

from __future__ import annotations

import re
import unicodedata
from typing import Optional


MAX_EMOJIS_PER_REPLY: int = 3


_STIFF_PREAMBLES: tuple[tuple[str, str], ...] = (
    (r"^\s*i\s+am\s+(?:an?\s+)?(?:ai|artificial\s+intelligence)[^.!?]*[.!?]\s*",
     "dropped_i_am_ai"),
    (r"^\s*i(?:'|’)?m\s+(?:an?\s+)?(?:ai|artificial\s+intelligence|ai\s+assistant)[^.!?]*[.!?]\s*",
     "dropped_im_ai"),
    (r"^\s*i(?:'|’)?m\s+designed\s+to[^.!?]*[.!?]\s*",
     "dropped_im_designed_to"),
    (r"^\s*i\s+am\s+designed\s+to[^.!?]*[.!?]\s*",
     "dropped_i_am_designed_to"),
    (r"^\s*as\s+(?:an?\s+)?ai(?:\s+assistant)?[^.!?]*[.!?]\s*",
     "dropped_as_an_ai"),
    (r"^\s*as\s+a\s+language\s+model[^.!?]*[.!?]\s*",
     "dropped_as_language_model"),
    (r"^\s*as\s+your\s+(?:virtual\s+)?assistant[^.!?]*[.!?]\s*",
     "dropped_as_your_assistant"),
    (r"^\s*i(?:'|’)?m\s+here\s+to\s+(?:help|assist)\s+you\s+with[^.!?]*[.!?]\s*",
     "dropped_here_to_help_with"),
)


_BOLD_PATTERN = re.compile(r"\*\*([^\n*][^*\n]*?)\*\*")
_ITALIC_PATTERN = re.compile(
    r"(?<![*\w])\*([^\s*][^\n*]*?[^\s*])\*(?!\*)",
)
_UNDERSCORE_BOLD = re.compile(r"__([^_\n][^_\n]*?)__")
_HEADER_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)


_EMOJI_RE = re.compile(
    "["                                                  
    "\U0001F300-\U0001F5FF"                                         
    "\U0001F600-\U0001F64F"                             
    "\U0001F680-\U0001F6FF"                                           
    "\U0001F700-\U0001F77F"                                      
    "\U0001F780-\U0001F7FF"                                    
    "\U0001F800-\U0001F8FF"                                         
    "\U0001F900-\U0001F9FF"                                        
    "\U0001FA00-\U0001FA6F"                                                     
    "\U0001FA70-\U0001FAFF"                                             
    "\U00002600-\U000026FF"                                
    "\U00002700-\U000027BF"                            
    "\U0001F1E6-\U0001F1FF"                         
    "]"
)


_NUMBERED_LIST_BLOCK = re.compile(
    r"(?ms)^\s*(?:1[.)]\s+.+\n)"
    r"(?:^\s*[2-9][.)]\s+.+\n?)+",
)
_NUMBERED_LIST_ITEM = re.compile(
    r"^\s*\d+[.)]\s+(?P<text>.+?)\s*$",
    re.MULTILINE,
)


_INTRO_DEDUPE_THRESHOLD: float = 0.7


def _strip_markdown_decorations(
    text: str, slugs: set[str],
) -> str:


    new = _BOLD_PATTERN.sub(r"\1", text)
    if new != text:
        slugs.add("stripped_bold")
        text = new
    new = _UNDERSCORE_BOLD.sub(r"\1", text)
    if new != text:
        slugs.add("stripped_underscore_bold")
        text = new
    new = _ITALIC_PATTERN.sub(r"\1", text)
    if new != text:
        slugs.add("stripped_italic")
        text = new
    new = _HEADER_PATTERN.sub("", text)
    if new != text:
        slugs.add("stripped_heading")
        text = new
    return text


def _drop_stiff_preamble(text: str, slugs: set[str]) -> str:


    for pattern, slug in _STIFF_PREAMBLES:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            slugs.add(slug)
            text = text[m.end():]
                                                          
            break
    return text


def _collapse_numbered_list(text: str, slugs: set[str]) -> str:


    def _replace(m: re.Match) -> str:
        block = m.group(0)
        items = [
            it.group("text").strip()
            for it in _NUMBERED_LIST_ITEM.finditer(block)
        ]
        if not items:
            return block
        slugs.add("collapsed_list")
                                                             
        cleaned: list[str] = []
        for it in items:
            cleaned.append(
                _ITALIC_PATTERN.sub(r"\1",
                _BOLD_PATTERN.sub(r"\1", it))
            )
        if all(len(it) <= 60 for it in cleaned):
            return ", ".join(cleaned) + "\n"
        return "\n".join(f"- {it}" for it in cleaned) + "\n"

    new = _NUMBERED_LIST_BLOCK.sub(_replace, text)
    return new


def _normalised_for_intro_compare(line: str) -> str:


    s = unicodedata.normalize("NFKC", line).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def _jaccard(a: str, b: str) -> float:
    a_set = set(a.split())
    b_set = set(b.split())
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)


def _dedupe_intro_lines(text: str, slugs: set[str]) -> str:


    lines = text.split("\n")
    non_empty: list[tuple[int, str]] = [
        (idx, ln) for idx, ln in enumerate(lines) if ln.strip()
    ]
    if len(non_empty) < 2:
        return text
    idx_a, line_a = non_empty[0]
    idx_b, line_b = non_empty[1]
    norm_a = _normalised_for_intro_compare(line_a)
    norm_b = _normalised_for_intro_compare(line_b)
    if not norm_a or not norm_b:
        return text
    sim = _jaccard(norm_a, norm_b)
    if sim >= _INTRO_DEDUPE_THRESHOLD:
        slugs.add("deduped_intro")
        del lines[idx_b]
        return "\n".join(lines)
    return text


def _cap_emoji_density(
    text: str, slugs: set[str],
    *, max_emojis: int = MAX_EMOJIS_PER_REPLY,
) -> str:


    matches = list(_EMOJI_RE.finditer(text))
    if len(matches) <= max_emojis:
        return text
    slugs.add("capped_emojis")
    out_chars = list(text)
                                                             
            
    extras = matches[max_emojis:]
    for m in reversed(extras):
        out_chars[m.start():m.end()] = []
    return "".join(out_chars)


def _trim_whitespace(text: str) -> str:


    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sanitize_reply_style(
    reply_text: Optional[str],
    *, max_emojis: int = MAX_EMOJIS_PER_REPLY,
) -> tuple[str, frozenset[str]]:


    slugs: set[str] = set()
    if not reply_text:
        return "", frozenset(slugs)
    text = str(reply_text)
                                                                 
                                                                
    try:
        from vault_device_safety_copy import rewrite_overclaim
        text, overclaim_slug = rewrite_overclaim(text)
        if overclaim_slug:
            slugs.add(overclaim_slug)
    except Exception:
        pass
    text = _drop_stiff_preamble(text, slugs)
    text = _strip_markdown_decorations(text, slugs)
    text = _collapse_numbered_list(text, slugs)
    text = _dedupe_intro_lines(text, slugs)
    text = _cap_emoji_density(text, slugs, max_emojis=max_emojis)
    text = _trim_whitespace(text)
    return text, frozenset(slugs)


__all__ = [
    "MAX_EMOJIS_PER_REPLY",
    "sanitize_reply_style",
]
