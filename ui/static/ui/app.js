// ui/static/ui/app.js: shared behaviour for the signed-in app shell.
(function () {
    "use strict";

    function getCookie(name) {
        const match = document.cookie.split(";").map((c) => c.trim()).find((c) => c.startsWith(name + "="));
        return match ? decodeURIComponent(match.substring(name.length + 1)) : null;
    }

    // ------------------------------------------------------------------
    // Top bar dropdowns (notifications, quick create, profile).
    // live_updates.js reads #notificationDropdown's d-none class, so these
    // panels toggle d-none instead of using Bootstrap's dropdown plugin.
    // ------------------------------------------------------------------
    function initDropdowns() {
        const pairs = [];
        document.querySelectorAll("[data-panel-toggle]").forEach((button) => {
            const panel = document.getElementById(button.dataset.panelToggle);
            if (panel) pairs.push([button, panel]);
        });

        function closeAll(except) {
            pairs.forEach(([button, panel]) => {
                if (panel === except) return;
                panel.classList.add("d-none");
                button.setAttribute("aria-expanded", "false");
            });
        }

        pairs.forEach(([button, panel]) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const opening = panel.classList.contains("d-none");
                closeAll(panel);
                panel.classList.toggle("d-none", !opening);
                button.setAttribute("aria-expanded", String(opening));
            });
            panel.addEventListener("click", (event) => event.stopPropagation());
        });

        document.addEventListener("click", () => closeAll());
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") closeAll();
        });
    }

    // ------------------------------------------------------------------
    // Sidebar: collapsible groups (remembered) and the "/" page finder.
    // ------------------------------------------------------------------
    function initSidebar() {
        const navigation = document.getElementById("sidebarNavigation");
        if (!navigation) return;

        const storageKey = "oc.sidebar.collapsed";
        let collapsed = [];
        try {
            collapsed = JSON.parse(localStorage.getItem(storageKey) || "[]");
        } catch (e) {
            collapsed = [];
        }

        const sections = Array.from(navigation.querySelectorAll(".nav-section"));

        function setCollapsed(section, value) {
            const toggle = section.querySelector(".nav-section-toggle");
            const list = section.querySelector(".nav");
            toggle.classList.toggle("collapsed", value);
            toggle.setAttribute("aria-expanded", String(!value));
            list.classList.toggle("d-none", value);
        }

        sections.forEach((section) => {
            const key = section.dataset.section;
            const isActive = section.classList.contains("has-active");
            if (collapsed.includes(key) && !isActive) setCollapsed(section, true);

            section.querySelector(".nav-section-toggle").addEventListener("click", () => {
                const nowCollapsed = !section.querySelector(".nav").classList.contains("d-none");
                setCollapsed(section, nowCollapsed);
                collapsed = collapsed.filter((k) => k !== key);
                if (nowCollapsed) collapsed.push(key);
                try {
                    localStorage.setItem(storageKey, JSON.stringify(collapsed));
                } catch (e) { /* storage unavailable */ }
            });
        });

        const body = document.querySelector("#sidebar .offcanvas-body");
        const active = navigation.querySelector(".nav-link.active");
        if (body && active) {
            const top = active.getBoundingClientRect().top - body.getBoundingClientRect().top;
            if (top > body.clientHeight - 80) body.scrollTop = top - body.clientHeight / 2;
        }

        const search = document.getElementById("sidebarSearch");
        if (!search) return;

        const empty = document.getElementById("sidebarEmpty");

        function filter() {
            const query = search.value.trim().toLowerCase();
            let anyVisible = false;
            sections.forEach((section) => {
                const list = section.querySelector(".nav");
                let sectionVisible = false;
                list.querySelectorAll(".nav-link").forEach((link) => {
                    const match = !query || link.textContent.toLowerCase().includes(query);
                    link.classList.toggle("d-none", !match);
                    sectionVisible = sectionVisible || match;
                });
                section.classList.toggle("d-none", !sectionVisible);
                if (query) {
                    list.classList.remove("d-none");
                } else {
                    list.classList.toggle("d-none", section.querySelector(".nav-section-toggle").classList.contains("collapsed"));
                }
                anyVisible = anyVisible || sectionVisible;
            });
            if (empty) empty.classList.toggle("d-none", anyVisible);
        }

        search.addEventListener("input", filter);
        search.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                const first = navigation.querySelector(".nav-link:not(.d-none)");
                if (first) window.location.href = first.href;
            }
            if (event.key === "Escape") {
                search.value = "";
                filter();
                search.blur();
            }
        });
        document.addEventListener("keydown", (event) => {
            const tag = (document.activeElement && document.activeElement.tagName) || "";
            if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey &&
                !["INPUT", "TEXTAREA", "SELECT"].includes(tag) && !document.activeElement.isContentEditable) {
                event.preventDefault();
                if (window.innerWidth < 992 && window.bootstrap) {
                    window.bootstrap.Offcanvas.getOrCreateInstance(document.getElementById("sidebar")).show();
                }
                search.focus();
            }
        });
    }

    // ------------------------------------------------------------------
    // Notifications: mark one as read.
    // ------------------------------------------------------------------
    function initNotifications() {
        document.addEventListener("click", (event) => {
            const button = event.target.closest(".js-mark-notification-read");
            if (!button) return;
            event.preventDefault();
            event.stopPropagation();

            const url = button.dataset.url;
            if (!url) return;

            button.disabled = true;
            fetch(url, {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
                credentials: "same-origin",
            })
                .then((response) => {
                    if (!response.ok) throw new Error("HTTP " + response.status);
                    return response.json();
                })
                .then((data) => {
                    if (!data.success) throw new Error("Mark read failed");
                    window.location.reload();
                })
                .catch((err) => {
                    console.error("Notification error:", err);
                    button.disabled = false;
                });
        }, true);
    }

    // ------------------------------------------------------------------
    // Rows with data-href open their record when clicked outside a link.
    // ------------------------------------------------------------------
    function initRowLinks() {
        document.addEventListener("click", (event) => {
            const row = event.target.closest("tr[data-href]");
            if (!row || event.target.closest("a, button, input, select, label, form")) return;
            if (event.metaKey || event.ctrlKey) {
                window.open(row.dataset.href, "_blank");
            } else {
                window.location.href = row.dataset.href;
            }
        });
    }

    // Bootstrap tooltips for anything marked data-bs-toggle="tooltip".
    function initTooltips() {
        if (!window.bootstrap) return;
        document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
            window.bootstrap.Tooltip.getOrCreateInstance(el);
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        initDropdowns();
        initSidebar();
        initNotifications();
        initRowLinks();
        initTooltips();
    });
})();
