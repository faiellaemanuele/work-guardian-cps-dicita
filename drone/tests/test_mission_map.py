from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.ui.video.mission_map import (
    MissionMapState,
    _fit_transform,
    draw_mission_map,
)
from common_doubles import FakeClock, MapWaypoint as _WP


class _Tag:
    def __init__(self, x: float, y: float, z: float = 1.5):
        self.position_m = (float(x), float(y), float(z))


def _cmd(**overrides) -> dict:
    cmd = {
        "target_index": 0,
        "reached": False,
        "finished": False,
        "fault": False,
        "supervision_stop_active": False,
        "supervision_stop_remaining_sec": None,
        "reason": "tracking",
    }
    cmd.update(overrides)
    return cmd


def _state(waypoints, clock, **kwargs) -> MissionMapState:
    return MissionMapState(waypoints, time_source=clock, **kwargs)


def test_coincident_waypoints_share_one_circle_with_joined_label():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0), _WP(0, 0)], clock)
    assert len(state.circles) == 2
    assert state.circles[0].label == "1/3"
    assert state.circles[1].label == "2"


def test_home_waypoint_labeled_h():
    clock = FakeClock()
    state = _state([_WP(0, 2), _WP(1, 0), _WP(0, 0)], clock, home_index=2)
    assert state.circles[-1].label == "H"
    assert state.circles[-1].is_home is True


_SITE = ((-4.0, -4.0), (4.0, -4.0), (4.0, 4.0), (-4.0, 4.0))


def test_site_area_kept_in_order_as_floats():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0)], clock, site_area=[[-1, -1], [1, -1], [1, 1]])
    assert state.site_area == ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0))


def test_no_site_area_by_default():
    clock = FakeClock()
    assert _state([_WP(0, 0)], clock).site_area == ()


def test_site_area_with_two_vertices_is_ignored():
    clock = FakeClock()
    state = _state([_WP(0, 0)], clock, site_area=[[0, 0], [1, 1]])
    assert state.site_area == ()


def test_frame_includes_the_whole_site_area():
    clock = FakeClock()
    circles = _state([_WP(0, 0), _WP(0.5, 0.5)], clock).circles

    to_px, _scale, bounds = _fit_transform(
        circles, 400, 400, pad_px=10, extra_points=_SITE
    )
    min_x, max_x, min_y, max_y = bounds
    assert min_x <= -4.0 and max_x >= 4.0
    assert min_y <= -4.0 and max_y >= 4.0
    for x, y in _SITE:
        px, py = to_px(x, y)
        assert 0 <= px <= 400 and 0 <= py <= 400


def test_site_area_shrinks_the_route_on_screen():
    clock = FakeClock()
    circles = _state([_WP(0, 0), _WP(0.5, 0.5)], clock).circles

    to_px_alone, _s, _b = _fit_transform(circles, 400, 400, pad_px=10)
    to_px_site, _s, _b = _fit_transform(
        circles, 400, 400, pad_px=10, extra_points=_SITE
    )

    def _spread(to_px):
        a, b = to_px(0.0, 0.0), to_px(0.5, 0.5)
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    assert _spread(to_px_site) < _spread(to_px_alone)


def test_drawing_with_site_area_keeps_requested_size():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(0.5, 0.5)], clock, site_area=_SITE)
    img = draw_mission_map(state, 320, 240, drone_xy=(0.2, 0.2), drone_pose_fresh=True)
    assert img.size == (320, 240)


_RESTRICTED = ((2.0, 2.0), (3.0, 2.0), (3.0, 3.0), (2.0, 3.0))


def test_restricted_areas_kept_in_order_as_floats():
    clock = FakeClock()
    state = _state(
        [_WP(0, 0), _WP(1, 0)], clock,
        restricted_areas=[[[0, 0], [1, 0], [1, 1]]],
    )
    assert state.restricted_areas == (((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),)


def test_no_restricted_areas_by_default():
    clock = FakeClock()
    assert _state([_WP(0, 0)], clock).restricted_areas == ()


def test_restricted_area_with_two_vertices_is_ignored():
    clock = FakeClock()
    state = _state(
        [_WP(0, 0)], clock, restricted_areas=[[[0, 0], [1, 1]], _RESTRICTED],
    )
    assert state.restricted_areas == (_RESTRICTED,)


def test_frame_includes_the_whole_restricted_area():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(0.5, 0.5)], clock, restricted_areas=[_RESTRICTED])

    to_px, _scale, _bounds = _fit_transform(
        state.circles, 400, 400, pad_px=10,
        extra_points=tuple(v for area in state.restricted_areas for v in area),
    )
    for x, y in _RESTRICTED:
        px, py = to_px(x, y)
        assert 0 <= px <= 400 and 0 <= py <= 400


def _red_pixels(img) -> int:
    colori = img.convert("RGB").getcolors(img.width * img.height) or ()
    return sum(n for n, (r, g, b) in colori if r - g > 60 and r - b > 60)


