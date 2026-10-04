const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {test} = require("node:test");
const vm = require("node:vm");

const source = readFileSync(join(__dirname, "../static/ui/browser_presence.js"), "utf8");
const settle = () => new Promise(resolve => setImmediate(resolve));

function browser(options = {}) {
    const clock = {now: 1000000};
    const storage = new Map();
    const heldLocks = new Set();
    const locks = {
        async request(name, settings, callback) {
            assert.equal(settings.ifAvailable, true);
            if (heldLocks.has(name)) return callback(null);
            heldLocks.add(name);
            try { return await callback({name}); }
            finally { heldLocks.delete(name); }
        },
    };
    function tab() {
        const events = {};
        const requests = [];
        const beacons = [];
        const timeouts = new Map();
        let tick;
        let intervalCleared = false;
        let nextTimeout = 0;
        const document = {
            currentScript: {dataset: {
                intervalMs: "60000",
                storageKey: "presence-user-1",
                heartbeatUrl: "/common/session/heartbeat/",
                csrfToken: "masked-csrf-token",
                csrfCookieName: "csrftoken",
                loginUrl: "/login/",
            }},
            cookie: "csrftoken=initial-csrf-token",
            visibilityState: "visible",
            addEventListener(name, callback) { events[name] = callback; },
        };
        const navigator = {
            onLine: options.online !== false,
            locks: options.locks === false ? undefined : locks,
            sendBeacon(url, body) {
                beacons.push({url, body});
                return options.beaconAccepted !== false;
            },
        };
        const window = {
            assigned: null,
            location: {
                pathname: "/projects/",
                search: "?page=2",
                assign(url) { window.assigned = url; },
            },
            localStorage: {
                getItem(key) {
                    if (options.storageBlocked) throw new Error("Storage blocked");
                    return storage.get(key) || null;
                },
                setItem(key, value) {
                    if (options.storageBlocked) throw new Error("Storage blocked");
                    storage.set(key, value);
                },
            },
            addEventListener(name, callback) { events[name] = callback; },
            setInterval(callback, ms) {
                assert.equal(ms, 15000);
                tick = callback;
                return 1;
            },
            clearInterval() { intervalCleared = true; },
            setTimeout(callback, ms) {
                assert.equal(ms, 10000);
                timeouts.set(++nextTimeout, callback);
                return nextTimeout;
            },
            clearTimeout(id) { timeouts.delete(id); },
        };
        vm.runInNewContext(source, {
            document, window, navigator, FormData, AbortController, URLSearchParams,
            Date: {now: () => clock.now},
            fetch: async (url, request) => {
                requests.push({url, ...request});
                if (options.hang) {
                    await new Promise((_, reject) => request.signal.addEventListener("abort", () => reject(new Error("Timeout"))));
                }
                if (options.networkFailure) throw new Error("Network offline");
                return {
                    status: options.status || 204,
                    json: async () => ({error: "Session ended", reason: options.reason || ""}),
                };
            },
        });
        return {
            document, navigator, requests, beacons,
            tick: () => tick(),
            event: async name => { await events[name](); await settle(); },
            // Someone using this tab, then the next 15-second check.
            use: async () => { events.keydown(); await tick(); await settle(); },
            assigned: () => window.assigned,
            expireRequest: () => [...timeouts.values()].forEach(callback => callback()),
            isStopped: () => intervalCleared,
        };
    }
    return {clock, tab, storage};
}

test("an open tab nobody uses sends no heartbeat", async () => {
    const app = browser();
    const tab = app.tab();
    await settle();
    for (let i = 0; i < 8; i++) {
        app.clock.now += 15000;
        await tab.tick();
    }
    await tab.event("pageshow");
    app.clock.now += 60000;
    await tab.event("pagehide");
    assert.equal(tab.requests.length, 0);
    assert.equal(tab.beacons.length, 0);
});

test("two tabs share one heartbeat each minute and the remaining tab takes over", async () => {
    const app = browser();
    const first = app.tab();
    const second = app.tab();
    await settle();
    await first.use();
    assert.equal(first.requests.length + second.requests.length, 1);
    app.clock.now += 59000;
    await first.use();
    await second.use();
    assert.equal(first.requests.length + second.requests.length, 1);
    app.clock.now += 1000;
    await second.tick();
    assert.equal(second.requests.length, 1);
    app.clock.now += 60000;
    // Nobody used either tab since the last heartbeat.
    await Promise.all([first.tick(), second.tick()]);
    assert.equal(first.requests.length + second.requests.length, 2);
    await first.use();
    await second.use();
    assert.equal(first.requests.length + second.requests.length, 3);
});

