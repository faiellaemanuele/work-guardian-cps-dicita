from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from PIL import Image, ImageDraw

from drone.ui import fonts

_MAP_BG = (255, 255, 255)
_GRID = (236, 236, 236)
_AXES = (198, 198, 198)
_ROUTE = (154, 154, 154)
_CIRCLE_BORDER = (0, 0, 0)

_SITE_BORDER = (150, 159, 168)
_SITE_FILL = (246, 248, 250)

_TAG_FLOOR = (23, 190, 207)
_TAG_HIGH = (31, 119, 180)
_TAG_FLOOR_FILL = (209, 243, 246)
_TAG_HIGH_FILL = (212, 229, 240)

_TAG_HIGH_Z_M = 0.75

_TAG_SIDE_RATIO = 1.1

_FILL_IDLE = (255, 255, 255)
_FILL_REACHED = (0, 137, 123)
_FILL_SUPERVISING = (208, 124, 12)

_LABEL_ON_IDLE = (0, 0, 0)
_LABEL_ON_FILL = (255, 255, 255)

_DRONE_FRESH = (55, 138, 221)
_DRONE_STALE = (150, 150, 150)

LEGEND_COLORS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("raggiunto", _FILL_REACHED),
    ("supervisione", _FILL_SUPERVISING),
)

_VISIT_HIGHLIGHT_SEC = 1.5

_GRID_STEP_M = 0.5

_CIRCLE_RADIUS_MAX = 30
_CIRCLE_SPACING_RATIO = 0.44

_DRONE_MIN_SCALE = 0.35

_DRONE_ENLARGE = 1.3

_ARROW_START = 48.0
_ARROW_LENGTH = 86.0
_ARROW_GROWTH = 18.0
_RING_RADIUS = 40.0


@dataclass
class MapCircle:
    x: float
    y: float
    label: str
    indices: tuple[int, ...]
    is_home: bool = False
    reached: bool = False
    highlight_until: float = 0.0


@dataclass
class MapTag:
    tag_id: int
    x: float
    y: float
    z: float


@dataclass
class MapBadge:
    text: str
    kind: str


class MissionMapState:
    def __init__(
        self,
        waypoints: Sequence[Any],
        home_index: Optional[int] = None,
        site_area: Sequence[Sequence[float]] = (),
        world_tags: Optional[Mapping[int, Any]] = None,
        time_source: Optional[Callable[[], float]] = None,
    ):
        self._now = time_source if time_source is not None else time.monotonic
        self.home_index = None if home_index is None else int(home_index)
        self.waypoint_count = len(waypoints)
        vertices = tuple((float(v[0]), float(v[1])) for v in site_area)
        self.site_area: tuple[tuple[float, float], ...] = (
            vertices if len(vertices) >= 3 else ()
        )

        self.tags: tuple[MapTag, ...] = ()
        if world_tags:
            tags = []
            for tag_id in sorted(world_tags):
                x, y, z = world_tags[tag_id].position_m
                tags.append(MapTag(int(tag_id), float(x), float(y), float(z)))
            self.tags = tuple(tags)

        grouped: dict[tuple[float, float], list[int]] = {}
        order: list[tuple[float, float]] = []
        for index, wp in enumerate(waypoints):
            key = (round(float(wp.x), 3), round(float(wp.y), 3))
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(index)

        self.circles: list[MapCircle] = []
        self._circle_of: dict[int, int] = {}
        for key in order:
            indices = tuple(grouped[key])
            is_home = self.home_index in indices
            parts = [
                "H" if index == self.home_index else str(index + 1)
                for index in indices
            ]
            circle = MapCircle(
                x=key[0], y=key[1],
                label="/".join(parts),
                indices=indices,
                is_home=is_home,
            )
            for index in indices:
                self._circle_of[index] = len(self.circles)
            self.circles.append(circle)

        self._supervising_circle: Optional[int] = None
        self._supervision_remaining: Optional[float] = None
        self._finished = False

    def update_command(self, command: Mapping[str, Any]) -> None:
        if not command:
            return
        now = self._now()

        finished = bool(command.get("finished", False))
        if self._finished and not finished:
            self.reset()
        self._finished = finished

        target_index = command.get("target_index")
        circle_index = (
            self._circle_of.get(int(target_index)) if target_index is not None else None
        )

        if bool(command.get("supervision_stop_active", False)) and circle_index is not None:
            self._supervising_circle = circle_index
            remaining = command.get("supervision_stop_remaining_sec")
            self._supervision_remaining = None if remaining is None else float(remaining)
        else:
            self._supervising_circle = None
            self._supervision_remaining = None

        if bool(command.get("reached", False)) and circle_index is not None:
            circle = self.circles[circle_index]
            if int(target_index) == max(circle.indices):
                circle.reached = True
                circle.highlight_until = 0.0
            else:
                circle.highlight_until = now + _VISIT_HIGHLIGHT_SEC

    def set_autonomy_inactive(self) -> None:
        self._supervising_circle = None
        self._supervision_remaining = None

    def reset(self) -> None:
        for circle in self.circles:
            circle.reached = False
            circle.highlight_until = 0.0
        self._supervising_circle = None
        self._supervision_remaining = None
        self._finished = False

    def circle_fill_states(self, now: Optional[float] = None) -> list[str]:
        if now is None:
            now = self._now()
        states: list[str] = []
        for index, circle in enumerate(self.circles):
            if index == self._supervising_circle:
                states.append("supervising")
                continue
            if circle.reached:
                states.append("reached")
                continue
            if now < circle.highlight_until:
                states.append("reached")
                continue
            states.append("idle")
        return states

    def supervision_remaining_sec(self) -> Optional[float]:
        if self._supervising_circle is None:
            return None
        return self._supervision_remaining

    def badge(self) -> Optional[MapBadge]:
        if self._supervising_circle is not None:
            remaining = self._supervision_remaining
            testo = (
                "Supervisione"
                if remaining is None
                else f"Supervisione · {remaining:.1f} s"
            )
            return MapBadge(text=testo, kind="supervision")
        if self._finished:
            return MapBadge(text="Missione completata", kind="finished")
        return None