def test_a_restricted_area_is_drawn_in_red():
    clock = FakeClock()
    senza = _state([_WP(0, 0), _WP(0.5, 0.5)], clock, site_area=_SITE)
    con = _state(
        [_WP(0, 0), _WP(0.5, 0.5)], clock, site_area=_SITE,
        restricted_areas=[_RESTRICTED],
    )
    assert _red_pixels(draw_mission_map(con, 320, 240)) > _red_pixels(
        draw_mission_map(senza, 320, 240)
    )


def test_tags_are_ordered_by_id():
    clock = FakeClock()
    state = _state([_WP(0, 0)], clock, world_tags={9: _Tag(1, 1), 2: _Tag(-1, -1)})
    assert [t.tag_id for t in state.tags] == [2, 9]


def test_tag_keeps_position_and_height():
    clock = FakeClock()
    state = _state([_WP(0, 0)], clock, world_tags={4: _Tag(1.91, 0.0, 1.65)})
    tag = state.tags[0]
    assert (tag.x, tag.y, tag.z) == (1.91, 0.0, 1.65)


def test_no_tags_by_default():
    clock = FakeClock()
    assert _state([_WP(0, 0)], clock).tags == ()


def test_frame_includes_the_tags():
    clock = FakeClock()
    state = _state(
        [_WP(0, 0), _WP(0.5, 0.5)], clock,
        world_tags={3: _Tag(0.0, -5.07), 16: _Tag(0.6, 2.96)},
    )
    to_px, _scale, _bounds = _fit_transform(
        state.circles, 400, 400, pad_px=10,
        extra_points=tuple((t.x, t.y) for t in state.tags),
    )
    for tag in state.tags:
        px, py = to_px(tag.x, tag.y)
        assert 0 <= px <= 400 and 0 <= py <= 400


def test_smaller_reserve_where_only_a_tag_is_at_the_edge():
    clock = FakeClock()
    circles = _state([_WP(0, 0), _WP(0, 1)], clock).circles
    extra = ((0.0, -3.0), (0.0, 3.0))

    _t, scala_piena, _b = _fit_transform(circles, 400, 400, pad_px=60, extra_points=extra)
    _t, scala_ridotta, _b = _fit_transform(
        circles, 400, 400, pad_px=60, extra_pad_px=20, extra_points=extra
    )
    assert scala_ridotta > scala_piena


def test_full_reserve_kept_where_a_circle_is_at_the_edge():
    clock = FakeClock()
    circles = _state([_WP(0, -3.0), _WP(0, 3.0)], clock).circles
    extra = ((0.0, 0.0),)

    _t, scala_piena, _b = _fit_transform(circles, 400, 400, pad_px=60, extra_points=extra)
    _t, scala_ridotta, _b = _fit_transform(
        circles, 400, 400, pad_px=60, extra_pad_px=20, extra_points=extra
    )
    assert scala_ridotta == scala_piena


def test_drawing_with_tags_keeps_requested_size():
    clock = FakeClock()
    state = _state(
        [_WP(0, 0), _WP(0.5, 0.5)], clock, site_area=_SITE,
        world_tags={0: _Tag(0, 0, 0.0), 3: _Tag(0.0, -5.07), 16: _Tag(0.6, 2.96)},
    )
    img = draw_mission_map(state, 320, 240)
    assert img.size == (320, 240)


def test_a_seen_tag_stays_lit_for_the_latch_then_goes_off():
    clock = FakeClock()
    state = _state([_WP(0, 0)], clock, world_tags={3: _Tag(0, -5.07), 16: _Tag(0.6, 2.96)})

    state.set_visible_tags({3})
    assert state.visible_tag_ids() == {3}

    clock.advance(0.5)
    assert state.visible_tag_ids() == {3}

    clock.advance(0.5)
    assert state.visible_tag_ids() == set()


def test_seeing_a_tag_again_restarts_the_latch():
    clock = FakeClock()
    state = _state([_WP(0, 0)], clock, world_tags={3: _Tag(0, -5.07)})

    state.set_visible_tags({3})
    clock.advance(0.6)
    state.set_visible_tags({3})
    clock.advance(0.6)
    assert state.visible_tag_ids() == {3}


def test_no_visible_tag_by_default_and_empty_update_is_ignored():
    clock = FakeClock()
    state = _state([_WP(0, 0)], clock, world_tags={3: _Tag(0, -5.07)})
    assert state.visible_tag_ids() == set()
    state.set_visible_tags(set())
    assert state.visible_tag_ids() == set()


def test_a_lit_tag_changes_the_drawing():
    clock = FakeClock()
    state = _state(
        [_WP(0, 0), _WP(0.5, 0.5)], clock,
        world_tags={3: _Tag(0.0, -5.07), 16: _Tag(0.6, 2.96)},
    )
    spento = draw_mission_map(state, 320, 240).tobytes()
    state.set_visible_tags({3})
    acceso = draw_mission_map(state, 320, 240).tobytes()
    assert acceso != spento


