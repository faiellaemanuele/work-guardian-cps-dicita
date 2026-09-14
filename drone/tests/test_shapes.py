from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
from PIL import Image, ImageDraw

from drone.ui import shapes


def test_il_bagliore_esce_dal_bordo_del_riquadro():
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    shapes.glow_box(img, (30, 30, 70, 70), radius=6, edge=(0, 200, 255), width=2,
                    glow=4, glow_alpha=200)
    assert img.getpixel((27, 50)) != (0, 0, 0)
    assert img.getpixel((2, 50)) == (0, 0, 0)


def test_senza_bagliore_fuori_dal_riquadro_non_si_disegna():
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    shapes.glow_box(img, (30, 30, 70, 70), radius=6, edge=(0, 200, 255), width=2,
                    fill=(10, 20, 30))
    assert img.getpixel((27, 50)) == (0, 0, 0)
    assert img.getpixel((50, 50)) == (10, 20, 30)
    assert img.getpixel((30, 50)) == (0, 200, 255)


def test_il_riempimento_trasparente_si_fonde_su_rgba():
    img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    shapes.glow_box(img, (10, 10, 50, 50), radius=4, fill=(255, 0, 0, 128))
    r, _g, _b, a = img.getpixel((30, 30))
    assert r > 200
    assert 100 <= a <= 160
    assert img.getpixel((2, 2))[3] == 0


def test_il_riquadro_che_esce_dall_immagine_non_esplode():
    img = Image.new("RGB", (40, 40), (0, 0, 0))
    shapes.glow_box(img, (-10, -10, 20, 20), radius=4, edge=(255, 255, 255), width=2,
                    glow=6, glow_alpha=255)
    assert img.getpixel((20, 5)) != (0, 0, 0)


def test_la_cache_dei_bagliori_non_cresce_senza_limite():
    shapes._GLOW_CACHE.clear()
    img = Image.new("RGB", (80, 80))
    for lato in range(shapes._GLOW_CACHE_MAX + 10):
        shapes.glow_box(img, (5, 5, 10 + lato, 40), radius=3, edge=(255, 255, 255),
                        width=1, glow=2, glow_alpha=100)
    assert len(shapes._GLOW_CACHE) <= shapes._GLOW_CACHE_MAX
    shapes._GLOW_CACHE.clear()


def _disco_bianco(draw, x, y, k):
    draw.ellipse((x - 15 * k, y - 15 * k, x + 15 * k, y + 15 * k), fill=(255, 255, 255))


def test_il_disegno_sovracampionato_ammorbidisce_i_bordi():
    netto = Image.new("RGB", (40, 40), (0, 0, 0))
    _disco_bianco(ImageDraw.Draw(netto), 20, 20, 1)
    liscio = Image.new("RGB", (40, 40), (0, 0, 0))
    shapes.paint_supersampled(liscio, (0, 0, 40, 40), (20, 20), _disco_bianco)

    def sfumati(img):
        rosso = np.asarray(img)[:, :, 0]
        return int(((rosso > 0) & (rosso < 255)).sum())

    assert sfumati(netto) == 0
    assert sfumati(liscio) > 0
    assert liscio.getpixel((20, 20)) == (255, 255, 255)


def test_il_disegno_sovracampionato_non_scurisce_i_bordi_su_rgba():
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    shapes.paint_supersampled(img, (0, 0, 40, 40), (20, 20), _disco_bianco)
    pixel = np.asarray(img)
    bordo = (pixel[:, :, 3] > 0) & (pixel[:, :, 3] < 255)
    assert bordo.any()
    assert bool((pixel[:, :, 0][bordo] >= 250).all())


def test_il_disegno_sovracampionato_che_esce_dall_immagine_non_esplode():
    img = Image.new("RGB", (20, 20), (0, 0, 0))
    shapes.paint_supersampled(img, (-10, -10, 10, 10), (0, 0), _disco_bianco)
    assert img.getpixel((2, 2)) == (255, 255, 255)


def test_gli_angoli_segnano_i_quattro_spigoli_e_lasciano_vuoto_il_centro():
    img = Image.new("RGB", (50, 50), (0, 0, 0))
    shapes.corner_brackets(ImageDraw.Draw(img), (5, 5, 44, 44), arm=8, width=2, color=(0, 255, 0))
    for punto in ((5, 5), (44, 5), (5, 44), (44, 44)):
        assert img.getpixel(punto) == (0, 255, 0)
    assert img.getpixel((25, 25)) == (0, 0, 0)
    assert img.getpixel((25, 5)) == (0, 0, 0)


def _run_all() -> int:
    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append((name, exc))
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"[ OK ] {name}")

    print("-" * 60)
    print(f"Totale: {len(tests)}  |  passati: {passed}  |  falliti: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
