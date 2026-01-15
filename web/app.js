const elChat = document.getElementById("chatList");
const elChatScroll = document.getElementById("chatScroll");
const elStatus = document.getElementById("status");
const elOverlay = document.getElementById("overlay");
const elName = document.getElementById("name");
const elMsg = document.getElementById("msg");

let myName = "User";

/* ---------- helpers ---------- */
function nowTS() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function api() {
    return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
}

function isNearBottom() {
    if (!elChatScroll) return true;
    const threshold = 80;
    return (elChatScroll.scrollHeight - elChatScroll.scrollTop - elChatScroll.clientHeight) < threshold;
}

function scrollToBottom() {
    if (!elChatScroll) return;
    elChatScroll.scrollTop = elChatScroll.scrollHeight;
}

function autoResizeTextarea() {
    if (!elMsg) return;
    elMsg.style.height = "0px";
    const h = Math.min(elMsg.scrollHeight, 160);
    elMsg.style.height = h + "px";
}

/* ---------- fast render queue (no freezes) ---------- */
const renderQueue = [];
let renderScheduled = false;

function enqueueRender(item) {
    renderQueue.push(item);
    if (!renderScheduled) {
        renderScheduled = true;
        requestAnimationFrame(flushRender);
    }
}

function flushRender() {
    renderScheduled = false;
    if (!elChat) return;

    const keepBottom = isNearBottom();

    const frag = document.createDocumentFragment();

    // батчим за один кадр; если очередь огромная — всё равно быстро,
    // потому что один append(frag) и минимум layout.
    for (let i = 0; i < renderQueue.length; i++) {
        const it = renderQueue[i];

        if (it.kind === "msg") {
            const row = document.createElement("div");
            row.className = "bubble-row " + (it.me ? "me" : "other");

            const bubble = document.createElement("div");
            bubble.className = "bubble " + (it.me ? "me" : "other");
            bubble.textContent = it.text || "";

            row.appendChild(bubble);
            frag.appendChild(row);

            const time = document.createElement("div");
            time.className = "ts " + (it.me ? "me" : "other");
            time.textContent = it.ts || nowTS();
            frag.appendChild(time);
        } else if (it.kind === "system") {
            const row = document.createElement("div");
            row.className = "bubble-row system";

            const bubble = document.createElement("div");
            bubble.className = "bubble system";
            bubble.textContent = it.text || "";

            row.appendChild(bubble);
            frag.appendChild(row);
        }
    }

    renderQueue.length = 0;
    elChat.appendChild(frag);

    if (keepBottom) scrollToBottom();
}

/* ---------- callbacks from python ---------- */
window.setStatus = (text) => {
    if (elStatus) elStatus.textContent = (text ?? "").toString();
};

window.addSystem = (text) => {
    enqueueRender({ kind: "system", text: (text ?? "").toString() });
};

window.addMessage = (ts, from, text) => {
    const me = ((from || "") === (myName || ""));
    enqueueRender({ kind: "msg", me, text: (text ?? "").toString(), ts: ts || nowTS() });
};

/* ---------- window controls ---------- */
document.getElementById("btnClose").addEventListener("click", () => api()?.win_close());
document.getElementById("btnMin").addEventListener("click", () => api()?.win_minimize());
document.getElementById("btnMax").addEventListener("click", () => api()?.win_toggle_max());

/* ---------- theme ---------- */
function applyTheme(theme) {
    const t = (theme || "dark").toString().toLowerCase();
    document.documentElement.classList.toggle("light", t === "light");
}

document.getElementById("btnTheme").addEventListener("click", async () => {
    // быстрый локальный переключатель
    document.documentElement.classList.toggle("light");
    const next = document.documentElement.classList.contains("light") ? "light" : "dark";

    // синхронизируем с бэком, если умеет
    try {
        const a = api();
        if (a?.toggle_theme) {
            const res = await a.toggle_theme();
            if (res?.theme) applyTheme(res.theme);
            return;
        }
    } catch (e) { }

    // если бэка нет/не умеет — остаёмся на локальном
    applyTheme(next);
});

// подтягиваем тему из бэка при готовности pywebview
window.addEventListener("pywebviewready", async () => {
    try {
        const a = api();
        if (a?.get_theme) {
            const res = await a.get_theme();
            if (res?.theme) applyTheme(res.theme);
        }
    } catch (e) { }
});

/* ---------- login ---------- */
async function doLogin() {
    const a = api();
    if (!a) {
        if (elStatus) elStatus.textContent = "API not ready...";
        return;
    }

    const name = (elName.value || "").trim() || "User";
    const res = await a.start(name);

    if (!res || !res.ok) {
        if (elStatus) elStatus.textContent = "Connect failed: " + (res?.error || "unknown");
        enqueueRender({ kind: "system", text: "Connect failed: " + (res?.error || "unknown") });
        return;
    }

    myName = res.name || name || "User";
    elOverlay.classList.add("hidden");

    enqueueRender({ kind: "system", text: `Logged in as ${myName}` });

    elMsg.focus();
}

document.getElementById("btnStart").addEventListener("click", doLogin);
elName.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doLogin();
});

/* ---------- send (Enter отправка, Shift+Enter перенос) ---------- */
async function sendMessageFromUI(text) {
    const a = api();
    const msg = (text ?? "").toString().trim();
    if (!msg) return;

    // optimistic UI
    enqueueRender({ kind: "msg", me: true, text: msg, ts: nowTS() });

    try {
        const res = await a.send_message(msg);
        if (res && res.ok === false) {
            if (elStatus) elStatus.textContent = "Send failed: " + (res.error || "unknown");
            enqueueRender({ kind: "system", text: "Send failed: " + (res.error || "unknown") });
        }
    } catch (e) {
        if (elStatus) elStatus.textContent = "Send failed: " + e;
        enqueueRender({ kind: "system", text: "Send failed: " + e });
    }
}

document.getElementById("btnSend").addEventListener("click", async () => {
    const text = elMsg.value;
    elMsg.value = "";
    autoResizeTextarea();
    await sendMessageFromUI(text);
    elMsg.focus();
});

elMsg.addEventListener("input", autoResizeTextarea);

elMsg.addEventListener("keydown", async (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const text = elMsg.value;
        elMsg.value = "";
        autoResizeTextarea();
        await sendMessageFromUI(text);
    }
});

/* ---------- initial focus ---------- */
setTimeout(() => elName?.focus(), 50);
setTimeout(() => autoResizeTextarea(), 0);
