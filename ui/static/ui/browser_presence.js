(() => {
    "use strict";

    const config = document.currentScript.dataset;
    const interval = Number(config.intervalMs) || 60000;
    const storageKey = config.storageKey;
    let localLastSent = 0;
    let lastInteraction = 0;
    let stopped = false;

    // Only a person using the page counts as activity. An open, unattended
    // tab sends nothing, so the server can sign it out as idle and record the
    // last real activity as the logout time.
    function interacted() {
        lastInteraction = Date.now();
    }
    ["pointerdown", "pointermove", "keydown", "wheel", "scroll", "touchstart"].forEach(name => {
        window.addEventListener(name, interacted, {passive: true, capture: true});
    });

    function lastSent() {
        try {
            return Number(window.localStorage.getItem(storageKey)) || localLastSent;
        } catch (_) {
            return localLastSent;
        }
    }

    function rememberSent(now) {
        localLastSent = now;
        try {
            window.localStorage.setItem(storageKey, String(now));
        } catch (_) {
            // Storage can be disabled; the server also throttles timestamp writes.
        }
    }

    function csrfToken() {
        const prefix = `${config.csrfCookieName}=`;
        const cookie = document.cookie.split(";").map(value => value.trim())
            .find(value => value.startsWith(prefix));
        return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : config.csrfToken;
    }

    async function send(beacon) {
        if (stopped || navigator.onLine === false) return;
        const now = Date.now();
        const previous = lastSent();
        // Ignore future stamps if the device clock changed. No client timestamp
        // is trusted by the server; these stamps only coordinate local tabs.
        if (previous <= now && now - previous < interval) return;
        // Nothing done here since the last heartbeat from any tab.
        if (!lastInteraction || (previous <= now && lastInteraction <= previous)) return;

        rememberSent(now);
        const body = new FormData();
        body.append("csrfmiddlewaretoken", csrfToken());
        if (beacon && navigator.sendBeacon) {
            try {
                if (navigator.sendBeacon(config.heartbeatUrl, body)) return;
            } catch (_) {
                // Fall back to a keepalive fetch if beacon cannot queue the data.
            }
        }
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 10000);
        try {
            const response = await fetch(config.heartbeatUrl, {
                method: "POST",
                body,
                credentials: "same-origin",
                cache: "no-store",
                redirect: "error",
                keepalive: true,
                signal: controller.signal,
            });
            if (response.status === 401 || response.status === 403) {
                stopped = true;
                window.clearInterval(timer);
            }
            if (response.status === 401 && config.loginUrl) {
                let reason = "";
                try { reason = (await response.json()).reason || ""; } catch (_) { /* no body */ }
                const here = window.location.pathname + window.location.search;
                const query = new URLSearchParams({next: here, ended: reason});
                window.location.assign(`${config.loginUrl}?${query}`);
            }
        } catch (_) {
            // Offline/closing tabs are expected. Retry on the next minute.
        } finally {
            window.clearTimeout(timeout);
        }
    }

    async function heartbeat(beacon = false) {
        if (stopped) return;
        if (navigator.locks) {
            try {
                await navigator.locks.request(storageKey, {ifAvailable: true}, lock => {
                    if (lock) return send(beacon);
                });
                return;
            } catch (_) {
                // Older/restricted browsers still coordinate through storage.
            }
        }
        await send(beacon);
    }

    // Check locally every 15 seconds so another tab can take over when one
    // closes. Shared storage/locks limit network requests to one per minute.
    const timer = window.setInterval(() => heartbeat(), interval / 4);
    window.addEventListener("pageshow", () => heartbeat());
    window.addEventListener("online", () => heartbeat());
    window.addEventListener("pagehide", () => heartbeat(true));
    document.addEventListener("visibilitychange", () => {
        // Coming back to a tab is activity; leaving it sends any pending beat.
        if (document.visibilityState === "visible") interacted();
        heartbeat(document.visibilityState === "hidden");
    });
    heartbeat();
})();
