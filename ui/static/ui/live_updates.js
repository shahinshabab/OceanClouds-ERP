(() => {
    "use strict";

    // Pages opt in with {% block live_topics %} on <body data-live-topics>:
    //   "inquiry"          any inquiry change     "inquiry:5"  only inquiry 5
    //   "task"             any visible task       "task:7"     only task 7
    //   "task-project:3"   tasks of project 3
    //   "todo" / "todo:4"  to-dos                 "notification" the bell list
    const config = document.currentScript.dataset;
    const topics = new Set((document.body.dataset.liveTopics || "").split(/\s+/).filter(Boolean));

    const CLOSE_SESSION_ENDED = 4401;
    const IDLE_MS = 4000;
    const RELOAD_DELAY_MS = 1500;

    let socket = null;
    let retryMs = 1000;
    let connectedBefore = false;
    let stopped = false;
    let reloadPending = false;
    let reloadTimer = null;
    let lastInteraction = 0;
    let formEdited = false;

    // ------------------------------------------------------------------
    // Page refresh without losing someone's work
    // ------------------------------------------------------------------

    ["pointerdown", "keydown", "wheel", "touchstart"].forEach((name) => {
        document.addEventListener(name, () => { lastInteraction = Date.now(); }, { passive: true, capture: true });
    });
    document.addEventListener("input", (e) => {
        if (e.target.closest("form")) formEdited = true;
    }, true);

    function isBusy() {
        const active = document.activeElement;
        if (active && active.matches("input, textarea, select, [contenteditable='true']")) return true;
        if (formEdited) return true;
        if (document.querySelector(".modal.show")) return true;
        const bell = document.getElementById("notificationDropdown");
        if (bell && !bell.classList.contains("d-none")) return true;
        return false;
    }

    function showBanner(text) {
        const banner = document.getElementById("liveUpdateBanner");
        if (!banner) return;
        banner.querySelector(".js-live-banner-text").textContent = text;
        banner.classList.remove("d-none");
    }

    function requestReload(text) {
        reloadPending = true;
        if (reloadTimer) return;
        reloadTimer = window.setTimeout(function tryReload() {
            reloadTimer = null;
            if (!reloadPending) return;
            if (document.hidden) return; // retried on visibilitychange
            if (isBusy()) {
                showBanner(text);
                return;
            }
            if (Date.now() - lastInteraction < IDLE_MS) {
                reloadTimer = window.setTimeout(tryReload, IDLE_MS);
                return;
            }
            window.location.reload();
        }, RELOAD_DELAY_MS);
    }

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && reloadPending) requestReload("This page has updates.");
    });

    document.addEventListener("click", (e) => {
        if (e.target.closest(".js-live-refresh")) window.location.reload();
    });

    // ------------------------------------------------------------------
    // Toasts and the notification bell
    // ------------------------------------------------------------------

    function toast(text, href) {
        const container = document.getElementById("liveToastContainer");
        if (!container || !window.bootstrap) return;

        const el = document.createElement("div");
        el.className = "toast align-items-center text-bg-dark border-0";
        el.setAttribute("role", "status");
        el.innerHTML =
            '<div class="d-flex"><div class="toast-body"><i class="bi bi-bell me-2"></i><span></span>' +
            '<a class="link-light ms-2 d-none">Open</a></div>' +
            '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
        el.querySelector("span").textContent = text;
        if (href) {
            const link = el.querySelector("a");
            link.href = href;
            link.classList.remove("d-none");
        }
        container.appendChild(el);
        el.addEventListener("hidden.bs.toast", () => el.remove());
        new window.bootstrap.Toast(el, { delay: 8000 }).show();
    }

    async function refreshBell() {
        try {
            const response = await fetch(config.panelUrl, {
                credentials: "same-origin",
                headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" },
                cache: "no-store",
            });
            const type = response.headers.get("Content-Type") || "";
            if (!response.ok || !type.includes("application/json")) return;
            const data = await response.json();

            const badge = document.getElementById("notificationBadge");
            if (badge) {
                badge.textContent = data.count;
                badge.classList.toggle("d-none", !data.count);
            }
            const dropdown = document.getElementById("notificationDropdown");
            if (dropdown) dropdown.innerHTML = data.html;
        } catch (_) {
            // The next push or page load will catch up.
        }
    }

    // ------------------------------------------------------------------
    // Events
    // ------------------------------------------------------------------

    function pageWants(kind, payload) {
        if (topics.has(kind) || topics.has(`${kind}:${payload.id}`)) return true;
        return kind === "task" && topics.has(`task-project:${payload.project_id}`);
    }

    const NOUNS = { inquiry: "enquiry", task: "task", todo: "to-do" };

    function handle(payload) {
        const kind = payload.kind;

        if (kind === "notification") {
            refreshBell();
            if (payload.action === "created") toast(payload.message, config.notificationsUrl);
            if (topics.has("notification")) requestReload("You have new notifications.");
            return;
        }

        const noun = NOUNS[kind];
        if (!noun) return;

        const wanted = pageWants(kind, payload);

        if (kind === "inquiry" && payload.action === "created" && !wanted) {
            const href = config.inquiryUrlTemplate.replace(/\/0\/$/, `/${payload.id}/`);
            toast(`New enquiry from ${payload.channel}: ${payload.label}`, href);
        }

        if (wanted) {
            const verb = payload.action === "created" ? "added" : payload.action;
            requestReload(`A ${noun} was ${verb}.`);
        }
    }

    // ------------------------------------------------------------------
    // Socket with reconnect
    // ------------------------------------------------------------------

    function connect() {
        if (stopped) return;
        const scheme = window.location.protocol === "https:" ? "wss" : "ws";
        socket = new WebSocket(`${scheme}://${window.location.host}${config.socketPath}`);

        socket.addEventListener("open", () => {
            retryMs = 1000;
            // Anything pushed while we were offline: catch up on the bell.
            if (connectedBefore) refreshBell();
            connectedBefore = true;
        });

        socket.addEventListener("message", (e) => {
            try {
                handle(JSON.parse(e.data));
            } catch (_) {
                // Ignore malformed messages.
            }
        });

        socket.addEventListener("close", (e) => {
            if (e.code === CLOSE_SESSION_ENDED) {
                stopped = true;
                return;
            }
            const wait = retryMs + Math.random() * 1000;
            retryMs = Math.min(retryMs * 2, 30000);
            window.setTimeout(connect, wait);
        });
    }

    window.addEventListener("pagehide", () => {
        stopped = true;
        if (socket) socket.close();
    });
    window.addEventListener("pageshow", (e) => {
        if (e.persisted) {
            stopped = false;
            connect();
        }
    });

    connect();
})();
