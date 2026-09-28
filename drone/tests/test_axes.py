from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def _axes():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt, plt.subplots(figsize=(6, 4))


def test_numero_semplice_usa_il_meno_tipografico():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import plain_number
    assert plain_number(1000) == "1000"
    assert plain_number(0.25) == "0.25"
    assert plain_number(-0.5) == "−0.5"


def test_lo_stile_degli_assi_nasconde_la_cornice_in_alto_e_a_destra():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import style_axis
    plt, (fig, ax) = _axes()
    style_axis(ax, "Tempo [s]", "Errore [m]", "Prova")
    assert ax.get_xlabel() == "Tempo [s]"
    assert ax.get_ylabel() == "Errore [m]"
    assert ax.get_title() == "Prova"
    assert ax.spines["top"].get_visible() is False
    assert ax.spines["right"].get_visible() is False
    plt.close(fig)


def test_il_sottotitolo_di_sessione_diventa_un_annotazione():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import add_session_subtitle, style_axis
    plt, (fig, ax) = _axes()
    style_axis(ax, "x", "y", "Titolo")
    prima = len(ax.texts)
    add_session_subtitle(ax, "120 campioni  ·  48 s")
    assert len(ax.texts) == prima + 1
    assert "120 campioni" in ax.texts[-1].get_text()
    assert ax.get_title() == "Titolo"
    plt.close(fig)


def test_la_tacca_di_tolleranza_compare_su_entrambi_i_lati():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import add_tolerance_tick
    plt, (fig, ax) = _axes()
    ax.set_ylim(-1.0, 1.0)
    add_tolerance_tick(ax, 0.15)
    ticks = list(ax.get_yticks())
    assert 0.15 in ticks
    assert -0.15 in ticks
    plt.close(fig)


def test_la_tacca_di_tolleranza_scaccia_le_tacche_troppo_vicine():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import add_tolerance_tick
    plt, (fig, ax) = _axes()
    ax.set_ylim(-1.0, 1.0)
    ax.set_yticks([-1.0, -0.2, 0.0, 0.2, 1.0])
    add_tolerance_tick(ax, 0.2)
    ticks = list(ax.get_yticks())
    assert ticks.count(0.2) == 1
    assert 0.0 in ticks
    plt.close(fig)


def test_senza_cambi_di_waypoint_non_si_disegna_niente():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import add_wp_change_markers
    plt, (fig, ax) = _axes()
    offset = add_wp_change_markers([ax], [], [], 60.0, "#000000")
    assert offset == 7
    assert len(ax.lines) == 0
    plt.close(fig)


def test_una_riga_di_etichette_quando_i_waypoint_sono_lontani():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import add_wp_change_markers
    plt, (fig, ax) = _axes()
    offset = add_wp_change_markers([ax], [5.0, 40.0, 90.0], ["W1", "W2", "W3"], 100.0, "#000000")
    assert len(ax.lines) == 3
    assert [t.get_text() for t in ax.texts] == ["W1", "W2", "W3"]
    assert offset == 18
    plt.close(fig)


def test_le_etichette_ammassate_si_impilano_su_piu_righe():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import add_wp_change_markers
    plt, (fig, ax) = _axes()
    vicini = add_wp_change_markers(
        [ax], [10.0, 10.5, 11.0], ["W1", "W2", "W3"], 100.0, "#000000",
    )
    assert vicini > 18
    plt.close(fig)


def test_le_linee_dei_waypoint_finiscono_su_tutti_i_pannelli():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import add_wp_change_markers
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1)
    add_wp_change_markers(list(axes), [5.0, 40.0], ["W1", "W2"], 100.0, "#000000")
    for ax in axes:
        assert len(ax.lines) == 2
    assert len(axes[0].texts) == 2
    assert len(axes[1].texts) == 0
    plt.close(fig)


def test_la_legenda_ordinata_segue_le_priorita():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import ordered_legend
    plt, (fig, ax) = _axes()
    ax.plot([0, 1], [0, 1], label="Traiettoria")
    ax.plot([0, 1], [1, 0], label="Partenza")
    ordered_legend(ax, {"Partenza": 0, "Traiettoria": 1})
    etichette = [t.get_text() for t in ax.get_legend().get_texts()]
    assert etichette == ["Partenza", "Traiettoria"]
    plt.close(fig)


def test_la_legenda_ordinata_non_nasce_senza_serie():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import ordered_legend
    plt, (fig, ax) = _axes()
    ordered_legend(ax, {"Partenza": 0})
    assert ax.get_legend() is None
    plt.close(fig)


def test_il_salvataggio_scrive_il_file_e_lo_annota():
    if not _matplotlib_available():
        return
    from drone.ui.plots.axes import figure_saver
    plt, (fig, ax) = _axes()
    salvati: list[Path] = []
    with tempfile.TemporaryDirectory() as d:
        salva = figure_saver(Path(d), 72, salvati, plt)
        percorso = salva(fig, "prova.png")
        assert percorso.exists()
        assert percorso.name == "prova.png"
        assert salvati == [percorso]
        assert plt.fignum_exists(fig.number) is False


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
