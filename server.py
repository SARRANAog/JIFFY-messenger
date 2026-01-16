# server.py
import socket
import threading
import json
import time

HOST = "0.0.0.0"
PORT = 5050

clients_lock = threading.Lock()
clients = {}  # conn -> {"addr": ..., "name": ...}

def send_json(conn: socket.socket, obj: dict):
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    conn.sendall(data)

def broadcast(sender_conn: socket.socket, payload: dict):
    dead = []
    with clients_lock:
        for conn in clients.keys():
            if conn is sender_conn:
                continue
            try:
                send_json(conn, payload)
            except Exception:
                dead.append(conn)

    for conn in dead:
        disconnect(conn, reason="send_failed")

def disconnect(conn: socket.socket, reason=""):
    with clients_lock:
        info = clients.pop(conn, None)
    try:
        conn.close()
    except Exception:
        pass

    if info:
        msg = {
            "type": "system",
            "ts": int(time.time()),
            "text": f"❌ {info.get('name','(unknown)')} отключился. {('(' + reason + ')') if reason else ''}".strip()
        }
        print(f"[SERVER] {msg['text']}")
        broadcast(None, msg)  # None ок: broadcast пропустит sender сравнение

def handle_client(conn: socket.socket, addr):
    conn_file = conn.makefile("r", encoding="utf-8", newline="\n")

    # 1) ждём hello
    try:
        line = conn_file.readline()
        if not line:
            disconnect(conn, "no_hello")
            return
        hello = json.loads(line)
        if hello.get("type") != "hello" or not hello.get("name"):
            send_json(conn, {"type": "error", "text": "Expected hello with name"})
            disconnect(conn, "bad_hello")
            return
        name = str(hello["name"])[:32]
    except Exception:
        disconnect(conn, "hello_parse_error")
        return

    with clients_lock:
        clients[conn] = {"addr": addr, "name": name}

    print(f"[SERVER] ✅ Подключился {name} ({addr[0]}:{addr[1]})")

    # уведомим остальных
    join_msg = {
        "type": "system",
        "ts": int(time.time()),
        "text": f"✅ {name} подключился."
    }
    broadcast(conn, join_msg)

    # 2) читаем сообщения
    try:
        while True:
            line = conn_file.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except Exception:
                send_json(conn, {"type": "error", "text": "Bad JSON"})
                continue

            if msg.get("type") == "msg":
                text = str(msg.get("text", ""))[:2000]
                if not text.strip():
                    continue

                out = {
                    "type": "msg",
                    "ts": int(time.time()),
                    "from": name,
                    "text": text
                }
                print(f"[{name}] {text}")
                broadcast(conn, out)

            elif msg.get("type") == "ping":
                send_json(conn, {"type": "pong", "ts": int(time.time())})
            else:
                send_json(conn, {"type": "error", "text": "Unknown message type"})
    finally:
        disconnect(conn, "client_closed")

def main():
    print(f"[SERVER] Запуск: {HOST}:{PORT}")
    print("[SERVER] Разреши порт в брандмауэре (Windows) и узнай IP своего ПК (ipconfig).")
    print("[SERVER] Жду подключений...\n")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(50)

        while True:
            conn, addr = s.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()

if __name__ == "__main__":
    main()
