# -*- coding: utf-8 -*-

import ctypes
import json
import os
import socket
import ssl
import threading
import time
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

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


def ui_message(ts: str, frm: str, text: str, client_msg_id: Optional[str] = None) -> None:
    ui_eval(
        "addMessage("
        f"{json.dumps(ts, ensure_ascii=False)},"
        f"{json.dumps(frm, ensure_ascii=False)},"
        f"{json.dumps(text, ensure_ascii=False)},"
        f"{json.dumps(client_msg_id, ensure_ascii=False)}"
        ");"
    )


class ClientState:
    def __init__(self) -> None:
        self.sock: Optional[socket.socket] = None
        self.sock_file = None
        self.connected: bool = False

        self.username: str = "user"
        self.display_name: str = "@user"
        self.user_id: Optional[int] = None

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
            if self.sock_file:
                try:
                    self.sock_file.close()
                except Exception:
                    pass
        finally:
            self.sock_file = None

        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None


def recv_loop(state: ClientState, local_sock: socket.socket, sock_file) -> None:
    try:
        f = sock_file
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
                client_msg_id = msg.get("client_msg_id")
                if client_msg_id is not None:
                    client_msg_id = str(client_msg_id)
                ui_message(ts, msg.get("from", "?"), msg.get("text", ""), client_msg_id)
            elif t == "system":
                ui_system(msg.get("text", ""))
            elif t == "error":
                ui_system("SERVER ERROR: " + str(msg.get("text", "")))
            elif t == "pong":
                pass
            else:
                pass
    except Exception as e:
        ui_system("Receiver error: " + str(e))
    finally:
        state.close()
        ui_status("Not connected")


class Settings:
    def __init__(self, path: str) -> None:
        self.path = path
        self.theme = "dark"
        self.remember_device = False
        self.username = ""
        self.password = ""
        self._load()

    def _load(self) -> None:
        try:
            if not os.path.exists(self.path):
                return
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)

            theme = str(data.get("theme", "dark")).lower()
            self.theme = "light" if theme == "light" else "dark"

            self.remember_device = bool(data.get("remember_device", False))
            self.username = str(data.get("username", "") or "")
            self.password = str(data.get("password", "") or "")
        except Exception:
            self.theme = "dark"
            self.remember_device = False
            self.username = ""
            self.password = ""

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "theme": self.theme,
                        "remember_device": self.remember_device,
                        "username": self.username,
                        "password": self.password,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _get_primary_work_area() -> Tuple[int, int, int, int]:
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


