#!/usr/bin/env python3
"""Generate every web brand image from the approved mobile master.

This script performs resizing/compositing only. It does not redesign or alter
the canonical SVaultAI mark.
"""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "assets" / "branding" / "vaultai-icon-1024.png"
FOREGROUND = (
    ROOT / "assets" / "branding" / "vaultai-icon-foreground-1024.png"
)
WEB = ROOT / "web"
ICONS = WEB / "icons"
BACKGROUND = (15, 17, 21, 255)


def resized(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.Resampling.LANCZOS)


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def maskable(foreground: Image.Image, size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), BACKGROUND)
    safe_size = round(size * 0.80)
    mark = resized(foreground, safe_size)
    offset = ((size - safe_size) // 2, (size - safe_size) // 2)
    canvas.alpha_composite(mark, offset)
    return canvas


def main() -> None:
    master = Image.open(MASTER).convert("RGBA")
    foreground = Image.open(FOREGROUND).convert("RGBA")
    if master.size != (1024, 1024) or foreground.size != (1024, 1024):
        raise SystemExit("Canonical branding sources must be 1024x1024")

    save_png(resized(master, 16), WEB / "favicon-16x16.png")
    save_png(resized(master, 32), WEB / "favicon-32x32.png")
    save_png(resized(master, 32), WEB / "favicon.png")
    save_png(resized(master, 180), WEB / "apple-touch-icon.png")
    save_png(resized(master, 192), ICONS / "Icon-192.png")
    save_png(resized(master, 512), ICONS / "Icon-512.png")
    save_png(maskable(foreground, 192), ICONS / "Icon-maskable-192.png")
    save_png(maskable(foreground, 512), ICONS / "Icon-maskable-512.png")

    # Multi-resolution ICO for browsers and pinned desktop shortcuts.
    master.convert("RGB").save(
        WEB / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )

    # Social card keeps the canonical artwork intact on the canonical dark
    # canvas; title and description remain machine-readable metadata.
    social = Image.new("RGBA", (1200, 630), BACKGROUND)
    social_icon = resized(master, 560)
    social.alpha_composite(social_icon, ((1200 - 560) // 2, 35))
    save_png(social, WEB / "og-image.png")


if __name__ == "__main__":
    main()
