from __future__ import annotations

import dataclasses
import logging
import sys

import cv2
import numpy as np
import pygame

from drone.config import APP_CONFIG

LOGGER = logging.getLogger(__name__)

_RECT_TYPE = None


def _rect_type():
    global _RECT_TYPE
    if _RECT_TYPE is None:
        import ctypes
        from ctypes import wintypes

        class _RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        _RECT_TYPE = _RECT
    return _RECT_TYPE


def enable_high_dpi_awareness() -> bool:
    if sys.platform != "win32":
        return False

    import ctypes

    try:
        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ):
            return True
    except (AttributeError, OSError):
        pass

    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except (AttributeError, OSError):
        pass

    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return True
    except (AttributeError, OSError):
        pass

    LOGGER.info("Impossibile impostare la DPI awareness: la finestra potrebbe risultare sfocata su schermi HiDPI.")
    return False


def monitor_work_origin_for_window(hwnd) -> "tuple[int, int] | None":
    if sys.platform != "win32" or not hwnd:
        return None

    import ctypes
    from ctypes import wintypes

    rect_type = _rect_type()

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", rect_type),
            ("rcWork", rect_type),
            ("dwFlags", wintypes.DWORD),
        ]

    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL

        _MONITOR_DEFAULTTONEAREST = 2
        hmon = user32.MonitorFromWindow(wintypes.HWND(int(hwnd)), _MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return None
        return (int(info.rcWork.left), int(info.rcWork.top))
    except (AttributeError, OSError, ValueError):
        return None


def _pygame_window_handle():
    try:
        return pygame.display.get_wm_info().get("window")
    except Exception:
        return None


def _maximize_cv_window(title: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            _SW_MAXIMIZE = 3
            user32.ShowWindow(hwnd, _SW_MAXIMIZE)
    except Exception:
        LOGGER.debug("Impossibile massimizzare la finestra '%s'.", title, exc_info=True)


def _client_size(title: str) -> "tuple[int, int] | None":
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return None
        rect = _rect_type()()
        if not user32.GetClientRect(wintypes.HWND(int(hwnd)), ctypes.byref(rect)):
            return None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None
        return (int(width), int(height))
    except (AttributeError, OSError, ValueError):
        return None


def _fit_dashboard_to_window(dashboard, title: str) -> None:
    size = _client_size(title)
    if size is None:
        return
    client_w, client_h = size

    config = dashboard.config
    panel_w = int(getattr(config, "panel_width", 920))
    video_w = max(client_w // 3, client_w - panel_w)
    video_h = client_h
    if (video_w, video_h) == tuple(getattr(config, "video_size", ())):
        return

    dashboard.config = dataclasses.replace(config, video_size=(video_w, video_h))
    LOGGER.debug(
        "Cruscotto adattato alla finestra: video %dx%d + pannelli %d = %dx%d.",
        video_w, video_h, panel_w, video_w + panel_w, client_h,
    )


def setup_video_window(dashboard) -> None:
    title = APP_CONFIG.video_window_title

    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    if dashboard.enabled:
        cfg_dash = APP_CONFIG.dashboard
        win_w = cfg_dash.video_size[0] + cfg_dash.panel_width
        win_h = cfg_dash.video_size[1]
        win_origin = cfg_dash.video_origin
    else:
        win_w, win_h = APP_CONFIG.dashboard.video_size
        win_origin = (0, 0)

    monitor_origin = monitor_work_origin_for_window(_pygame_window_handle())
    if monitor_origin is not None:
        win_origin = monitor_origin

    try:
        cv2.resizeWindow(title, win_w, win_h)
        cv2.imshow(title, np.zeros((win_h, win_w, 3), dtype=np.uint8))
        cv2.waitKey(1)
        cv2.moveWindow(title, *win_origin)
        cv2.waitKey(1)
    except cv2.error:
        pass
    _maximize_cv_window(title)

    if dashboard.enabled:
        try:
            cv2.waitKey(1)
        except cv2.error:
            pass
        _fit_dashboard_to_window(dashboard, title)
