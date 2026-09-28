from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.data.flight_report_stats import (
    duration_key,
    elapsed_seconds,
    entries_with_pose,
    filter_divergence,
    join_tag_ids,
    percent_within,
    rms,
    total_duration_sec,
    values_of,
    waypoint_groups,
)


def _campione(t, indice, distanza, raggiunto=False):
    return {
        "timestamp": t,
        "target_index": indice,
        "distance_3d": distanza,
        "reached": raggiunto,
    }


def test_gli_id_dei_tag_si_uniscono_col_separatore():
    assert join_tag_ids([1, 3, 7], "|") == "1|3|7"
    assert join_tag_ids([2], "|") == "2"


def test_senza_tag_la_colonna_resta_vuota():
    assert join_tag_ids([], "|") == ""
    assert join_tag_ids(None, "|") == ""


def test_i_valori_saltano_i_campioni_senza_quel_dato():
    campioni = [{"d": 1.0}, {"d": None}, {}, {"d": 3}]
    assert values_of(campioni, "d") == [1.0, 3.0]


def test_lo_scarto_quadratico_medio():
    assert rms([3.0, 4.0]) == math.sqrt(12.5)
    assert rms([2.0, -2.0]) == 2.0
    assert rms([]) is None


def test_la_percentuale_conta_solo_i_campioni_pertinenti():
    campioni = [{"d": 0.1}, {"d": 0.5}, {"d": None}, {"d": 0.2}]
    pct = percent_within(
        campioni,
        lambda e: e["d"] <= 0.2,
        lambda e: e.get("d") is not None,
    )
    assert pct is not None
    assert abs(pct - (200.0 / 3.0)) < 1e-9


def test_la_percentuale_e_ignota_se_nessun_campione_e_pertinente():
    campioni = [{"d": None}, {}]
    assert percent_within(campioni, lambda e: True, lambda e: e.get("d") is not None) is None


def test_le_soste_si_raggruppano_per_waypoint_consecutivo():
    campioni = [
        _campione(100.0, 0, 1.0),
        _campione(101.0, 0, 0.4, raggiunto=True),
        _campione(102.0, 1, 2.0),
        _campione(103.0, 1, 1.5),
    ]
    gruppi = waypoint_groups(campioni)
    assert [g["index"] for g in gruppi] == [0, 1]
    assert gruppi[0]["start"] == 0.0
    assert gruppi[0]["end"] == 1.0
    assert gruppi[0]["min_d3"] == 0.4
    assert gruppi[0]["reached"] is True
    assert gruppi[1]["reached"] is False


def test_tornare_su_un_waypoint_apre_un_secondo_gruppo():
    campioni = [
        _campione(100.0, 0, 1.0),
        _campione(101.0, 1, 1.0),
        _campione(102.0, 0, 0.2),
    ]
    gruppi = waypoint_groups(campioni)
    assert [g["index"] for g in gruppi] == [0, 1, 0]
    assert gruppi[2]["min_d3"] == 0.2


def test_un_waypoint_senza_indice_resta_un_gruppo_a_se():
    campioni = [_campione(100.0, None, None), _campione(101.0, 0, 1.0)]
    gruppi = waypoint_groups(campioni)
    assert gruppi[0]["index"] is None
    assert gruppi[0]["min_d3"] is None


def _confronto(raw, filtrata):
    return {
        "raw_x": raw, "filtered_x": filtrata,
        "raw_y": 0.0, "filtered_y": 0.0,
        "raw_z": 1.0, "filtered_z": 1.0,
    }


def test_il_filtro_che_resta_dentro_i_valori_grezzi_non_segnala_niente():
    campioni = [_confronto(0.0, 0.05), _confronto(1.0, 0.95)]
    assert filter_divergence(campioni, 0.10) == []


