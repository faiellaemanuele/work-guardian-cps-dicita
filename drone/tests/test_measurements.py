from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config.measurements import (
    CAMERA_MATRIX,
    DIST_COEFFS,
    RESTRICTED_AREAS_RAW,
    SITE_AREA_VERTICES_M,
    WORLD_TAGS_RAW,
)


def _all_finite_floats(values) -> bool:
    return all(isinstance(v, float) and math.isfinite(v) for v in values)


def test_world_tags_map_is_not_empty():
    assert WORLD_TAGS_RAW


def test_tag_ids_are_non_negative_integers():
    for tag_id in WORLD_TAGS_RAW:
        assert isinstance(tag_id, int) and not isinstance(tag_id, bool), tag_id
        assert tag_id >= 0, tag_id


def test_every_tag_has_position_and_orientation():
    for tag_id, spec in WORLD_TAGS_RAW.items():
        assert set(spec) == {"position_m", "orientation_rpy_deg"}, tag_id


def test_every_tag_pose_has_three_components():
    for tag_id, spec in WORLD_TAGS_RAW.items():
        assert len(spec["position_m"]) == 3, tag_id
        assert len(spec["orientation_rpy_deg"]) == 3, tag_id


def test_every_tag_coordinate_is_a_finite_float():
    for tag_id, spec in WORLD_TAGS_RAW.items():
        assert _all_finite_floats(spec["position_m"]), tag_id
        assert _all_finite_floats(spec["orientation_rpy_deg"]), tag_id


def test_site_area_is_a_polygon_of_at_least_three_vertices():
    assert len(SITE_AREA_VERTICES_M) >= 3


def test_every_vertex_has_two_finite_coordinates():
    for vertex in SITE_AREA_VERTICES_M:
        assert len(vertex) == 2, vertex
        assert _all_finite_floats(vertex), vertex


def test_first_vertex_is_not_repeated_at_the_end():
    assert SITE_AREA_VERTICES_M[0] != SITE_AREA_VERTICES_M[-1]


def test_every_restricted_area_has_a_centre_and_a_size():
    for index, area in enumerate(RESTRICTED_AREAS_RAW):
        assert set(area) == {"center_m", "size_m"}, index


def test_every_restricted_area_is_a_rectangle_of_finite_measures():
    for index, area in enumerate(RESTRICTED_AREAS_RAW):
        assert len(area["center_m"]) == 2, index
        assert len(area["size_m"]) == 2, index
        assert _all_finite_floats(area["center_m"]), index
        assert _all_finite_floats(area["size_m"]), index


def test_every_restricted_area_has_positive_sides():
    for index, area in enumerate(RESTRICTED_AREAS_RAW):
        assert all(side > 0.0 for side in area["size_m"]), index


def test_camera_matrix_is_three_by_three():
    assert len(CAMERA_MATRIX) == 3
    for row in CAMERA_MATRIX:
        assert len(row) == 3, row
        assert _all_finite_floats(row), row


def test_dist_coeffs_has_five_finite_values():
    assert len(DIST_COEFFS) == 5
    assert _all_finite_floats(DIST_COEFFS)


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
