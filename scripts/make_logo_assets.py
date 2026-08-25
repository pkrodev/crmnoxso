"""Generuje warianty logo używane w aplikacji.

    python scripts/make_logo_assets.py

Wejście: ``logo.png`` w katalogu głównym (681×380, PNG z przezroczystością).
Zmierzony skład pliku: bursztyn #FFAF00 — 31,6% pikseli, czerń — 28,3%,
przezroczystość — 40,1%.

Powstają trzy pliki w ``app/static/img/``:

``logo.png``
    kopia oryginału — na jasne tła.

``logo-light.png``
    czerń zamieniona na biel, bursztyn nietknięty. **Konieczny**, bo sidebar ma
    tło ink-950: czarny napis „NOXSO" i sylwetka traktora zlałyby się z tłem.
    Sprawdzone — czarne piksele zajmują całą dolną część kadru.

``favicon.png``
    kadr na sam traktor, 32×32. Pełne logo jest za szerokie (681×380), żeby
    cokolwiek dało się z niego odczytać w tym rozmiarze.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "logo.png"
TARGET_DIR = ROOT / "app" / "static" / "img"


def _is_amber(r: int, g: int, b: int) -> bool:
    """Czy piksel należy do bursztynu marki (#FFAF00) lub jego antyaliasingu."""
    return r > 180 and 90 < g < 230 and b < 90


def to_light_variant(image: Image.Image) -> Image.Image:
    """Wariant na ciemne tło: negatyw szarości, bursztyn nietknięty.

    Zwykła zamiana czerni na biel nie wystarcza. Traktor jest narysowany jako
    czarna sylwetka z BIAŁYMI liniami detali w środku — po samym rozjaśnieniu
    czerni detale zlałyby się z korpusem i zostałaby plama.

    Odwracamy więc jasność: czarny korpus robi się biały, białe linie detali
    czarne, a bursztyn zostaje bursztynem. Pod napisem „NOXSO" tło jest
    przezroczyste (zmierzone), więc czarne „NO" na sidebarze ink-950 znikłoby
    bez tej zamiany.
    """
    image = image.convert("RGBA")
    pixels = image.load()
    width, height = image.size

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0 or _is_amber(r, g, b):
                continue
            pixels[x, y] = (255 - r, 255 - g, 255 - b, a)

    return image


# Zmierzona ramka samego traktora, bez napisu „NOXSO": x 0–469, y 37–264.
TRACTOR_BOX = (0, 37, 469, 264)


def crop_tractor(image: Image.Image, size: int = 32) -> Image.Image:
    """Wycina kadr z traktorem na favicon.

    Pełne logo ma proporcje 681×380 — w kwadracie 32×32 zrobiłaby się z niego
    nieczytelna kreska. Bierzemy więc sam traktor, wyśrodkowany w kwadracie,
    z bursztynowym tłem marki zamiast przezroczystości (ikona w karcie
    przeglądarki i tak leży na jasnym tle).
    """
    image = image.convert("RGBA")
    left, top, right, bottom = TRACTOR_BOX
    cropped = image.crop((left, top, right, bottom))

    side = max(cropped.width, cropped.height)
    square = Image.new("RGBA", (side, side), (255, 175, 0, 255))
    square.alpha_composite(
        cropped, ((side - cropped.width) // 2, (side - cropped.height) // 2)
    )
    return square.resize((size, size), Image.LANCZOS)


def main() -> int:
    if not SOURCE.exists():
        print(f"Nie znaleziono pliku {SOURCE}", file=sys.stderr)
        return 1

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    original = Image.open(SOURCE).convert("RGBA")

    original.save(TARGET_DIR / "logo.png")
    print(f"logo.png            {original.size[0]}×{original.size[1]}")

    light = to_light_variant(original.copy())
    light.save(TARGET_DIR / "logo-light.png")
    print(f"logo-light.png      {light.size[0]}×{light.size[1]}  (czerń → biel)")

    favicon = crop_tractor(original, 64)
    favicon.save(TARGET_DIR / "favicon.png")
    crop_tractor(original, 32).save(TARGET_DIR / "favicon.ico", sizes=[(32, 32)])
    print("favicon.png (64) / favicon.ico (32)   kadr na traktor")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