def test_reached_marks_circle_green_permanently():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0)], clock)
    assert state.circle_fill_states() == ["idle", "idle"]

    state.update_command(_cmd(target_index=0, reached=True, reason="waypoint_reached"))
    assert state.circle_fill_states() == ["reached", "idle"]

    state.update_command(_cmd(target_index=1))
    clock.advance(5.0)
    assert state.circle_fill_states() == ["reached", "idle"]


def test_supervision_stop_colors_circle_orange_with_countdown_badge():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0)], clock)

    state.update_command(_cmd(
        target_index=1, supervision_stop_active=True,
        supervision_stop_remaining_sec=12.4, reason="supervision_stop",
    ))
    assert state.circle_fill_states() == ["idle", "supervising"]
    badge = state.badge()
    assert badge is not None
    assert badge.kind == "supervision"
    assert "12.4" in badge.text


def test_supervision_completed_turns_circle_green_and_clears_badge():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0)], clock)
    state.update_command(_cmd(
        target_index=1, supervision_stop_active=True,
        supervision_stop_remaining_sec=1.0, reason="supervision_stop",
    ))
    state.update_command(_cmd(
        target_index=1, reached=True, reason="supervision_stop_completed",
    ))
    assert state.circle_fill_states() == ["idle", "reached"]
    assert state.badge() is None


def test_intermediate_visit_lights_then_deactivates_final_stays_green():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0), _WP(0, 0)], clock)

    state.update_command(_cmd(target_index=0, reached=True))
    assert state.circle_fill_states()[0] == "reached"

    clock.advance(2.0)
    assert state.circle_fill_states()[0] == "idle"

    state.update_command(_cmd(target_index=2, reached=True))
    assert state.circle_fill_states()[0] == "reached"
    clock.advance(5.0)
    assert state.circle_fill_states()[0] == "reached"


def test_intermediate_visit_reactivates_on_next_visit():
    clock = FakeClock()
    state = _state(
        [_WP(0, 0), _WP(1, 0), _WP(0, 0), _WP(1, 0), _WP(0, 0)], clock
    )

    state.update_command(_cmd(target_index=0, reached=True))
    assert state.circle_fill_states()[0] == "reached"
    clock.advance(2.0)
    assert state.circle_fill_states()[0] == "idle"

    state.update_command(_cmd(target_index=2, reached=True))
    assert state.circle_fill_states()[0] == "reached"
    clock.advance(2.0)
    assert state.circle_fill_states()[0] == "idle"

    state.update_command(_cmd(target_index=4, reached=True))
    clock.advance(5.0)
    assert state.circle_fill_states()[0] == "reached"


def test_supervision_on_revisited_circle_deactivates_like_reached():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0), _WP(0, 0)], clock)

    state.update_command(_cmd(
        target_index=0, supervision_stop_active=True,
        supervision_stop_remaining_sec=3.0, reason="supervision_stop",
    ))
    assert state.circle_fill_states()[0] == "supervising"

    state.update_command(_cmd(
        target_index=0, reached=True, reason="supervision_stop_completed",
    ))
    assert state.circle_fill_states()[0] == "reached"
    clock.advance(2.0)
    assert state.circle_fill_states()[0] == "idle"

    state.update_command(_cmd(
        target_index=2, supervision_stop_active=True,
        supervision_stop_remaining_sec=3.0, reason="supervision_stop",
    ))
    assert state.circle_fill_states()[0] == "supervising"
    state.update_command(_cmd(
        target_index=2, reached=True, reason="supervision_stop_completed",
    ))
    clock.advance(5.0)
    assert state.circle_fill_states()[0] == "reached"


def test_autonomy_inactive_clears_supervision_but_keeps_green():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0)], clock)
    state.update_command(_cmd(target_index=0, reached=True))
    state.update_command(_cmd(
        target_index=1, supervision_stop_active=True,
        supervision_stop_remaining_sec=5.0, reason="supervision_stop",
    ))

    state.set_autonomy_inactive()
    assert state.circle_fill_states() == ["reached", "idle"]
    assert state.badge() is None


def test_finished_shows_badge_and_restart_resets_map():
    clock = FakeClock()
    state = _state([_WP(0, 0), _WP(1, 0)], clock)
    state.update_command(_cmd(target_index=0, reached=True))
    state.update_command(_cmd(
        target_index=1, reached=True, finished=True, reason="waypoint_reached",
    ))
    badge = state.badge()
    assert badge is not None and badge.kind == "finished"

    state.update_command(_cmd(target_index=0, reason="tracking"))
    assert state.circle_fill_states() == ["idle", "idle"]
    assert state.badge() is None


def test_empty_or_out_of_range_commands_are_ignored():
    clock = FakeClock()
    state = _state([_WP(0, 0)], clock)
    state.update_command({})
    state.update_command(_cmd(target_index=99, reached=True))
    state.update_command(_cmd(target_index=None))
    assert state.circle_fill_states() == ["idle"]


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