_SUPERSAMPLE = 2


def _ss(value: float) -> int:
    return int(round(value * _SUPERSAMPLE))


def _fit_transform(circles, width, height, pad_px, reserved_right=0, reserved_left=0,
                   extra_points=(), extra_pad_px=None):
    circle_xs = [c.x for c in circles]
    circle_ys = [c.y for c in circles]
    xs = circle_xs + [float(p[0]) for p in extra_points]
    ys = circle_ys + [float(p[1]) for p in extra_points]
    margin_m = 0.1
    min_x, max_x = min(xs) - margin_m, max(xs) + margin_m
    min_y, max_y = min(ys) - margin_m, max(ys) + margin_m
    span_x = max(max_x - min_x, 0.5)
    span_y = max(max_y - min_y, 0.5)

    if extra_pad_px is None:
        extra_pad_px = pad_px

    def side_pad(values, circle_values, edge):
        if circle_values and edge(circle_values) == edge(values):
            return pad_px
        return extra_pad_px

    pad_left = side_pad(xs, circle_xs, min)
    pad_right = side_pad(xs, circle_xs, max)
    pad_top = side_pad(ys, circle_ys, max)
    pad_bottom = side_pad(ys, circle_ys, min)

    avail_w = max(
        1, width - pad_left - pad_right - max(0, reserved_left) - max(0, reserved_right)
    )
    avail_h = max(1, height - pad_top - pad_bottom)
    scale = min(avail_w / span_x, avail_h / span_y)

    off_x = pad_left + max(0, reserved_left) + (avail_w - span_x * scale) / 2.0
    off_y = pad_top + (avail_h - span_y * scale) / 2.0

    def to_px(x_m: float, y_m: float) -> tuple[float, float]:
        return (
            off_x + (x_m - min_x) * scale,
            off_y + (max_y - y_m) * scale,
        )

    return to_px, scale, (min_x, max_x, min_y, max_y)


_TAG_LABEL_MIN_HALF = _ss(10)


def _fill_site_area(draw, vertices, to_px) -> None:
    if not vertices:
        return
    draw.polygon([to_px(x, y) for x, y in vertices], fill=_SITE_FILL)


def _draw_site_border(draw, vertices, to_px) -> None:
    if not vertices:
        return
    points = [to_px(x, y) for x, y in vertices]
    draw.line(points + [points[0]], fill=_SITE_BORDER, width=_ss(2), joint="curve")


def _draw_grid(draw, to_px, bounds, width, height):
    min_x, max_x, min_y, max_y = bounds

    gx = math.floor(min_x / _GRID_STEP_M) * _GRID_STEP_M
    while gx <= max_x:
        px, _ = to_px(gx, min_y)
        draw.line((px, 0, px, height), fill=_GRID, width=_ss(1))
        gx += _GRID_STEP_M
    gy = math.floor(min_y / _GRID_STEP_M) * _GRID_STEP_M
    while gy <= max_y:
        _, py = to_px(min_x, gy)
        draw.line((0, py, width, py), fill=_GRID, width=_ss(1))
        gy += _GRID_STEP_M

    if min_x <= 0.0 <= max_x:
        px, _ = to_px(0.0, min_y)
        draw.line((px, 0, px, height), fill=_AXES, width=_ss(1))
    if min_y <= 0.0 <= max_y:
        _, py = to_px(min_x, 0.0)
        draw.line((0, py, width, py), fill=_AXES, width=_ss(1))


