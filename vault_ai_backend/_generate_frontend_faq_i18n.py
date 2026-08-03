"""Guard for the retired backend-to-frontend FAQ generator.

The complete frontend Help Center is canonical and must never be generated
from the smaller conversational backend FAQ. Backend translations currently
fall back to reviewed English in ``vault_faq_content_i18n.py``.
"""

from __future__ import annotations

from pathlib import Path

FRONTEND_CANONICAL = (
    Path(__file__).resolve().parent.parent
    / "vault_ai_frontend" / "lib" / "help_center_content.dart"
)
FRONTEND_I18N = (
    Path(__file__).resolve().parent.parent
    / "vault_ai_frontend" / "lib" / "help_center_content_i18n.dart"
)


def main() -> None:
    """Validate canonical files exist; deliberately write nothing."""
    missing = [path for path in (FRONTEND_CANONICAL, FRONTEND_I18N)
               if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing canonical Help Center source: "
            + ", ".join(str(path) for path in missing)
        )
    print("Frontend Help Center is canonical; no files were generated.")


if __name__ == "__main__":
    main()
