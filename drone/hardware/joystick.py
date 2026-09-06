import logging

import os

import pygame

from drone.config import APP_CONFIG

LOGGER = logging.getLogger(__name__)

_JOYSTICK = None


def _enable_background_joystick_events():
    os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")


def _disconnect_current_joystick():
    global _JOYSTICK

    if _JOYSTICK is None:
        return

    try:
        _JOYSTICK.quit()
    except Exception:
        LOGGER.exception("Errore durante la chiusura del joystick.")
    finally:
        _JOYSTICK = None


def _get_joystick_instance_id(joystick):
    if joystick is None:
        return None

    try:
        return joystick.get_instance_id()
    except (AttributeError, OSError, pygame.error):
        return None


def _get_joystick_legacy_id(joystick):
    if joystick is None:
        return None

    try:
        return joystick.get_id()
    except (AttributeError, OSError, pygame.error):
        return None


def _connect_first_joystick(device_index=0):
    global _JOYSTICK

    joystick_count = pygame.joystick.get_count()
    if joystick_count < 1:
        raise RuntimeError(
            "Nessun joystick rilevato. Collega il controller PS4 prima di avviare il programma."
        )

    if not 0 <= device_index < joystick_count:
        device_index = 0

    _disconnect_current_joystick()

    joystick = pygame.joystick.Joystick(device_index)
    joystick.init()
    _JOYSTICK = joystick

    LOGGER.info("Joystick collegato: %s", _JOYSTICK.get_name())
    LOGGER.info(
        "Assi: %s | Pulsanti: %s | instance_id=%s | legacy_id=%s",
        _JOYSTICK.get_numaxes(),
        _JOYSTICK.get_numbuttons(),
        _get_joystick_instance_id(_JOYSTICK),
        _get_joystick_legacy_id(_JOYSTICK),
    )


def init_joystick():
    _enable_background_joystick_events()
    pygame.init()
    pygame.joystick.init()

    _initial_window_size = (960, 720)
    screen = pygame.display.set_mode(_initial_window_size, pygame.RESIZABLE)
    pygame.display.set_caption(APP_CONFIG.window_title)

    if pygame.joystick.get_count() > 0:
        _connect_first_joystick()

    return screen


def is_joystick_connected() -> bool:
    return _JOYSTICK is not None


def close_joystick():
    _disconnect_current_joystick()

    try:
        if pygame.joystick.get_init():
            pygame.joystick.quit()
    except pygame.error:
        pass


def _get_event_controller_ids(event):
    ids = []
    for attr_name in ("instance_id", "joy", "which"):
        attr_value = getattr(event, attr_name, None)
        if attr_value is None:
            continue
        if attr_value not in ids:
            ids.append(attr_value)
    return tuple(ids)


def _event_matches_active_joystick(event, active_instance_id, active_legacy_id):
    event_ids = _get_event_controller_ids(event)

    if active_instance_id is not None and active_instance_id in event_ids:
        return True

    if active_legacy_id is not None and active_legacy_id in event_ids:
        return True

    try:
        if pygame.joystick.get_count() <= 1:
            LOGGER.debug(
                "Evento joystick accettato dal criterio di compatibilità | event_ids=%s | instance_id=%s | legacy_id=%s",
                event_ids,
                active_instance_id,
                active_legacy_id,
            )
            return True
    except pygame.error:
        pass

    return False


def _active_joystick_ids():
    return (
        _get_joystick_instance_id(_JOYSTICK),
        _get_joystick_legacy_id(_JOYSTICK),
    )


def _apply_button_event(event, actions, mapping):
    if event.button == mapping.button_takeoff:
        actions["takeoff"] = True
    elif event.button == mapping.button_land:
        actions["land"] = True
    elif event.button == mapping.button_detection:
        actions["detect"] = True
    elif event.button == mapping.button_autonomy:
        actions["autonomy"] = True
    elif event.button == mapping.button_quit:
        actions["quit"] = True


def _handle_device_added(event):
    if _JOYSTICK is not None:
        return
    try:
        device_index = getattr(event, "device_index", getattr(event, "which", 0))
        _connect_first_joystick(device_index)
    except RuntimeError:
        pass