def _draw_route(draw, state: MissionMapState, to_px) -> None:
    seen: set[tuple[int, int]] = set()
    for index in range(state.waypoint_count - 1):
        a = state._circle_of.get(index)
        b = state._circle_of.get(index + 1)
        if a is None or b is None or a == b:
            continue
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        ca, cb = state.circles[a], state.circles[b]
        draw.line((*to_px(ca.x, ca.y), *to_px(cb.x, cb.y)), fill=_ROUTE, width=_ss(2))


def _draw_tags(draw, tags, to_px, radius: int) -> None:
    if not tags:
        return
    half = radius * _TAG_SIDE_RATIO / 2.0
    points = [to_px(t.x, t.y) for t in tags]
    if len(points) > 1:
        closest = min(
            math.dist(a, b)
            for index, a in enumerate(points)
            for b in points[index + 1:]
        )
        half = min(half, closest * _CIRCLE_SPACING_RATIO)
    half = int(max(_ss(4), half))

    font = fonts.sans(int(half * 0.95)) if half >= _TAG_LABEL_MIN_HALF else None
    for tag, (cx, cy) in zip(tags, points):
        high = tag.z >= _TAG_HIGH_Z_M
        color = _TAG_HIGH if high else _TAG_FLOOR
        draw.rectangle(
            (cx - half, cy - half, cx + half, cy + half),
            fill=_TAG_HIGH_FILL if high else _TAG_FLOOR_FILL,
            outline=color, width=max(1, _ss(1.5)),
        )
        if font is not None:
            draw.text((cx, cy), str(tag.tag_id), font=font, fill=color, anchor="mm")


def _circle_radius(circles, to_px) -> int:
    limit = float(_ss(_CIRCLE_RADIUS_MAX))
    points = [to_px(c.x, c.y) for c in circles]
    if len(points) > 1:
        closest = min(
            math.dist(a, b)
            for index, a in enumerate(points)
            for b in points[index + 1:]
        )
        limit = min(limit, closest * _CIRCLE_SPACING_RATIO)
    return int(max(_ss(9), limit))


def _draw_circles(draw, state: MissionMapState, fills: list[str], to_px, radius: int) -> None:
    fill_colors = {
        "idle": _FILL_IDLE,
        "reached": _FILL_REACHED,
        "supervising": _FILL_SUPERVISING,
    }
    for circle, state_name in zip(state.circles, fills):
        cx, cy = to_px(circle.x, circle.y)
        fill = fill_colors.get(state_name, _FILL_IDLE)
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=fill, outline=_CIRCLE_BORDER, width=_ss(2),
        )
        ratio = 0.72 if len(circle.label) <= 2 else 0.50
        font = fonts.sans(max(_ss(7), int(radius * ratio)))
        color = _LABEL_ON_IDLE if state_name == "idle" else _LABEL_ON_FILL
        draw.text((cx, cy), circle.label, font=font, fill=color, anchor="mm")


def _arrow(draw, x0, y0, x1, y1, color, width, head) -> None:
    draw.line((x0, y0, x1, y1), fill=color, width=width)
    angle = math.atan2(y1 - y0, x1 - x0)
    for side in (+1, -1):
        a = angle + side * math.radians(150)
        draw.line(
            (x1, y1, x1 + math.cos(a) * head, y1 + math.sin(a) * head),
            fill=color, width=width,
        )


def _draw_rotation_ring(draw, cx, cy, radius, clockwise, color, width, head) -> None:
    start, end = (35, 305) if clockwise else (-125, 145)
    draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
             start, end, fill=color, width=width)
    angle = math.radians(end if clockwise else start)
    px, py = cx + math.cos(angle) * radius, cy + math.sin(angle) * radius
    tangent = angle + (math.pi / 2 if clockwise else -math.pi / 2)
    for side in (+1, -1):
        a = tangent + side * math.radians(150)
        draw.line(
            (px, py, px + math.cos(a) * head, py + math.sin(a) * head),
            fill=color, width=width,
        )