test("storage fallback coordinates tabs without Web Locks", async () => {
    const app = browser({locks: false});
    const first = app.tab();
    const second = app.tab();
    await settle();
    await first.use();
    await second.use();
    assert.equal(first.requests.length + second.requests.length, 1);
    app.clock.now += 60000;
    await first.use();
    await second.use();
    assert.equal(first.requests.length + second.requests.length, 2);
});

test("returning to a tab counts as activity", async () => {
    const app = browser();
    const tab = app.tab();
    await settle();
    tab.document.visibilityState = "visible";
    await tab.event("visibilitychange");
    assert.equal(tab.requests.length, 1);
});

test("hidden/closing pages send a throttled beacon and never request logout", async () => {
    const app = browser();
    const tab = app.tab();
    await settle();
    await tab.use();
    tab.document.visibilityState = "hidden";
    await tab.event("visibilitychange");
    assert.equal(tab.beacons.length, 0);
    app.clock.now += 60000;
    await tab.event("pagehide");
    assert.equal(tab.beacons.length, 0);
    await tab.event("keydown");
    await tab.event("pagehide");
    assert.equal(tab.beacons.length, 1);
    assert.equal(tab.beacons[0].url, "/common/session/heartbeat/");
    assert.equal(tab.beacons[0].body.get("csrfmiddlewaretoken"), "initial-csrf-token");
    assert.equal(tab.isStopped(), false);
    await tab.event("pageshow");
    assert.equal(tab.requests.length, 1);
});

test("failed beacon queue falls back to authenticated keepalive fetch", async () => {
    const app = browser({beaconAccepted: false});
    const tab = app.tab();
    await settle();
    await tab.use();
    app.clock.now += 60000;
    await tab.event("keydown");
    await tab.event("pagehide");
    assert.equal(tab.requests.length, 2);
    assert.equal(tab.requests[1].keepalive, true);
    assert.equal(tab.requests[1].credentials, "same-origin");
    assert.equal(tab.requests[1].method, "POST");
});

test("requests use the current CSRF cookie after token rotation", async () => {
    const app = browser();
    const tab = app.tab();
    await settle();
    await tab.use();
    app.clock.now += 60000;
    tab.document.cookie = "other=value; csrftoken=rotated-token";
    await tab.use();
    assert.equal(tab.requests[1].body.get("csrfmiddlewaretoken"), "rotated-token");
    app.clock.now += 60000;
    tab.document.cookie = "";
    await tab.use();
    assert.equal(tab.requests[2].body.get("csrfmiddlewaretoken"), "masked-csrf-token");
});

test("an ended login sends the page to sign-in with the reason", async () => {
    const app = browser({status: 401, reason: "idle_timeout"});
    const tab = app.tab();
    await settle();
    await tab.use();
    assert.equal(tab.isStopped(), true);
    assert.equal(tab.assigned(), "/login/?next=%2Fprojects%2F%3Fpage%3D2&ended=idle_timeout");
});

for (const status of [401, 403]) {
    test(`heartbeat stops after authentication/CSRF rejection ${status}`, async () => {
        const app = browser({status});
        const tab = app.tab();
        await settle();
        await tab.use();
        assert.equal(tab.isStopped(), true);
        app.clock.now += 120000;
        await tab.event("keydown");
        await tab.tick();
        await tab.event("pageshow");
        assert.equal(tab.requests.length, 1);
    });
}

test("network failure retries at the next minute without flooding", async () => {
    const app = browser({networkFailure: true});
    const tab = app.tab();
    await settle();
    await tab.use();
    app.clock.now += 15000;
    await tab.use();
    assert.equal(tab.requests.length, 1);
    app.clock.now += 45000;
    await tab.tick();
    assert.equal(tab.requests.length, 2);
    assert.equal(tab.isStopped(), false);
});

test("offline devices resume on the online event", async () => {
    const app = browser({online: false});
    const tab = app.tab();
    await settle();
    await tab.use();
    assert.equal(tab.requests.length, 0);
    tab.navigator.onLine = true;
    await tab.event("online");
    assert.equal(tab.requests.length, 1);
});

test("blocked storage retains per-tab throttling", async () => {
    const app = browser({storageBlocked: true});
    const tab = app.tab();
    await settle();
    await tab.use();
    await tab.use();
    assert.equal(tab.requests.length, 1);
    app.clock.now += 60000;
    await tab.use();
    assert.equal(tab.requests.length, 2);
});

test("a timed-out request releases its cross-tab lock", async () => {
    const app = browser({hang: true});
    const first = app.tab();
    const second = app.tab();
    await settle();
    first.use();
    await settle();
    first.expireRequest();
    await settle();
    app.clock.now += 60000;
    // Do not await the intentionally hung second request.
    second.use();
    await settle();
    assert.equal(second.requests.length, 1);
    second.expireRequest();
    await settle();
});
