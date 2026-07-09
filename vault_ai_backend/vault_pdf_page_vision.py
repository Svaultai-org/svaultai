

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Optional


logger = logging.getLogger(__name__)


MAX_PDF_PAGES_PER_DOC: int = int(
    os.getenv("VAULTAI_PDF_VISION_MAX_PAGES", "3"),
)
DEFAULT_RENDER_DPI: int = int(
    os.getenv("VAULTAI_PDF_VISION_DPI", "144"),
)

                                                        
MAX_PNG_BYTES: int = int(
    os.getenv("VAULTAI_PDF_VISION_MAX_PNG_BYTES", str(6 * 1024 * 1024)),
)


_VISION_TIMEOUT_SECONDS: int = int(
    os.getenv("VAULTAI_VISION_TIMEOUT_S", "30"),
)


def render_pdf_pages_to_png(
    pdf_bytes: bytes,
    *,
    max_pages: int = MAX_PDF_PAGES_PER_DOC,
    dpi: int = DEFAULT_RENDER_DPI,
) -> tuple[list[bytes], int]:


    if not pdf_bytes:
        return [], 0
    try:
        import fitz
    except Exception:
        logger.exception("[PDF-PAGE-VISION] fitz import failed")
        return [], 0

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        logger.exception("[PDF-PAGE-VISION] fitz.open failed")
        return [], 0

    rendered: list[bytes] = []
    total_pages = 0
    try:
        total_pages = int(doc.page_count or 0)
        page_cap = min(total_pages, max(1, int(max_pages)))
        for i in range(page_cap):
            try:
                page = doc.load_page(i)
                pix = page.get_pixmap(dpi=int(dpi))
                png = pix.tobytes("png")
                if not png:
                    continue
                if len(png) > MAX_PNG_BYTES:
                                                           
                                                          
                    logger.warning(
                        "[PDF-PAGE-VISION] dropped oversize page "
                        "idx=%d size_bytes=%d limit=%d",
                        i, len(png), MAX_PNG_BYTES,
                    )
                    continue
                rendered.append(png)
            except Exception:
                logger.exception(
                    "[PDF-PAGE-VISION] render failed idx=%d", i,
                )
                continue
    finally:
        try:
            doc.close()
        except Exception:
            pass

    return rendered, total_pages


def _resolve_vision_model() -> str:
    try:
        from vault_config import ai as _ai_cfg
        return _ai_cfg().chat_model
    except Exception:
        return os.getenv("VAULTAI_VISION_MODEL") or ""


def _inspect_one_png_with_vision(
    png_bytes: bytes, question: str,
) -> Optional[str]:


    if not png_bytes or not question:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None

    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key:
        return None

    model = _resolve_vision_model()
    if not model:
        return None

    try:
        b64 = base64.b64encode(png_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        client = OpenAI(api_key=api_key, timeout=_VISION_TIMEOUT_SECONDS)
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are inspecting one page of a "
                            "PDF stored in a private user vault. "
                            "Be precise. If the page shows an "
                            "ID document, passport, driver "
                            "license, or identity card, state "
                            "the document type and the name "
                            "visible on it. Do NOT invent data. "
                            "If you can't tell, say so plainly.\n\n"
                            f"User's question: {question}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }],
            max_tokens=600,
            temperature=0.0,
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception:
        logger.exception("[PDF-PAGE-VISION] vision call failed")
        return None


def inspect_pdf_pages_with_vision(
    *,
    file_id: str,
    pdf_bytes: bytes,
    question: str,
    max_pages: int = MAX_PDF_PAGES_PER_DOC,
    dpi: int = DEFAULT_RENDER_DPI,
    vision_callable: Optional[Any] = None,
) -> dict:


    if vision_callable is None:
        vision_callable = _inspect_one_png_with_vision

    rendered, total_pages = render_pdf_pages_to_png(
        pdf_bytes, max_pages=max_pages, dpi=dpi,
    )
    pages_inspected = 0
    page_results: list[dict] = []
    for idx, png in enumerate(rendered):
        try:
            analysis = vision_callable(png, question)
        except Exception:
            logger.exception(
                "[PDF-PAGE-VISION] vision_callable raised "
                "file_id=%s idx=%d",
                (file_id or "")[:8], idx,
            )
            analysis = None
        pages_inspected += 1
        if not analysis:
            continue
        page_results.append({
            "page_index": idx,
            "analysis":   analysis,
        })

    budget_exceeded = total_pages > max(1, int(max_pages))

                                                        
    logger.info(
        "[PDF-PAGE-VISION] file_id=%s pages_inspected=%d "
        "total_pages=%d budget_exceeded=%s pages_with_text=%d",
        (file_id or "")[:8],
        pages_inspected,
        total_pages,
        budget_exceeded,
        len(page_results),
    )

    return {
        "pages_inspected": pages_inspected,
        "total_pages":     total_pages,
        "budget_exceeded": budget_exceeded,
        "page_results":    page_results,
    }


__all__ = [
    "MAX_PDF_PAGES_PER_DOC",
    "DEFAULT_RENDER_DPI",
    "MAX_PNG_BYTES",
    "render_pdf_pages_to_png",
    "inspect_pdf_pages_with_vision",
]
