from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PIL import Image

from drone.ui import fonts
from drone.ui.setup import effects


class _FakeSurface:
    def __init__(self, size=(800, 600)):
        self._size = size
        self.alpha = None

    def get_size(self):
        return self._size

    def set_alpha(self, value):
        self.alpha = value


class _FakeScreen(_FakeSurface):
    def __init__(self, size=(800, 600)):
        super().__init__(size)
        self.blitted = []

    def blit(self, surface, position):
        self.blitted.append(surface)


def test_fit_text_lascia_stare_il_testo_che_ci_sta():
    font = fonts.sans(20)
    assert effects.fit_text("Percorso breve", font, 10_000) == "Percorso breve"


def test_fit_text_taglia_con_l_ellissi_e_rientra_nella_larghezza():
    font = fonts.sans(20)
    ridotto = effects.fit_text("Verifica della sicurezza collettiva", font, 120)
    assert ridotto.endswith("…")
    assert font.getlength(ridotto) <= 120


def test_wrap_text_manda_a_capo_sugli_spazi():
    font = fonts.sans(20)
    righe = effects.wrap_text("alfa beta gamma delta epsilon", font, 90, max_lines=5)
    assert len(righe) > 1
    assert " ".join(righe) == "alfa beta gamma delta epsilon"
    assert all(font.getlength(r) <= 90 for r in righe)


def test_wrap_text_rispetta_il_numero_massimo_di_righe():
    font = fonts.sans(20)
    righe = effects.wrap_text("alfa beta gamma delta epsilon zeta eta", font, 90, max_lines=2)
    assert len(righe) == 2
    assert righe[-1].endswith("…")


def test_wrap_text_su_testo_vuoto_non_produce_righe():
    font = fonts.sans(20)
    assert effects.wrap_text("", font, 200, max_lines=3) == []
    assert effects.wrap_text("   ", font, 200, max_lines=3) == []


def test_wrap_text_tiene_la_parola_piu_lunga_della_riga():
    font = fonts.sans(20)
    righe = effects.wrap_text("supercalifragilistichespiralidoso", font, 40, max_lines=3)
    assert righe == ["supercalifragilistichespiralidoso"]


def test_lo_sfondo_ha_la_misura_chiesta_ed_e_una_copia():
    primo = effects.grid_background(120, 80, 20, 3)
    secondo = effects.grid_background(120, 80, 20, 3)
    assert primo.size == (120, 80)
    assert primo is not secondo
    assert primo.tobytes() == secondo.tobytes()


def test_lo_sfondo_e_piu_chiaro_al_centro_che_negli_angoli():
    img = effects.grid_background(120, 80, 0, 0)
    assert sum(img.getpixel((60, 28))) > sum(img.getpixel((0, 79)))


def test_le_crocette_della_griglia_si_staccano_dal_fondo():
    liscio = effects.grid_background(120, 80, 0, 0)
    griglia = effects.grid_background(120, 80, 40, 4)
    assert griglia.getpixel((20, 20)) != liscio.getpixel((20, 20))


def test_il_bottone_resta_scuro_e_si_accende_d_azzurro_sotto_il_cursore():
    box = (60, 30, 240, 90)
    spento = Image.new("RGB", (300, 120), (0, 0, 0))
    effects.draw_hover_button(spento, box, "Conferma", fonts.sans_bold(20), unit=1.0)
    acceso = Image.new("RGB", (300, 120), (0, 0, 0))
    effects.draw_hover_button(acceso, box, "Conferma", fonts.sans_bold(20), unit=1.0, hover=True)
    assert sum(spento.getpixel((80, 45))) < 100
    assert acceso.getpixel((80, 45)) == effects.CYAN_FILL


def test_la_dissolvenza_disegna_subito_la_prima_schermata():
    screen = _FakeScreen()
    prima = _FakeSurface()
    effects.CrossfadeBlitter(duration_sec=10.0).draw(screen, prima)
    assert screen.blitted == [prima]


def test_la_dissolvenza_sovrappone_le_due_schermate_al_cambio():
    blitter = effects.CrossfadeBlitter(duration_sec=10.0)
    screen = _FakeScreen()
    prima, seconda = _FakeSurface(), _FakeSurface()

    blitter.draw(screen, prima)
    screen.blitted.clear()
    blitter.draw(screen, seconda)

    assert screen.blitted == [prima, seconda]
    assert seconda.alpha is None


def test_la_dissolvenza_finita_disegna_la_sola_schermata_nuova():
    blitter = effects.CrossfadeBlitter(duration_sec=10.0)
    screen = _FakeScreen()
    prima, seconda = _FakeSurface(), _FakeSurface()

    blitter.draw(screen, prima)
    blitter.draw(screen, seconda)
    blitter._started_at -= 100.0
    screen.blitted.clear()
    blitter.draw(screen, seconda)

    assert screen.blitted == [seconda]


def test_la_dissolvenza_non_incrocia_misure_diverse():
    blitter = effects.CrossfadeBlitter(duration_sec=10.0)
    screen = _FakeScreen()
    prima = _FakeSurface((800, 600))
    seconda = _FakeSurface((1024, 768))

    blitter.draw(screen, prima)
    screen.blitted.clear()
    blitter.draw(screen, seconda)

    assert screen.blitted == [seconda]


def test_le_finestre_senza_pygame_avviato_non_esplodono():
    effects.focus_window()
    effects.maximize_window()


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
