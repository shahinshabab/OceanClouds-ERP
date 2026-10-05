# Docker deployment

The stack contains Django/Gunicorn (ASGI with Uvicorn workers), PostgreSQL,
Redis, and Nginx. PostgreSQL data,
uploaded media, and collected static files are stored in named Docker volumes.

## Configure

Copy `.env.example` to `.env` and replace both placeholder secrets. Generate a
Django secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

For production, keep `DJANGO_DEBUG=False`, use the public hostname in
`DJANGO_ALLOWED_HOSTS`, and include its full HTTPS origin in
`DJANGO_CSRF_TRUSTED_ORIGINS`.

## Start

```bash
docker compose config
docker compose build
docker compose up -d
docker compose ps
curl http://127.0.0.1:8080/healthz
```

The web entrypoint waits for the healthy PostgreSQL dependency through Compose,
runs Django migrations, collects static files, and starts Gunicorn. Container
Nginx listens only on `127.0.0.1:8080` by default so the server's TLS-enabled
host Nginx can proxy to it without a port conflict.

Example host Nginx proxy target:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

For the test server, `deploy/test.oceanclouds.in.nginx.conf` is the HTTP host
configuration used before Certbot adds the HTTPS listener and redirect.
The production equivalent is `deploy/oceanclouds.in.nginx.conf`; issue its
certificate only after both production DNS names resolve to the main server.

## Persistent data

- `oceanclouds-erp_postgres_data`: PostgreSQL data
- `oceanclouds-erp_media_data`: user uploads
- `oceanclouds-erp_static_data`: collected Django static files

Do not use `docker compose down --volumes` in production; it removes the named
data volumes. Back up PostgreSQL with `pg_dump` and back up the media volume
before upgrades.

## Live updates

Pages get pushes over one websocket per tab at `/ws/live/` (Django Channels,
with Redis carrying messages between Gunicorn workers):

- Notifications: the bell badge and dropdown refresh and a toast appears.
- Inquiries: a new inquiry shows a toast everywhere; the inquiry list and
  detail pages refresh themselves.
- Tasks and to-dos: list, kanban, detail, and project pages refresh when a
  task or to-do the user can see changes.

Pages refresh only when the user is idle. If they are typing in a form or have
a dialog open, a "Refresh" banner appears instead. Pushes carry ids and short
labels only and go to the same people the views already allow (admins, the
project manager, assignees, owners); data still loads through normal views.
Saves never fail because of Redis: pushes are sent after commit and errors are
only logged. Sockets close on logout, when a newer login replaces the session,
and at the fixed 12-hour deadline. They do not count as presence activity.

The host Nginx must pass websocket upgrades. Both files in `deploy/` include a
`location /ws/` block; after Certbot has added the HTTPS server block, copy the
same `location /ws/` block into the `listen 443` server as well, then
`sudo nginx -t && sudo systemctl reload nginx`.

Redis is capped at 64 MB with no persistence (`compose.yaml`); restarting it
only drops in-flight pushes, and browsers reconnect on their own.

## Login, logout and idle sign-out

Every login and logout is a `UserLoginSession` row. A login ends one of four ways:

| End reason | When | Logout time recorded | Attendance |
| --- | --- | --- | --- |
| Manual Logout | the user clicks Logout | the click | counted |
| Idle Logout (Last Activity) | only if `LOGIN_IDLE_TIMEOUT_MINUTES` is set (off by default): no activity for that long | the last activity | counted |
| Fixed Session Expired | active right up to the 12-hour limit | the 12-hour limit | needs an approved checkout |
| Replaced by New Login | the user signs in elsewhere | the new login | needs an approved checkout |

Activity means someone using the app: clicking a link, submitting a form,
typing a URL, or clicking, typing, scrolling or moving the mouse on an open
page (sent as a heartbeat, below). An open tab nobody touches, automatic page
reloads from live updates, background fetches and the websocket itself are not
activity. Idle sign-out is off by default, so a forgotten logout stays open
until the 12-hour limit and then needs an approved checkout. With idle sign-out
turned on, it instead ends as an idle logout at the last real activity.

The `session-cleanup` service runs `close_expired_login_sessions` every minute;
requests and heartbeats also close an ended login straight away. Closing a login
deletes its Django session, pauses active work at the logout time, and tells
open tabs over the websocket, which then go to the sign-in page with the reason.
Set `LOGIN_IDLE_TIMEOUT_MINUTES` in `.env` to a number of minutes to turn idle
sign-out on; leave it at `0` (the default) to keep only the 12-hour limit.

## Browser presence

Authenticated application and Django admin pages send a CSRF-protected POST to
`/common/session/heartbeat/` about once per minute while someone is using them,
and nothing while they sit unattended. Tabs share a timestamp in
local storage and use Web Locks where available to avoid duplicate requests.
If storage is unavailable, each tab may send its own heartbeat, but the endpoint
still limits timestamp updates to once per minute for the current login.

Presence reuses `UserLoginSession.last_activity_at`; there is no new table,
migration, or per-heartbeat history. `BROWSER_HEARTBEAT_INTERVAL_SECONDS` is 60
and `BROWSER_OFFLINE_THRESHOLD_SECONDS` is 180 in `core/settings.py`.
Attendance & Leave shows presence as of page load; refresh to see updates.
Offline since is calculated as last seen plus the three-minute grace period.
It is an estimate: browser suspension, computer sleep, or network loss can also
stop heartbeats. It is not an exact browser-close or attendance checkout time.

Heartbeats never extend the fixed 12-hour authentication deadline, acknowledge
notices, or mark checkout. A heartbeat for a login that is idle or past its
deadline ends that login and returns 401 with the end reason. Heartbeat
requests skip the per-request global expiry scan and notice query, while still
checking authentication, CSRF, the current login key, and its expiry deadline.
Standard server access logs may include these requests; existing Docker log
rotation still limits their size. Collect static files when deploying.

Local validation with a dedicated test database and integrations disabled:

```text
python manage.py test common ui projects reports --verbosity 1
node --test ui/tests_js/browser_presence.test.cjs
python manage.py check
python manage.py makemigrations --check --dry-run
```