def test_il_filtro_che_sborda_oltre_il_margine_viene_segnalato():
    campioni = [_confronto(0.0, 0.0), _confronto(1.0, 1.4)]
    segnalati = filter_divergence(campioni, 0.10)
    assert len(segnalati) == 1
    d = segnalati[0]
    assert d["axis"] == "X"
    assert d["raw_max"] == 1.0
    assert d["filtered_max"] == 1.4
    assert abs(d["excess"] - 0.4) < 1e-9


def test_lo_sbordo_sotto_il_margine_non_scatta():
    campioni = [_confronto(0.0, 0.0), _confronto(1.0, 1.05)]
    assert filter_divergence(campioni, 0.10) == []


def test_si_guarda_anche_lo_sbordo_verso_il_basso():
    campioni = [_confronto(0.0, -0.5), _confronto(1.0, 1.0)]
    segnalati = filter_divergence(campioni, 0.10)
    assert len(segnalati) == 1
    assert abs(segnalati[0]["excess"] - 0.5) < 1e-9


def test_un_asse_senza_dati_non_si_puo_giudicare():
    campioni = [{"raw_x": None, "filtered_x": 5.0, "raw_y": 0.0, "filtered_y": 0.0}]
    assert filter_divergence(campioni, 0.10) == []



def _campione_a_orologi(timestamp, monotonic=None, **extra):
    e = {"timestamp": timestamp, "target_index": 0, "distance_3d": 1.0, "reached": False}
    if monotonic is not None:
        e["monotonic"] = monotonic
    e.update(extra)
    return e


def test_le_durate_usano_l_orologio_monotono_quando_c_e():
    campioni = [_campione_a_orologi(1000.0, 10.0), _campione_a_orologi(1001.0, 11.0)]
    assert duration_key(campioni) == "monotonic"


def test_senza_orologio_monotono_si_ripiega_sul_timestamp():
    campioni = [_campione_a_orologi(1000.0), _campione_a_orologi(1001.0)]
    assert duration_key(campioni) == "timestamp"
    assert elapsed_seconds(campioni) == [0.0, 1.0]


def test_se_manca_a_un_solo_campione_si_ripiega_su_tutti():
    campioni = [_campione_a_orologi(1000.0, 10.0), _campione_a_orologi(1001.0)]
    assert duration_key(campioni) == "timestamp"


def test_un_salto_dell_orologio_di_sistema_non_falsa_le_durate():
    campioni = [
        _campione_a_orologi(1000.0, 10.0),
        _campione_a_orologi(1001.0, 11.0),
        _campione_a_orologi(931.0, 12.0),
        _campione_a_orologi(932.0, 13.0),
    ]

    assert elapsed_seconds(campioni) == [0.0, 1.0, 2.0, 3.0]
    assert total_duration_sec(campioni) == 3.0


def test_i_tempi_partono_sempre_da_zero():
    campioni = [_campione_a_orologi(5000.0, 900.0), _campione_a_orologi(5002.0, 902.0)]
    assert elapsed_seconds(campioni)[0] == 0.0


def test_senza_campioni_non_c_e_durata():
    assert elapsed_seconds([]) == []
    assert total_duration_sec([]) == 0.0


def test_le_soste_per_waypoint_seguono_l_orologio_monotono():
    campioni = [
        _campione_a_orologi(1000.0, 10.0, target_index=0),
        _campione_a_orologi(500.0, 12.0, target_index=0),
        _campione_a_orologi(501.0, 13.0, target_index=1),
    ]

    gruppi = waypoint_groups(campioni)

    assert gruppi[0]["start"] == 0.0
    assert gruppi[0]["end"] == 2.0
    assert gruppi[1]["start"] == 3.0


def test_entries_with_pose_scarta_i_campioni_senza_posa():
    entries = [
        {"x": 1.0, "y": 0.0, "z": 1.5},
        {"x": None, "y": None, "z": None},
        {"y": 0.0},
        {"x": 2.0, "y": 0.0, "z": 1.5},
    ]

    tenuti = entries_with_pose(entries)

    assert [e["x"] for e in tenuti] == [1.0, 2.0]


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
