"""Klavye + oyun kolu / gitar kontrolcusu -> zaman damgali oyun girdileri ve menu eylemleri.

pygame-ce olaylari SDL zaman damgasi tasimaz; olay zamani, olaylarin cekildigi (poll) ana gore
kestirilir: onceki poll ile simdiki poll arasinin ortasi. Uygulama dongusu frame'ler arasinda ~1 ms
aralikla poll ettigi icin niceleme hatasi ~+-0.5 ms (render sirasinda ~+-1-2 ms) kalir.

Cikti:
- GameInput(kind: InputKind, fret, value, pc)  -> oyun sahnesi pc'yi SongTime'a cevirip motora verir
- menu eylemleri: "UP","DOWN","LEFT","RIGHT","CONFIRM","BACK","OPTION" + "PAUSE","START"
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pygame

from .engine.input_event import InputKind

try:  # SDL GameController API (standart dugme adlari: Xbox 360 gitarlari dahil)
    from pygame._sdl2 import controller as _ctl
except Exception:  # pragma: no cover
    _ctl = None

MENU_REPEAT_DELAY = 0.34
MENU_REPEAT_RATE = 0.065
WHAMMY_KEY_PERIOD = 0.100

NAV_KEYS = {
    pygame.K_UP: "UP", pygame.K_DOWN: "DOWN", pygame.K_LEFT: "LEFT", pygame.K_RIGHT: "RIGHT",
    pygame.K_RETURN: "CONFIRM", pygame.K_KP_ENTER: "CONFIRM", pygame.K_ESCAPE: "BACK",
    pygame.K_BACKSPACE: "BACK", pygame.K_TAB: "OPTION", pygame.K_SPACE: "CONFIRM",
}
REPEATABLE = {"UP", "DOWN", "LEFT", "RIGHT"}

# oyun eylemi -> menu eylemi (GH tarzi: yesil onay, kirmizi geri, strum gezinme)
ACTION_MENU = {
    "fret0": "CONFIRM", "fret1": "BACK", "fret2": "LEFT", "fret3": "RIGHT", "fret4": "OPTION",
    "strum_up": "UP", "strum_down": "DOWN", "start": "CONFIRM", "pause": "BACK",
}

# ---- kontrolcu varsayilan eslemesi (SDL GameController standart adlari)
if _ctl is not None:
    CTL_BUTTONS = {
        pygame.CONTROLLER_BUTTON_A: "fret0",
        pygame.CONTROLLER_BUTTON_B: "fret1",
        pygame.CONTROLLER_BUTTON_Y: "fret2",
        pygame.CONTROLLER_BUTTON_X: "fret3",
        pygame.CONTROLLER_BUTTON_LEFTSHOULDER: "fret4",
        pygame.CONTROLLER_BUTTON_DPAD_UP: "strum_up",
        pygame.CONTROLLER_BUTTON_DPAD_DOWN: "strum_down",
        pygame.CONTROLLER_BUTTON_DPAD_LEFT: "nav_left",
        pygame.CONTROLLER_BUTTON_DPAD_RIGHT: "nav_right",
        pygame.CONTROLLER_BUTTON_BACK: "star_power",
        pygame.CONTROLLER_BUTTON_START: "start",
        pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: "open_strum",
    }
else:
    CTL_BUTTONS = {}

# genel (GameController olarak taninmayan) joystick: XInput sirasi varsayimi
JOY_BUTTONS = {0: "fret0", 1: "fret1", 3: "fret2", 2: "fret3", 4: "fret4", 5: "open_strum",
               6: "star_power", 7: "start"}

CONTROLLER_HELP = [
    ("Green / Red / Yellow / Blue / Orange", "A / B / Y / X / LB"),
    ("Strum up / down", "D-pad up / down (strum bar)"),
    ("Whammy", "Right stick X (guitar) or right trigger"),
    ("Star Power", "Tilt (right stick Y) or Back / Select"),
    ("Open strum", "RB"),
    ("Pause / Start", "Start"),
    ("Menus", "A confirm, B back, D-pad / strum move"),
]


@dataclass
class GameInput:
    kind: InputKind
    fret: int = -1
    value: float = 0.0
    pc: float = 0.0


class _Pad:
    """Takili bir kontrolcu."""

    def __init__(self, dev, is_controller: bool, instance_id: int, name: str):
        self.dev = dev
        self.is_controller = is_controller
        self.instance_id = instance_id
        self.name = name
        self.is_guitar = "guitar" in name.lower() or "gh" in name.lower().split()
        self.whammy = 0.0
        self.tilt = False
        self.stick_nav = 0     # sol cubukla menu gezinme durumu (-1,0,1)
        self.hat = (0, 0)


class InputManager:
    def __init__(self, settings):
        self.settings = settings
        self.keymap: dict[int, str] = {}
        self.rebuild_keymap()
        self.pads: dict[int, _Pad] = {}
        self._last_poll = time.perf_counter()
        self._menu_held: dict[object, list] = {}     # kaynak -> [eylem, sonraki tekrar]
        self._whammy_keys: set[int] = set()
        self._whammy_phase = 1.0
        self._whammy_next = 0.0
        self.game: list[GameInput] = []
        self.menu: list[str] = []
        self.raw_keys: list[pygame.event.Event] = []
        self.text: list[str] = []
        self.last_device = "keyboard"
        self._ctl_ok = False
        try:
            pygame.joystick.init()
            if _ctl is not None:
                _ctl.init()
                self._ctl_ok = True
        except Exception:
            self._ctl_ok = False

    # ---------------------------------------------------------------- ayar
    def rebuild_keymap(self) -> None:
        k = self.settings.keys
        m: dict[int, str] = {}

        def add(names, action):
            for n in names:
                try:
                    code = pygame.key.key_code(n)
                except (ValueError, pygame.error):
                    continue
                m.setdefault(code, action)

        for i, names in enumerate(k.frets):
            add(names, f"fret{i}")
        add(k.strum_up, "strum_up")
        add(k.strum_down, "strum_down")
        add(k.open_strum, "open_strum")
        add(k.star_power, "star_power")
        add(k.whammy, "whammy")
        add(k.start, "start")
        add(k.pause, "pause")
        self.keymap = m

    # ---------------------------------------------------------------- olaylar
    def begin_poll(self) -> tuple[float, float]:
        now = time.perf_counter()
        prev = self._last_poll
        self._last_poll = now
        self.game.clear()
        self.menu.clear()
        self.raw_keys.clear()
        return prev, now

    def stamp(self, prev: float, now: float) -> float:
        # olayin gercek zamani (prev, now] araliginda; tekduze varsayimla ortasi en iyi kestirim
        if now - prev > 0.050:   # uzun bekleme (pencere tasima vb.): simdiki zaman
            return now
        return (prev + now) * 0.5

    def process(self, ev: pygame.event.Event, pc: float) -> None:
        t = ev.type
        if t == pygame.KEYDOWN:
            self.last_device = "keyboard"
            self.raw_keys.append(ev)
            self._key(ev.key, True, pc)
        elif t == pygame.KEYUP:
            self._key(ev.key, False, pc)
        elif t == pygame.JOYDEVICEADDED:
            self._add_pad(ev.device_index)
        elif t == pygame.JOYDEVICEREMOVED:
            self._remove_pad(getattr(ev, "instance_id", -1))
        elif self._ctl_ok and t in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
            pad = self.pads.get(getattr(ev, "instance_id", -1))
            if pad is not None and pad.is_controller:
                self.last_device = "controller"
                act = CTL_BUTTONS.get(ev.button)
                if act:
                    self._action(act, t == pygame.CONTROLLERBUTTONDOWN, pc, ("c", pad.instance_id, ev.button))
        elif self._ctl_ok and t == pygame.CONTROLLERAXISMOTION:
            pad = self.pads.get(getattr(ev, "instance_id", -1))
            if pad is not None and pad.is_controller:
                self._ctl_axis(pad, ev.axis, ev.value / 32767.0, pc)
        elif t in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
            pad = self.pads.get(getattr(ev, "instance_id", -1))
            if pad is not None and not pad.is_controller:
                self.last_device = "controller"
                act = JOY_BUTTONS.get(ev.button)
                if act:
                    self._action(act, t == pygame.JOYBUTTONDOWN, pc, ("j", pad.instance_id, ev.button))
        elif t == pygame.JOYHATMOTION:
            pad = self.pads.get(getattr(ev, "instance_id", -1))
            if pad is not None and not pad.is_controller:
                self._joy_hat(pad, ev.value, pc)
        elif t == pygame.JOYAXISMOTION:
            pad = self.pads.get(getattr(ev, "instance_id", -1))
            if pad is not None and not pad.is_controller:
                self._joy_axis(pad, ev.axis, ev.value, pc)

    def update(self, now: float) -> None:
        """Menu tus tekrari ve klavye whammy salinimi."""
        for src, rec in list(self._menu_held.items()):
            if now >= rec[1]:
                self.menu.append(rec[0])
                rec[1] = now + MENU_REPEAT_RATE
        if self._whammy_keys and now >= self._whammy_next:
            self._whammy_phase = 0.7 if self._whammy_phase >= 1.0 else 1.0
            self.game.append(GameInput(InputKind.WHAMMY, value=self._whammy_phase, pc=now))
            self._whammy_next = now + WHAMMY_KEY_PERIOD

    def clear_held(self) -> None:
        self._menu_held.clear()

    # ---------------------------------------------------------------- klavye
    def _key(self, key: int, down: bool, pc: float) -> None:
        act = self.keymap.get(key)
        nav = NAV_KEYS.get(key)
        src = ("k", key)
        if down:
            if nav:
                self._menu_press(nav, src, pc)
            elif act and act in ACTION_MENU:
                self._menu_press(ACTION_MENU[act], src, pc)
            if key == pygame.K_ESCAPE or act == "pause":
                self.menu.append("PAUSE")
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER) or act == "start":
                self.menu.append("START")
        else:
            self._menu_held.pop(src, None)
        if act:
            if act == "whammy":
                self._whammy_key(key, down, pc)
            else:
                self._game_action(act, down, pc)

    def _whammy_key(self, key: int, down: bool, pc: float) -> None:
        if down:
            if not self._whammy_keys:
                self._whammy_phase = 1.0
                self.game.append(GameInput(InputKind.WHAMMY, value=1.0, pc=pc))
                self._whammy_next = pc + WHAMMY_KEY_PERIOD
            self._whammy_keys.add(key)
        else:
            self._whammy_keys.discard(key)
            if not self._whammy_keys:
                self.game.append(GameInput(InputKind.WHAMMY, value=0.0, pc=pc))

    # ---------------------------------------------------------------- ortak eylem
    def _menu_press(self, action: str, src, pc: float) -> None:
        self.menu.append(action)
        if action in REPEATABLE:
            self._menu_held[src] = [action, pc + MENU_REPEAT_DELAY]

    def _action(self, act: str, down: bool, pc: float, src) -> None:
        """Kontrolcu dugmesi."""
        if down:
            if act == "nav_left":
                self._menu_press("LEFT", src, pc)
            elif act == "nav_right":
                self._menu_press("RIGHT", src, pc)
            elif act in ACTION_MENU:
                self._menu_press(ACTION_MENU[act], src, pc)
            elif act == "star_power":
                self.menu.append("BACK")
            if act == "start":
                self.menu.append("START")
                self.menu.append("PAUSE")
        else:
            self._menu_held.pop(src, None)
        if not act.startswith("nav_"):
            self._game_action(act, down, pc)

    def _game_action(self, act: str, down: bool, pc: float) -> None:
        if act.startswith("fret"):
            f = int(act[4:])
            self.game.append(GameInput(InputKind.FRET_DOWN if down else InputKind.FRET_UP, fret=f, pc=pc))
        elif not down:
            return
        elif act in ("strum_up", "strum_down"):
            self.game.append(GameInput(InputKind.STRUM, pc=pc))
        elif act == "open_strum":
            self.game.append(GameInput(InputKind.OPEN_STRUM, pc=pc))
        elif act == "star_power":
            self.game.append(GameInput(InputKind.STAR_POWER, pc=pc))

    # ---------------------------------------------------------------- kontrolculer
    def _add_pad(self, device_index: int) -> None:
        try:
            if self._ctl_ok and _ctl.is_controller(device_index):
                c = _ctl.Controller(device_index)
                js = c.as_joystick()
                iid = js.get_instance_id()
                name = c.name or js.get_name()
                self.pads[iid] = _Pad(c, True, iid, name)
                return
            js = pygame.joystick.Joystick(device_index)
            js.init()
            iid = js.get_instance_id()
            self.pads[iid] = _Pad(js, False, iid, js.get_name())
        except Exception:
            pass

    def _remove_pad(self, instance_id: int) -> None:
        pad = self.pads.pop(instance_id, None)
        if pad is None:
            return
        for src in [s for s in self._menu_held if isinstance(s, tuple) and len(s) == 3 and s[1] == instance_id]:
            self._menu_held.pop(src, None)
        try:
            pad.dev.quit()
        except Exception:
            pass

    def pad_names(self) -> list[str]:
        return [p.name + (" (guitar)" if p.is_guitar else "") for p in self.pads.values()]

    def _set_whammy(self, pad: _Pad, v: float, pc: float) -> None:
        v = max(0.0, min(1.0, v))
        if abs(v - pad.whammy) >= 0.02 or (v == 0.0 and pad.whammy != 0.0):
            pad.whammy = v
            self.game.append(GameInput(InputKind.WHAMMY, value=v, pc=pc))

    def _set_tilt(self, pad: _Pad, tilted: bool, pc: float) -> None:
        if tilted and not pad.tilt:
            self.game.append(GameInput(InputKind.STAR_POWER, pc=pc))
        pad.tilt = tilted

    def _stick_nav(self, pad: _Pad, v: float, pc: float) -> None:
        dz = float(self.settings.extra.get("joy_deadzone", 0.35))
        d = -1 if v < -max(0.5, dz) else (1 if v > max(0.5, dz) else 0)
        if d != pad.stick_nav:
            src = ("s", pad.instance_id)
            self._menu_held.pop(src, None)
            if d:
                self._menu_press("UP" if d < 0 else "DOWN", src, pc)
            pad.stick_nav = d

    def _ctl_axis(self, pad: _Pad, axis: int, v: float, pc: float) -> None:
        thr = float(self.settings.extra.get("tilt_threshold", 0.55))
        if axis == pygame.CONTROLLER_AXIS_RIGHTX and pad.is_guitar:
            self._set_whammy(pad, (v + 1.0) * 0.5, pc)
        elif axis == pygame.CONTROLLER_AXIS_TRIGGERRIGHT and not pad.is_guitar:
            self._set_whammy(pad, v, pc)
        elif axis == pygame.CONTROLLER_AXIS_RIGHTY and pad.is_guitar:
            self._set_tilt(pad, abs(v) > thr, pc)
        elif axis == pygame.CONTROLLER_AXIS_LEFTY and not pad.is_guitar:
            self._stick_nav(pad, v, pc)

    def _joy_hat(self, pad: _Pad, value, pc: float) -> None:
        x, y = value
        px, py = pad.hat
        pad.hat = (x, y)
        if y != py:
            if py == 1:
                self._action("strum_up", False, pc, ("h", pad.instance_id, "u"))
            if py == -1:
                self._action("strum_down", False, pc, ("h", pad.instance_id, "d"))
            if y == 1:
                self._action("strum_up", True, pc, ("h", pad.instance_id, "u"))
            if y == -1:
                self._action("strum_down", True, pc, ("h", pad.instance_id, "d"))
        if x != px:
            if px:
                self._action("nav_left" if px < 0 else "nav_right", False, pc, ("h", pad.instance_id, "x"))
            if x:
                self._action("nav_left" if x < 0 else "nav_right", True, pc, ("h", pad.instance_id, "x"))

    def _joy_axis(self, pad: _Pad, axis: int, v: float, pc: float) -> None:
        thr = float(self.settings.extra.get("tilt_threshold", 0.55))
        if axis == 2 and pad.is_guitar:
            self._set_whammy(pad, (v + 1.0) * 0.5, pc)
        elif axis == 3 and pad.is_guitar:
            self._set_tilt(pad, abs(v) > thr, pc)
        elif axis == 5 and not pad.is_guitar:
            self._set_whammy(pad, (v + 1.0) * 0.5, pc)
        elif axis == 1 and not pad.is_guitar:
            self._stick_nav(pad, v, pc)


def key_label(name: str) -> str:
    """Tus adini ekranda gosterilecek hale getir."""
    n = name.strip()
    special = {"return": "Enter", "escape": "Esc", "space": "Space", "up": "Up", "down": "Down",
               "left": "Left", "right": "Right", "right shift": "RShift", "left shift": "LShift",
               "backspace": "Bksp"}
    if n in special:
        return special[n]
    return n.upper() if len(n) <= 3 else n.title()
