# -*- coding: utf-8 -*-
import ctypes
import json
import os
import socket
import ssl
import threading
import time
from datetime import datetime
from typing import Optional, Tuple

import webview

DEFAULT_HOST = "wispy-breeze-6674.fly.dev"
DEFAULT_PORT = 443
DEFAULT_TLS = True

APP_TITLE = "JIFFY"

_window: Optional[webview.Window] = None


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def connect_socket(host: str, port: int, use_tls: bool) -> socket.socket:
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.settimeout(10)
    raw.connect((host, port))
    raw.settimeout(None)

    if not use_tls:
        return raw

    ctx = ssl.create_default_context()
    return ctx.wrap_socket(raw, server_hostname=host)


def try_connect(host: str, port: int, use_tls: bool) -> Tuple[Optional[socket.socket], Optional[str]]:
    try:
        s = connect_socket(host, port, use_tls)
        return s, None
    except socket.gaierror:
        return None, "Host not found (DNS)."
    except ConnectionRefusedError:
        return None, "Connection refused."
    except TimeoutError:
        return None, "Connection timeout."
    except ssl.SSLError as e:
        return None, "TLS error: " + str(e)
    except Exception as e:
        return None, "Error: " + str(e)


def ui_eval(js: str) -> None:
    if _window is None:
        return
    try:
        _window.evaluate_js(js)
    except Exception:
        pass


def ui_status(text: str) -> None:
    ui_eval(f"setStatus({json.dumps(text, ensure_ascii=False)});")


def ui_system(text: str) -> None:
    ui_eval(f"addSystem({json.dumps(text, ensure_ascii=False)});")


def ui_message(ts: str, frm: str, text: str) -> None:
    ui_eval(
        "addMessage("
        f"{json.dumps(ts, ensure_ascii=False)},"
        f"{json.dumps(frm, ensure_ascii=False)},"
        f"{json.dumps(text, ensure_ascii=False)}"
        ");"
    )


class ClientState:
    def __init__(self) -> None:
        self.sock: Optional[socket.socket] = None
        self.connected: bool = False
        self.username: str = "User"
        self.send_lock = threading.Lock()

    def send_json(self, obj: dict) -> None:
        s = self.sock
        if s is None:
            raise RuntimeError("Socket is not connected")

        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self.send_lock:
            s.sendall(data)

    def close(self) -> None:
        self.connected = False
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None


def recv_loop(state: ClientState, local_sock: socket.socket) -> None:
    try:
        f = local_sock.makefile("r", encoding="utf-8", newline="\n")
        while True:
            line = f.readline()
            if not line:
                ui_system("Connection closed by server.")
                break

            try:
                msg = json.loads(line)
            except Exception:
                ui_system("Bad data (not JSON).")
                continue

            t = msg.get("type")
            if t == "msg":
                ts = fmt_ts(int(msg.get("ts", time.time())))
                ui_message(ts, msg.get("from", "?"), msg.get("text", ""))
            elif t == "system":
                ui_system(msg.get("text", ""))
            elif t == "error":
                ui_system("SERVER ERROR: " + str(msg.get("text", "")))
    except Exception as e:
        ui_system("Receiver error: " + str(e))
    finally:
        state.close()
        ui_status("Not connected")


class Settings:
    def __init__(self, path: str) -> None:
        self.path = path
        self.theme = "dark"  # "dark" | "light"
        self._load()

    def _load(self) -> None:
        try:
            if not os.path.exists(self.path):
                return
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            theme = str(data.get("theme", "dark")).lower()
            self.theme = "light" if theme == "light" else "dark"
        except Exception:
            self.theme = "dark"

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"theme": self.theme}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


# --- Windows work area (exclude taskbar) ---
class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _get_primary_work_area() -> Tuple[int, int, int, int]:
    """
    Возвращает (x, y, width, height) рабочей области (без панели задач) для primary monitor.
    """
    try:
        SPI_GETWORKAREA = 0x0030
        rect = _RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        if ok:
            x = int(rect.left)
            y = int(rect.top)
            w = int(rect.right - rect.left)
            h = int(rect.bottom - rect.top)
            return x, y, w, h
    except Exception:
        pass
    return 0, 0, 1000, 700


