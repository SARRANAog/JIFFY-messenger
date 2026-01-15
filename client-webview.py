# -*- coding: utf-8 -*-
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
        FIX: в некоторых версиях pywebview свойство _window.maximized
        не обновляется корректно. Делаем toggle на нашей стороне.
        """
        if not _window:
            return

        # лениво создаём флаг на объекте окна
        if not hasattr(_window, "_is_maximized"):
            setattr(_window, "_is_maximized", False)

        is_max = getattr(_window, "_is_maximized", False)

        try:
            if is_max:
                _window.restore()
                setattr(_window, "_is_maximized", False)
            else:
                _window.maximize()
                setattr(_window, "_is_maximized", True)
        except Exception:
            # fallback: пробуем всё равно переключиться
            try:
                _window.restore()
                setattr(_window, "_is_maximized", False)
            except Exception:
                pass


def _ensure_workdir():
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
        "Py Messenger",
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
