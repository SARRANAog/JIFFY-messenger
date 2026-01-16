document.addEventListener("DOMContentLoaded", () => {
    // --- sidebar / main ---
    const elChatList = document.getElementById("chatList");          // sidebar list
    const elChatSearch = document.getElementById("chatSearch");
    const btnNewChat = document.getElementById("btnNewChat");
    const elSidebarStatus = document.getElementById("sidebarStatus");

    const elActiveTitle = document.getElementById("activeChatTitle");
    const elActiveSub = document.getElementById("activeChatSub");

    const elMsgScroll = document.getElementById("msgScroll");
    const elMsgList = document.getElementById("msgList");            // messages list
    const elMsg = document.getElementById("msg");                    // textarea
    const btnSend = document.getElementById("btnSend");

    // --- overlay/auth ---
    const elOverlay = document.getElementById("overlay");
    const elStatus = document.getElementById("status");
    const elName = document.getElementById("name");
    const elPass = document.getElementById("pass");
    const elBio = document.getElementById("bio");
    const rowBio = document.getElementById("rowBio");

    const tabLogin = document.getElementById("tabLogin");
    const tabRegister = document.getElementById("tabRegister");
    const elMode = document.getElementById("mode");
    const btnStart = document.getElementById("btnStart");

    // --- topbar buttons ---
    const btnClose = document.getElementById("btnClose");
    const btnMin = document.getElementById("btnMin");
    const btnMax = document.getElementById("btnMax");
    const btnTheme = document.getElementById("btnTheme");

    let myName = "User";
    let authMode = "login"; // login | register

    // ------------------------
    // Chat model (client MVP)
    // ------------------------
    // chatId: "system" or "dm:@user"
    const chatsById = new Map();        // chatId -> {id,title,lastText,lastTsTxt,unread}
    const chatOrder = [];              // [chatId...]
    const messagesByChat = new Map();  // chatId -> [{me,from,text,ts,clientMsgId,system}]

    let currentChatId = "system";

    // Dedupe server echo vs optimistic
    // client_msg_id -> chatId (so echo knows where to go)
    const pendingEcho = new Map();

    function api() {
        return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
    }

    function setStatus(text) {
        if (elStatus) elStatus.textContent = text || "";
        if (elSidebarStatus) elSidebarStatus.textContent = text || "";
    }

    function nowTS() {
        return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }

    function escapeHtml(s) {
        return (s ?? "")
            .toString()
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function normalizeUser(u) {
        const s = (u || "").toString().trim();
        if (!s) return "";
        return s.startsWith("@") ? s : ("@" + s);
    }

    function chatIdFromPeer(peer) {
        const p = normalizeUser(peer);
        return p ? ("dm:" + p.toLowerCase()) : "";
    }

    function genClientMsgId() {
        try {
            if (crypto && crypto.randomUUID) return crypto.randomUUID();
        } catch (_) { }
        return "m_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10);
    }

    function isNearBottom(container, thresholdPx = 80) {
        if (!container) return true;
        const { scrollTop, clientHeight, scrollHeight } = container;
        return (scrollHeight - (scrollTop + clientHeight)) <= thresholdPx;
    }

    function ensureChat(chatId, title) {
        if (!chatId) return null;

        let c = chatsById.get(chatId);
        if (!c) {
            c = {
                id: chatId,
                title: title || chatId,
                lastText: "",
                lastTsTxt: "",
                unread: 0,
            };
            chatsById.set(chatId, c);
            chatOrder.unshift(chatId);
        } else if (title && (!c.title || c.title === c.id)) {
            c.title = title;
        }

        if (!messagesByChat.get(chatId)) messagesByChat.set(chatId, []);
        return c;
    }

    function bumpChat(chatId) {
        const idx = chatOrder.indexOf(chatId);
        if (idx > 0) {
            chatOrder.splice(idx, 1);
            chatOrder.unshift(chatId);
        }
    }

    function addMessageToChat(chatId, msg) {
        ensureChat(chatId, msg.system ? "System" : (msg.chatTitle || chatId));

        const list = messagesByChat.get(chatId);
        if (!list) return;

        // dedupe by clientMsgId (important for our own echo)
        if (msg.clientMsgId) {
            const exists = list.some(m => m.clientMsgId && m.clientMsgId === msg.clientMsgId);
            if (exists) return;
        }

        list.push(msg);
        if (list.length > 1200) list.splice(0, list.length - 1200);

        const c = chatsById.get(chatId);
        if (c) {
            c.lastText = (msg.text || "").toString();
            c.lastTsTxt = msg.ts || nowTS();
        }

        bumpChat(chatId);
    }

    function renderChatList() {
        if (!elChatList) return;
        const q = (elChatSearch?.value || "").trim().toLowerCase();

        elChatList.innerHTML = "";

        for (const id of chatOrder) {
            const c = chatsById.get(id);
            if (!c) continue;

            const title = (c.title || id).toString();
            const preview = (c.lastText || "").toString();

            if (q) {
                const hay = (title + " " + preview).toLowerCase();
                if (!hay.includes(q)) continue;
            }

            const item = document.createElement("div");
            item.className = "chatitem" + (id === currentChatId ? " active" : "");
            item.dataset.chatId = id;

            const t = document.createElement("div");
            t.className = "chatitem-title";
            t.textContent = title;

            const p = document.createElement("div");
            p.className = "chatitem-preview";
            p.textContent = preview || " ";

            const meta = document.createElement("div");
            meta.className = "chatitem-meta";

            const left = document.createElement("div");
            left.textContent = c.lastTsTxt || "";

            const right = document.createElement("div");
            right.textContent = (c.unread && id !== currentChatId) ? String(c.unread) : "";

            meta.appendChild(left);
            meta.appendChild(right);

            item.appendChild(t);
            item.appendChild(p);
            item.appendChild(meta);

            item.addEventListener("click", () => selectChat(id));

            elChatList.appendChild(item);
        }
    }

    function clearMsgList() {
        if (elMsgList) elMsgList.innerHTML = "";
    }

    function renderMessages(chatId) {
        if (!elMsgList) return;
        clearMsgList();

        const stick = isNearBottom(elMsgScroll);
        const list = messagesByChat.get(chatId) || [];

        const frag = document.createDocumentFragment();

        for (const m of list) {
            const row = document.createElement("div");
            row.className = "bubble-row " + (m.system ? "system" : (m.me ? "me" : "other"));

            const bubble = document.createElement("div");
            bubble.className = "bubble " + (m.system ? "system" : (m.me ? "me" : "other"));
            bubble.innerHTML = escapeHtml(m.text || "");

            row.appendChild(bubble);
            frag.appendChild(row);

            if (!m.system) {
                const ts = document.createElement("div");
                ts.className = "ts " + (m.me ? "me" : "other");
                ts.textContent = m.ts || nowTS();
                frag.appendChild(ts);
            }
        }

        elMsgList.appendChild(frag);

        if (elMsgScroll && stick) {
            elMsgScroll.scrollTop = elMsgScroll.scrollHeight;
        }
    }

    function selectChat(chatId) {
        if (!chatId) return;

        currentChatId = chatId;
        const c = chatsById.get(chatId);

        if (c) c.unread = 0;

        if (elActiveTitle) elActiveTitle.textContent = c ? (c.title || chatId) : chatId;
        if (elActiveSub) elActiveSub.textContent = " ";

        renderChatList();
        renderMessages(chatId);

        setTimeout(() => elMsg?.focus(), 0);
    }

    function openOrCreateDM(raw) {
        const peer = normalizeUser(raw);
        if (!peer) return;

        const id = chatIdFromPeer(peer);
        ensureChat(id, peer);
        renderChatList();
        selectChat(id);
    }

    // ✅ NEW: proper "add interlocutor" action from plus button
    function startNewChatFlow() {
        // 1) use search value if exists
        const fromSearch = (elChatSearch?.value || "").trim();
        let peer = fromSearch;

        // 2) otherwise ask
        if (!peer) peer = prompt("Введите @username собеседника:");

        peer = normalizeUser(peer);
        if (!peer) return;

        openOrCreateDM(peer);

        // keep search clean (optional)
        if (elChatSearch) elChatSearch.value = "";
        renderChatList();
    }

    // ✅ NEW: if user is in system but typed @user in search, auto-create chat and send there
    function resolveChatForSend() {
        if (currentChatId && currentChatId !== "system") return currentChatId;

        const candidate = normalizeUser((elChatSearch?.value || "").trim());
        if (candidate) {
            const id = chatIdFromPeer(candidate);
            ensureChat(id, candidate);
            selectChat(id);
            return id;
        }
        return null;
    }

    // ----------------------------
    // Callbacks from python
    // ----------------------------
    window.setStatus = (text) => setStatus(text);

    window.addSystem = (text) => {
        const chatId = "system";
        ensureChat(chatId, "System");

        addMessageToChat(chatId, {
            me: false,
            from: "System",
            text: text || "",
            ts: nowTS(),
            clientMsgId: null,
            system: true,
            chatTitle: "System",
        });

        // unread if not opened
        if (currentChatId !== chatId) {
            const c = chatsById.get(chatId);
            if (c) c.unread = (c.unread || 0) + 1;
        }

        renderChatList();
        if (currentChatId === chatId) renderMessages(chatId);
    };

    // Signature: addMessage(ts, from, text, client_msg_id)
    window.addMessage = (ts, from, text, clientMsgId) => {
        const fromName = (from || "").toString().trim();
        const isMe = fromName === (myName || "");

        let chatId = null;
        let chatTitle = null;

        if (!isMe) {
            // ✅ FIX: входящее сообщение ВСЕГДА создаёт чат у получателя
            const peer = normalizeUser(fromName);
            chatId = chatIdFromPeer(peer);
            chatTitle = peer;
            ensureChat(chatId, chatTitle);
        } else {
            // echo нашего сообщения
            if (clientMsgId && pendingEcho.has(clientMsgId)) {
                chatId = pendingEcho.get(clientMsgId);
                pendingEcho.delete(clientMsgId);
            } else {
                chatId = currentChatId || "system";
            }
            const c = chatsById.get(chatId);
            chatTitle = c ? c.title : chatId;
        }

        if (!chatId) chatId = "system";

        // Добавляем в историю (и не дублируем по clientMsgId)
        addMessageToChat(chatId, {
            me: isMe,
            from: fromName,
            text: text || "",
            ts: ts || nowTS(),
            clientMsgId: clientMsgId || null,
            system: false,
            chatTitle,
        });

        // unread если чат не активен
        if (currentChatId !== chatId) {
            const c = chatsById.get(chatId);
            if (c) c.unread = (c.unread || 0) + 1;
            renderChatList();
            return;
        }

        renderChatList();
        renderMessages(chatId);
    };

    // ----------------------------
    // Window controls
    // ----------------------------
    btnClose?.addEventListener("click", () => api()?.win_close?.());
    btnMin?.addEventListener("click", () => api()?.win_minimize?.());
    btnMax?.addEventListener("click", () => api()?.win_toggle_max?.());

    btnTheme?.addEventListener("click", async () => {
        document.documentElement.classList.toggle("light");
        try { await api()?.toggle_theme?.(); } catch (_) { }
    });

    // ----------------------------
    // Auth UI
    // ----------------------------
    function setMode(mode) {
        authMode = mode;

        tabLogin?.classList.toggle("active", mode === "login");
        tabRegister?.classList.toggle("active", mode === "register");

        if (elMode) elMode.textContent = "Режим: " + (mode === "login" ? "вход" : "регистрация");
        if (btnStart) btnStart.textContent = (mode === "login" ? "Войти" : "Зарегистрироваться");

        rowBio?.classList.toggle("hidden", mode !== "register");

        if (elPass) elPass.autocomplete = (mode === "login" ? "current-password" : "new-password");
        if (elName) elName.placeholder = (mode === "login" ? "@username" : "Придумай @username");
    }

    tabLogin?.addEventListener("click", () => setMode("login"));
    tabRegister?.addEventListener("click", () => setMode("register"));

    async function loadSavedCreds() {
        const a = api();
        if (!a?.get_saved_credentials) return;
        try {
            const res = await a.get_saved_credentials();
            if (res?.ok && res.remember) {
                if (elName) elName.value = res.username || "";
                if (elPass) elPass.value = res.password || "";
            }
        } catch (_) { }
    }

    async function submitAuth() {
        const a = api();
        setStatus("Авторизация...");

        if (!a) {
            setStatus("API not ready...");
            return;
        }

        const username = (elName?.value || "").trim();
        const password = (elPass?.value || "");
        const bio = (elBio?.value || "");

        if (!username || !password) {
            setStatus("Введите username и пароль");
            return;
        }

        if (btnStart) {
            btnStart.disabled = true;
            btnStart.style.opacity = "0.85";
        }

        try {
            let res;
            if (authMode === "register") {
                if (!a.auth_register) {
                    setStatus("auth_register not implemented in API");
                    return;
                }
                res = await a.auth_register(username, password, bio);
            } else {
                if (!a.auth_login) {
                    setStatus("auth_login not implemented in API");
                    return;
                }
                res = await a.auth_login(username, password);
            }

            if (!res?.ok) {
                setStatus("Auth failed: " + (res?.error || "unknown"));
                return;
            }

            myName = (res?.user?.display_name) ? res.user.display_name : username;

            // init system chat
            ensureChat("system", "System");
            renderChatList();
            selectChat("system");

            elOverlay?.classList.add("hidden");
            setStatus("Connected");
            elMsg?.focus();
        } catch (e) {
            setStatus("Auth error: " + (e?.message || e));
        } finally {
            if (btnStart) {
                btnStart.disabled = false;
                btnStart.style.opacity = "";
            }
        }
    }

    btnStart?.addEventListener("click", submitAuth);

    [elName, elPass, elBio].forEach((el) => {
        if (!el) return;
        el.addEventListener("keydown", (e) => {
            if (e.key === "Enter") submitAuth();
        });
    });

    // ----------------------------
    // Sidebar: search + new chat
    // ----------------------------
    // ✅ FIX: plus button actually starts new chat (add interlocutor)
    btnNewChat?.addEventListener("click", () => {
        startNewChatFlow();
    });

    elChatSearch?.addEventListener("input", () => renderChatList());

    elChatSearch?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            openOrCreateDM(elChatSearch.value);
        }
    });

    // ----------------------------
    // Send
    // ----------------------------
    function autoResizeTextarea(el) {
        if (!el) return;
        el.style.height = "auto";
        el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }

    async function sendMessageFromUI(text) {
        const a = api();
        const msg = (text || "");
        if (!msg.trim()) return;

        // ✅ FIX: if we're still in system, try to resolve chat from search
        if (!currentChatId || currentChatId === "system") {
            const resolved = resolveChatForSend();
            if (!resolved) {
                setStatus("Выбери чат слева или введи @username в поиск (и нажми +)");
                return;
            }
        }

        const clientMsgId = genClientMsgId();
        pendingEcho.set(clientMsgId, currentChatId);

        // optimistic: сразу в историю/рендер
        addMessageToChat(currentChatId, {
            me: true,
            from: myName,
            text: msg.trim(),
            ts: nowTS(),
            clientMsgId,
            system: false,
            chatTitle: chatsById.get(currentChatId)?.title || currentChatId
        });

        renderChatList();
        renderMessages(currentChatId);

        if (!a?.send_message) {
            setStatus("Not connected (API)");
            pendingEcho.delete(clientMsgId);
            return;
        }

        // IMPORTANT: оставляем сигнатуру (text, clientMsgId) как у тебя
        const res = await a.send_message(msg.trim(), clientMsgId);
        if (res?.ok === false) {
            setStatus("Send failed: " + res.error);
            pendingEcho.delete(clientMsgId);
        }
    }

    btnSend?.addEventListener("click", async () => {
        const text = elMsg?.value || "";
        if (elMsg) elMsg.value = "";
        autoResizeTextarea(elMsg);
        await sendMessageFromUI(text);
        elMsg?.focus();
    });

    elMsg?.addEventListener("input", () => autoResizeTextarea(elMsg));
    elMsg?.addEventListener("keydown", async (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            const text = elMsg.value;
            elMsg.value = "";
            autoResizeTextarea(elMsg);
            await sendMessageFromUI(text);
        }
    });

    // ----------------------------
    // Init
    // ----------------------------
    setMode("login");
    setTimeout(() => elName?.focus(), 50);
    setTimeout(loadSavedCreds, 100);

    // Pre-create System chat so UI isn't empty
    ensureChat("system", "System");
    renderChatList();
    selectChat("system");
});