class Api:
    def __init__(self, state: ClientState, settings: Settings) -> None:
        self.state = state
        self.settings = settings

    # --- connection ---
    def start(self, name: str):
        self.state.username = (name or "User").strip()[:32] or "User"

        ui_status(f"Connecting to {DEFAULT_HOST}:{DEFAULT_PORT} (TLS={'ON' if DEFAULT_TLS else 'OFF'})...")
        s, reason = try_connect(DEFAULT_HOST, DEFAULT_PORT, DEFAULT_TLS)
        if s is None:
            ui_status("Not connected")
            ui_system("Connect failed: " + (reason or "unknown"))
            return {"ok": False, "error": reason or "unknown"}

        self.state.sock = s
        self.state.connected = True

        ui_status(f"Connected to {DEFAULT_HOST}:{DEFAULT_PORT} (TLS={'ON' if DEFAULT_TLS else 'OFF'})")
        ui_system("Connected.")

        try:
            self.state.send_json({"type": "hello", "name": self.state.username})
        except Exception as e:
            ui_system("Failed to send hello: " + str(e))
            self.state.close()
            ui_status("Not connected")
            return {"ok": False, "error": str(e)}

        threading.Thread(target=recv_loop, args=(self.state, s), daemon=True).start()
        return {"ok": True, "name": self.state.username}

    def send_message(self, text: str):
        if not self.state.connected or self.state.sock is None:
            return {"ok": False, "error": "Not connected"}

        t = (text or "").strip()
        if not t:
            return {"ok": True}

        try:
            self.state.send_json({"type": "msg", "text": t})
            return {"ok": True}
        except Exception as e:
            self.state.close()
            ui_status("Not connected")
            ui_system("Send failed: " + str(e))
            return {"ok": False, "error": str(e)}

    # --- theme ---
    def toggle_theme(self):
        self.settings.theme = "light" if self.settings.theme != "light" else "dark"
        self.settings.save()
        return {"ok": True, "theme": self.settings.theme}

    def get_theme(self):
        return {"ok": True, "theme": self.settings.theme}

    # --- window controls ---
    def win_close(self):
        if _window:
            _window.destroy()

    def win_minimize(self):
        if _window:
            _window.minimize()

    def win_toggle_max(self):
        """
        Максимизация НЕ в fullscreen, а в рабочую область (без панели задач).
        Restore возвращает прежний размер/позицию.
        """
        if not _window:
            return

        if not hasattr(_window, "_is_maximized"):
            setattr(_window, "_is_maximized", False)
        if not hasattr(_window, "_normal_bounds"):
            try:
                nb = (int(_window.x), int(_window.y), int(_window.width), int(_window.height))
            except Exception:
                nb = (80, 80, 1000, 700)
            setattr(_window, "_normal_bounds", nb)

        is_max = bool(getattr(_window, "_is_maximized", False))

        try:
            if is_max:
                x, y, w, h = getattr(_window, "_normal_bounds", (80, 80, 1000, 700))
                try:
                    _window.move(int(x), int(y))
                except Exception:
                    pass
                try:
                    _window.resize(int(w), int(h))
                except Exception:
                    pass
                setattr(_window, "_is_maximized", False)
            else:
                try:
                    setattr(
                        _window,
                        "_normal_bounds",
                        (int(_window.x), int(_window.y), int(_window.width), int(_window.height)),
                    )
                except Exception:
                    pass

                x, y, w, h = _get_primary_work_area()
                try:
                    _window.move(int(x), int(y))
                except Exception:
                    pass
                try:
                    _window.resize(int(w), int(h))
                except Exception:
                    pass

                setattr(_window, "_is_maximized", True)
        except Exception:
            pass


def _ensure_workdir():
    """
    Делает так, чтобы url="web/index.html" работал и в dev, и в PyInstaller onefile.
    """
    try:
        import sys

        base_dir = getattr(sys, "_MEIPASS", None)
        if base_dir:
            os.chdir(base_dir)
        else:
            os.chdir(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass


def main():
    global _window

    _ensure_workdir()

    state = ClientState()
    settings = Settings(path="settings.json")
    api = Api(state, settings)

    _window = webview.create_window(
        APP_TITLE,
        url="web/index.html",
        width=1000,
        height=700,
        frameless=True,
        easy_drag=True,
        js_api=api,
        background_color="#0f1115",
    )

    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
