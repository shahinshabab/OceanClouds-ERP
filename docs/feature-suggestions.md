# Feature suggestions and open follow-ups

Written after the October 2026 code review. Nothing here is built yet. Part 1
lists issues the review found but left alone because each needs a decision
from you. Part 2 is new features, ordered by how much they would help day to
day.

Effort: **S** about a day, **M** a few days, **L** a week or more.

---

## Part 1: Follow-ups that need a decision

| # | Issue | Why it matters | Suggested fix | Effort |
|---|-------|----------------|---------------|--------|
| 1 | **Scheduled jobs don't run in Docker.** `CRONJOBS` (django-crontab) only works with host cron, and the containers have none, so `generate_due_todos` never runs in production. | Nobody gets the "due today" or "overdue" to-dos. | Add a `scheduler` service to `compose.yaml` (like `session-cleanup`) that runs `generate_due_todos` once a day. The first run will create to-dos for everything already due, so check the count on the test server first. | S |
| 2 | **Uploaded files are public.** Nginx serves `/media/` to anyone, and contract files keep their original names. | Anyone who guesses a URL can download a signed contract or a ticket screenshot. | Serve media through a small login-checked Django view using `X-Accel-Redirect` and an `internal` Nginx location. On S3, keep the signed URLs the critical-fixes PR turns on. | S |
| 3 | **Production security settings fail open.** `SECRET_KEY` falls back to `"change-me"`, secure cookies and the SSL redirect default to off, and there is no HSTS. | One missing `.env` line means weak sessions. | Make the defaults follow `not DEBUG`, refuse to start with the default key when `DEBUG` is off, and add `SECURE_HSTS_SECONDS`. Compose already requires a key, so this only affects non-Docker runs. | S |
| 4 | **Invoices are never marked overdue,** and the sales report counts draft and cancelled invoices in its totals. | The "Overdue" count is always 0, and "Outstanding" is too high. | Work out "overdue" from `due_date` and the paid status, and leave draft and cancelled invoices out of the report totals. | S |
| 5 | **Seed services come back on every deploy.** `services/signals.py` re-creates "Wedding Photography" and the other seed services by name after each `migrate`. | A renamed or deleted seed service reappears with a new code. | Move the seed into a one-time data migration. | S |
| 6 | **Public signing link works on draft contracts.** The token is unguessable, but a draft link that was shared early can still be signed. | A client could sign terms that weren't final. | Allow signing only when the status is "Pending signature". Sending the contract by email already sets that status. | S |
| 7 | **Project Managers can open any deal, invoice or payment** by changing the ID in the URL, not just the ones linked to their projects. | It depends on whether PMs should see all the money. | If they shouldn't, limit `SalesReadOnlyAccessMixin` querysets to deals linked to the PM's projects. | S |
| 8 | **CRM Managers are missing from attendance.** `ATTENDANCE_ACCESS_ROLES` leaves them out. | Their logins get pending checkouts that they can't correct and admins can't see. | Add `ROLE_CRM_MANAGER` to the attendance roles and the employee list. | S |
| 9 | **Slow project pages.** The project list and kanban run about 13 queries per project, and the checklist list about 4 per row. | Pages get slower as projects pile up. | Annotate the progress counts and work time in `get_queryset`. | M |
| 10 | **Backups stay on the same server** (`deploy/backup.sh`). | If the Lightsail instance is lost, the backups go with it. | Copy each nightly dump to S3, or another machine, with a 30-day lifecycle. | S |
| 11 | **Login has no rate limit, and logout works over GET.** | Password guessing is unthrottled, and another website can log people out. | Use a small cache-based login throttle, and make logout POST-only. | S |
| 12 | **Email campaigns can't be sent.** Campaigns can be set to "scheduled" or "running", but no code sends them, and the WhatsApp helpers are never called. | The screens suggest a feature that doesn't exist. | Hide the campaign screens until sending is built (see feature C below). | S |

---

## Part 2: New features

### A. Payment schedule and reminders (high value, M)

The 10 / 30 / 60 split appears on proposals and contracts, but nothing tracks
the three instalments themselves.

- When a contract is signed, create one instalment record per split row
  (amount, due trigger, status). Read the percentages from the shared
  constants so a future change to the split carries through.
- Show "Advance paid · Event payment due · Delivery payment pending" on the
  deal and project pages.
- Send automatic reminder emails (and WhatsApp once it's live) a few days
  before the event and when the final delivery is marked done.
- Generate the instalment invoice in one click from the schedule row.

### B. Online payment links (high value, M)

Add a Razorpay (UPI / card) "Pay now" link to invoice emails and the public
contract page. A webhook records the `Payment` automatically with the
gateway reference, so staff don't have to type it in. Advance payments could
then confirm a booking without anyone stepping in.

### C. Client portal (high value, L)

Build one private link per client, using the same token idea as contract
signing, where the couple can:
- read the proposal and accept a plan
- sign the contract
- see their invoices and payments and pay online (B)
- see delivery status and download links for each deliverable

This replaces sending separate PDFs and answering "what's pending?" messages.

### D. Delivery hand-off and final invoice (M)

When every deliverable in a project is marked delivered, record the delivery
link (Drive, Pixieset and so on), email it to the client, and raise the
"On delivery" invoice automatically. The project can then move to
"Completed" with the review to-do.

### E. Crew scheduling and availability (M)

Assign photographers, videographers and freelancers to each event day, with
conflict warnings when someone is already booked that day. Add a crew
calendar view next to the existing event calendar, and give each crew member
a "my upcoming shoots" list.

### F. Project profitability (M)

Track expenses per project (travel, freelancer fees, albums, hard drives) and
show revenue minus expenses minus logged work hours (the work sessions
already record time) on the project page and in the sales report.

### G. GST-ready invoices (S–M)

Add your GSTIN, the client's GSTIN (optional), the SAC code for photography
services, and a CGST/SGST or IGST split by place of supply. This is only
needed if invoices have to be GST-compliant.

### H. Anniversary and follow-up messages (S)

The old anniversary command was removed because it used models that no longer
exist. Rebuild it on contacts (bride and groom, marketing allowed) and the
wedding event date, with a log table so each couple gets one message a year.
It can reuse `messaging.services.send_anniversary_email`.

### I. Audit trail for money changes (S)

Record who changed or deleted a payment, invoice total or contract status,
when they did it, and the old and new values, and show it on the invoice page.
This makes month-end questions easy to answer.

### J. Lead source and conversion report (S)

Inquiries already store their channel. Add a report showing, for each channel
(Instagram, referral, website and so on), inquiries → leads → deals →
signed contracts → revenue, so marketing spend can follow what converts.