def _draw_movement(draw, cx, cy, heading_deg, command, color, scale) -> None:
    if not command:
        return
    fb = float(command.get("fb", 0) or 0)
    lr = float(command.get("lr", 0) or 0)
    yaw = float(command.get("yaw", 0) or 0)

    width = max(2, _ss(3.2 * scale))
    head = _ss(11 * scale)
    heading = math.radians(heading_deg)

    dx = fb * math.cos(heading) + lr * math.cos(heading - math.pi / 2)
    dy = fb * math.sin(heading) + lr * math.sin(heading - math.pi / 2)
    magnitude = math.hypot(dx, dy)
    if magnitude > 0:
        start = _ss(_ARROW_START * scale)
        end = _ss((_ARROW_LENGTH + _ARROW_GROWTH * min(1.0, magnitude / 40.0)) * scale)
        ux, uy = dx / magnitude, dy / magnitude
        _arrow(draw, cx + ux * start, cy - uy * start,
               cx + ux * end, cy - uy * end, color, width, head)
    if yaw:
        _draw_rotation_ring(
            draw, cx, cy, _ss(_RING_RADIUS * scale), yaw > 0, color,
            max(2, _ss(2.0 * scale)), _ss(7 * scale),
        )


def _draw_drone_marker(draw, x_px, y_px, heading_deg, fresh, width, height,
                       scale=1.0, command=None) -> None:
    color = _DRONE_FRESH if fresh else _DRONE_STALE
    margin = _ss(16)
    cx = max(margin, min(width - margin, x_px))
    cy = max(margin, min(height - margin, y_px))
    scale = scale * _DRONE_ENLARGE

    def _w(px_logico):
        return max(1, _ss(px_logico * scale))

    heading_rad = math.radians(heading_deg)
    hx = cx + math.cos(heading_rad) * _ss(36 * scale)
    hy = cy - math.sin(heading_rad) * _ss(36 * scale)
    draw.line((cx, cy, hx, hy), fill=color, width=_w(3.5))

    ax, ay = 15.0 * _SUPERSAMPLE * scale, 12.5 * _SUPERSAMPLE * scale
    draw.line((cx - ax, cy - ay, cx + ax, cy + ay), fill=color, width=_w(3))
    draw.line((cx + ax, cy - ay, cx - ax, cy + ay), fill=color, width=_w(3))
    rotor_r = 7.5 * _SUPERSAMPLE * scale
    for dx, dy in ((-ax, -ay), (ax, -ay), (-ax, ay), (ax, ay)):
        draw.ellipse(
            (cx + dx - rotor_r, cy + dy - rotor_r, cx + dx + rotor_r, cy + dy + rotor_r),
            fill=_MAP_BG, outline=color, width=_w(3),
        )
    dot_r = 4.6 * _SUPERSAMPLE * scale
    draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r), fill=color)

    _draw_movement(draw, cx, cy, heading_deg, command, color, scale)


def draw_mission_map(
    state: MissionMapState,
    width: int,
    height: int,
    *,
    drone_xy: Optional[tuple[float, float]] = None,
    drone_heading_deg: float = 0.0,
    drone_pose_fresh: bool = False,
    drone_command: Optional[Mapping[str, Any]] = None,
    reserved_right_px: int = 0,
    reserved_left_px: int = 0,
    now: Optional[float] = None,
) -> "Image.Image":
    width, height = max(60, int(width)), max(60, int(height))
    if not state.circles:
        return Image.new("RGB", (width, height), _MAP_BG)

    W, H = width * _SUPERSAMPLE, height * _SUPERSAMPLE
    img = Image.new("RGB", (W, H), _MAP_BG)
    draw = ImageDraw.Draw(img)

    base_pad = _ss(6)
    fit_kwargs = dict(
        reserved_right=_ss(reserved_right_px), reserved_left=_ss(reserved_left_px),
        extra_points=tuple(state.site_area) + tuple((t.x, t.y) for t in state.tags),
    )

    def _fit(radius):
        return _fit_transform(
            state.circles, W, H,
            pad_px=base_pad + radius,
            extra_pad_px=base_pad + int(radius * _TAG_SIDE_RATIO / 2.0),
            **fit_kwargs,
        )

    to_px, _scale, bounds = _fit(_ss(_CIRCLE_RADIUS_MAX))
    radius = _circle_radius(state.circles, to_px)
    to_px, _scale, bounds = _fit(radius)
    radius = _circle_radius(state.circles, to_px)

    _fill_site_area(draw, state.site_area, to_px)
    _draw_grid(draw, to_px, bounds, W, H)
    _draw_site_border(draw, state.site_area, to_px)
    _draw_tags(draw, state.tags, to_px, radius=radius)
    _draw_route(draw, state, to_px)
    _draw_circles(draw, state, state.circle_fill_states(now), to_px, radius=radius)

    if drone_xy is not None:
        x_px, y_px = to_px(float(drone_xy[0]), float(drone_xy[1]))
        drone_scale = max(_DRONE_MIN_SCALE, radius / float(_ss(_CIRCLE_RADIUS_MAX)))
        _draw_drone_marker(
            draw, x_px, y_px, drone_heading_deg, drone_pose_fresh, W, H,
            scale=drone_scale, command=drone_command,
        )

    return img.resize((width, height), Image.LANCZOS)