def _handle_device_removed(event, active_instance_id, active_legacy_id) -> bool:
    removed_ids = _get_event_controller_ids(event)

    try:
        single_device = pygame.joystick.get_count() <= 1
    except pygame.error:
        single_device = True

    era_il_nostro = (
        (active_instance_id is not None and active_instance_id in removed_ids)
        or (active_legacy_id is not None and active_legacy_id in removed_ids)
        or (active_instance_id is None and single_device)
    )
    if not era_il_nostro:
        return False

    LOGGER.warning("Joystick disconnesso.")
    _disconnect_current_joystick()

    if pygame.joystick.get_count() > 0:
        try:
            _connect_first_joystick()
            return False
        except RuntimeError:
            return True
    return True


def read_events():
    actions = {
        "quit": False,
        "takeoff": False,
        "land": False,
        "detect": False,
        "autonomy": False,
    }

    active_instance_id, active_legacy_id = _active_joystick_ids()
    mapping = APP_CONFIG.joystick

    try:
        events = pygame.event.get()
    except pygame.error:
        actions["quit"] = True
        return actions

    for event in events:
        if event.type == pygame.QUIT:
            actions["quit"] = True

        elif event.type == pygame.JOYBUTTONDOWN:
            if not _event_matches_active_joystick(event, active_instance_id, active_legacy_id):
                continue

            LOGGER.debug(
                "JOYBUTTONDOWN ricevuto | button=%s | event_ids=%s",
                getattr(event, "button", None),
                _get_event_controller_ids(event),
            )
            _apply_button_event(event, actions, mapping)

        elif event.type == pygame.JOYDEVICEADDED:
            _handle_device_added(event)
            active_instance_id, active_legacy_id = _active_joystick_ids()

        elif event.type == pygame.JOYDEVICEREMOVED:
            if _handle_device_removed(event, active_instance_id, active_legacy_id):
                actions["quit"] = True
            active_instance_id, active_legacy_id = _active_joystick_ids()

    return actions


def _zero_command():
    return {
        "lr": 0,
        "fb": 0,
        "ud": 0,
        "yaw": 0,
    }


def _apply_deadzone(value, deadzone):
    if abs(value) < deadzone:
        return 0.0
    span = 1.0 - deadzone
    if span <= 0.0:
        return value
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - deadzone) / span


def _axis_to_speed(value, speed_pct):
    speed_pct = max(0, min(100, int(speed_pct)))
    value = _apply_deadzone(value, APP_CONFIG.joystick.deadzone)
    value = max(-1.0, min(1.0, value))
    return int(value * speed_pct)


def _get_axis_value(index):
    if _JOYSTICK is None:
        return 0.0

    try:
        if index < 0 or index >= _JOYSTICK.get_numaxes():
            return 0.0
        return _JOYSTICK.get_axis(index)
    except (AttributeError, OSError, pygame.error):
        return 0.0


def get_command(speed_pct=50):
    try:
        pygame.event.pump()
    except pygame.error:
        return _zero_command()

    if _JOYSTICK is None:
        return _zero_command()

    mapping = APP_CONFIG.joystick

    lr = _axis_to_speed(_get_axis_value(mapping.axis_lr), speed_pct)
    fb = _axis_to_speed(-_get_axis_value(mapping.axis_fb), speed_pct)
    ud = _axis_to_speed(-_get_axis_value(mapping.axis_ud), speed_pct)
    yaw = _axis_to_speed(_get_axis_value(mapping.axis_yaw), speed_pct)

    return {
        "lr": lr,
        "fb": fb,
        "ud": ud,
        "yaw": yaw,
    }


def format_joystick_help() -> str:
    mapping = APP_CONFIG.joystick

    w = 26
    sep = "─" * 58
    righe = [
        "",
        "Comandi del controller",
        sep,
        f"{'Pulsante':<{w}}  Azione",
        sep,
        f"{mapping.label_takeoff:<{w}}  decolla",
        f"{mapping.label_land:<{w}}  atterra",
        f"{mapping.label_detection:<{w}}  accende e spegne il riconoscimento",
        f"{mapping.label_autonomy:<{w}}  accende e spegne il volo autonomo",
        f"{mapping.label_quit:<{w}}  chiude la sessione e salva i dati",
        sep,
        f"{'Asse':<{w}}  Movimento",
        sep,
        f"{mapping.label_axis_lr:<{w}}  trasla a sinistra e a destra",
        f"{mapping.label_axis_fb:<{w}}  avanza e indietreggia",
        f"{mapping.label_axis_ud:<{w}}  sale e scende",
        f"{mapping.label_axis_yaw:<{w}}  ruota su sé stesso",
        sep,
    ]
    return "\n".join(righe)