def _center_in_work_area(win_w: int, win_h: int) -> Tuple[int, int]:
    x, y, w, h = _get_primary_work_area()
    cx = x + max(0, (w - win_w) // 2)
    cy = y + max(0, (h - win_h) // 2)
    return int(cx), int(cy)


class Api:
    def __init__(self, state: ClientState, settings: Settings) -> None:
        self.state = state
        self.settings = settings

    def _connect_and_auth(self, mode: str, username: str, password: str, bio: str = "") -> Dict[str, Any]:
        u = (username or "").strip()
        if u.startswith("@"):
            u = u[1:]
        u = u.strip().lower()

        if not u or not password:
            return {"ok": False, "error": "Missing username/password"}

        ui_status(f"Connecting to {DEFAULT_HOST}:{DEFAULT_PORT} (TLS={'ON' if DEFAULT_TLS else 'OFF'})...")
        s, reason = try_connect(DEFAULT_HOST, DEFAULT_PORT, DEFAULT_TLS)
        if s is None:
            ui_status("Not connected")
            ui_system("Connect failed: " + (reason or "unknown"))
            return {"ok": False, "error": reason or "unknown"}

        try:
            f = s.makefile("r", encoding="utf-8", newline="\n")

            self.state.send_lock = threading.Lock()
            self.state.sock = s
            self.state.sock_file = f

            if mode == "register":
                self.state.send_json({"type": "auth_register", "username": u, "password": password, "bio": bio or ""})
            else:
                self.state.send_json({"type": "auth_login", "username": u, "password": password})

            line = f.readline()
            if not line:
                self.state.close()
                ui_status("Not connected")
                return {"ok": False, "error": "No auth response from server"}

            try:
                resp = json.loads(line)
            except Exception:
                self.state.close()
                ui_status("Not connected")
                return {"ok": False, "error": "Bad auth response (not JSON)"}

            if resp.get("type") != "auth_ok":
                err = str(resp.get("text") or resp.get("error") or "Auth failed")
                self.state.close()
                ui_status("Not connected")
                ui_system("Auth failed: " + err)
                return {"ok": False, "error": err}

            user = resp.get("user") or {}
            self.state.username = str(user.get("username") or u)
            self.state.display_name = str(user.get("display_name") or ("@" + self.state.username))
            try:
                self.state.user_id = int(user.get("user_id")) if user.get("user_id") is not None else None
            except Exception:
                self.state.user_id = None

            self.state.connected = True
            ui_status(f"Connected to {DEFAULT_HOST}:{DEFAULT_PORT} (TLS={'ON' if DEFAULT_TLS else 'OFF'})")
            ui_system("Auth OK. Connected.")

            threading.Thread(target=recv_loop, args=(self.state, s, f), daemon=True).start()
            return {"ok": True, "user": {"user_id": self.state.user_id, "username": self.state.username, "display_name": self.state.display_name}}

        except Exception as e:
            try:
                self.state.close()
            except Exception:
                pass
            ui_status("Not connected")
            ui_system("Auth error: " + str(e))
            return {"ok": False, "error": str(e)}

    def send_message(self, text: str, client_msg_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.state.connected or self.state.sock is None:
            return {"ok": False, "error": "Not connected"}

        t = (text or "").strip()
        if not t:
            return {"ok": True}

        payload: Dict[str, Any] = {"type": "msg", "text": t}
        if client_msg_id:
            payload["client_msg_id"] = str(client_msg_id)[:128]

        try:
            self.state.send_json(payload)
            return {"ok": True}
        except Exception as e:
            self.state.close()
            ui_status("Not connected")
            ui_system("Send failed: " + str(e))
            return {"ok": False, "error": str(e)}

    def toggle_theme(self) -> Dict[str, Any]:
        self.settings.theme = "light" if self.settings.theme != "light" else "dark"
        self.settings.save()
        return {"ok": True, "theme": self.settings.theme}

    def get_theme(self) -> Dict[str, Any]:
        return {"ok": True, "theme": self.settings.theme}

    def get_saved_credentials(self) -> Dict[str, Any]:
        if not self.settings.remember_device:
            return {"ok": True, "remember": False, "username": "", "password": ""}
        return {"ok": True, "remember": True, "username": self.settings.username or "", "password": self.settings.password or ""}

    def save_credentials(self, username: str, password: str, remember: bool = True) -> Dict[str, Any]:
        self.settings.username = (username or "").strip()[:64]
        self.settings.password = (password or "")[:128]
        self.settings.remember_device = bool(remember)
        self.settings.save()
        return {"ok": True}

    def auth_login(self, username: str, password: str) -> Dict[str, Any]:
        self.save_credentials(username, password, True)
        return self._connect_and_auth("login", username, password)

    def auth_register(self, username: str, password: str, bio: str = "") -> Dict[str, Any]:
        self.save_credentials(username, password, True)
        return self._connect_and_auth("register", username, password, bio=bio or "")

    def win_close(self) -> None:
        if _window:
            _window.destroy()

    def win_minimize(self) -> None:
        if _window:
            _window.minimize()

    def win_toggle_max(self) -> None:
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
                    setattr(_window, "_normal_bounds", (int(_window.x), int(_window.y), int(_window.width), int(_window.height)))
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


def _ensure_workdir() -> None:
    try:
        import sys
        base_dir = getattr(sys, "_MEIPASS", None)
        if base_dir:
            os.chdir(base_dir)
        else:
            os.chdir(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass


def main() -> None:
    global _window
    _ensure_workdir()

    state = ClientState()
    settings = Settings(path="settings.json")
    api = Api(state, settings)

    win_w, win_h = 1000, 700
    cx, cy = _center_in_work_area(win_w, win_h)

    _window = webview.create_window(
        APP_TITLE,
        url="web/index.html",
        width=win_w,
        height=win_h,
        x=cx,
        y=cy,
        frameless=True,
        easy_drag=False,
        js_api=api,
        background_color="#0f1115",
    )

    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
