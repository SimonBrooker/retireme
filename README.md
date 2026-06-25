# retireme

A self-hosted retirement / net-worth tracker. Single-user, password protected, runs as one Docker container with a SQLite file for storage.

## Features

- **First-run setup wizard** — on first launch you create a password, then enter your date of birth (or just your current age), target retirement age, and withdrawal rate, then add your accounts and any expected inheritance.
- **Age stays current on its own** — give it your date of birth instead of a static age and it recalculates automatically on every visit, so you never have to remember to bump it up each year. Already set up with a manual age? Nothing changes unless you add a date of birth later in Settings.
- **Custom accounts** — add as many as you like: cash savings, ISA, SIPP, workplace pension (DC), defined benefit pension, general investment account, property equity, or other. Each has its own growth rate, annual contribution, and a setting for whether contributions stop at retirement.
- **"Show inflated figures" toggle** (Dashboard and Kids) — everything in the app is in today's money by default, on the assumption you've already discounted your entered growth rates for inflation (most people have, even if only in the back of their mind). This toggle is the opposite operation: it adds your Settings inflation estimate back on top, as a pure display lens — not saved, doesn't touch any growth/projection maths — so you can sanity-check what the actual nominal £ figure on a future statement might say. Deliberately scoped to retirement and Kids accounts only; property is always shown in today's money, since its growth rate isn't necessarily discounted for inflation the same way yours is, and "Total net worth" is recomputed as inflated-retirement + unchanged-property rather than naively scaled as one number.
- **Kids** — a separate page for tracking children's Junior ISAs and Junior SIPPs. Add a child (name + date of birth), then add their JISA/JSIPP from the Accounts page and assign it to them. These accounts are kept completely out of your own net worth and retirement figures — not just excluded from the withdrawal calc the way property is, but excluded everywhere, since it isn't your money. The Kids page plots a projected-value-by-age chart, one coloured line per child, with a marker at their 18th birthday, using each account's own growth/contribution figures.
- **Actual-balance history** — once you know what really happened (the market beat or missed your assumed growth rate), log the real balance for an account at a given age on the History page. It overrides the projection for that age and becomes the new anchor every later year compounds from — you can also backfill genuinely historical ages from before you started using the app.
- **Retirement assets kept separate from total net worth** — each account has a "counts as a retirement asset" toggle. Untick it for things like property: it still counts toward your total net worth, but is excluded from the withdrawal-rate figure, so your home doesn't quietly inflate your retirement income number. Picking "Property equity" as the type suggests unticking this automatically (you can still override it).
- **Inheritance modelling** — add expected inheritance by source, the age you expect to receive it, the gross amount, and your share (e.g. 50% if split with a sibling). You can route it into a specific account or leave it as unallocated cash.
- **Compounding projection engine** — projects every account forward year by year (growth + contribution, contribution compounding optionally too) out to whatever age you choose.
- **Graphs** — net worth by account over time (hover any point to see that year's growth and contribution, or whether it's an actual recorded figure), and annual withdrawal capacity against an optional target retirement income. Dashed markers show "today", your target retirement age, and — if you've set a target income — the age you're first projected to reach it.
- **Growth rate scenarios** — a chart comparing your retirement assets (never property) under flat hypothetical growth rates of 3/5/7/9/12%, plus a line using each account's own configured rate, all with the same contributions throughout. Useful for seeing how sensitive your plan actually is to the growth assumption.
- **Theme follows you everywhere, including the login screen** — change it in Settings and it's reflected immediately, even before you log back in.
- **Year-by-year ledger table** — the full age-by-age breakdown, including any backfilled history, similar to a spreadsheet model.
- **Four themes** — two dark, two light — pick one from Settings → Appearance.
- **Currency picker** — choose GBP, USD, EUR, CAD, or AUD at setup (or change it any time from Settings). Updates the symbol everywhere instantly; doesn't convert any figures.
- **Export, import, and reset** — Settings → Data management. Export everything (accounts, history, inheritance entries, assumptions — not your password) to a JSON file; import one to restore/replace your data; or wipe everything back to a blank slate without losing your login.
- **Optional two-factor authentication** — Settings → Two-factor authentication. Scan a QR code into any standard authenticator app (Google Authenticator, Authy, 1Password, etc.) and your password alone is no longer enough to log in. Entirely optional.
- **Account recovery that can't lock you out** — forgot your password, or lost the device your authenticator app was on? `docker exec` into the container and run `flask reset-password` — see [Account recovery](#account-recovery) below. No email, no SMTP setup, no support tickets.
- **Hashed passwords** — passwords are never stored in plain text. Hashing uses Werkzeug's `generate_password_hash` (PBKDF2-SHA256, salted).

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env and set a real SECRET_KEY (any long random string)

docker compose up -d --build
```

Then open `http://localhost:5000` and follow the setup wizard.

Your data lives in `./data/retirement.db` on the host (mounted as a volume), so it survives container rebuilds. Back that file up like you would any other sensitive personal file.

## Upgrading an existing install

If you already have this running with data in it: just rebuild and restart (`docker compose up -d --build`). The app checks its own database schema on startup and adds any new columns/tables it needs automatically — your accounts, inheritance entries, and history are never wiped or reset by an upgrade.

## Account recovery

This is a single-user app with no email/SMTP setup, so password reset works differently than you might be used to: **server access is the recovery mechanism.** If you can `docker exec` into the container, you can always get back in — that's the same level of access you already need to deploy this app in the first place, and the same level of access that already lets you read the raw SQLite file directly if you really wanted to.

```bash
docker exec -it <container_name> flask reset-password
```

This prompts you for a new password (hidden input, typed twice to confirm) and sets it directly — no need to know the old one. If two-factor authentication is enabled, it gets cleared too, since if you're locked out you may have lost your authenticator device as well as your password. You can re-enable 2FA from Settings after logging back in.

Don't know your container's name? `docker ps` will show it.

This is also why optional 2FA (Settings → Two-factor authentication) is just that — *optional, additional* security, not a replacement for the password. There's deliberately no self-service "forgot password" web flow gated behind a recovery code or backup codes you'd have to remember to save somewhere: for a single-user self-hosted tool, the CLI command above is simpler, has no setup step, and can never lock you out the way a lost recovery code could.

## Security

This has been hardened against the OWASP Top 10, with the app-level pieces below already in place. **If you're exposing this to the internet** (e.g. nginx reverse proxy + Cloudflare), the deployment-level steps after that matter just as much — the app can't protect itself from a misconfigured edge.

**What's implemented in the app:**

- **CSRF protection** on every form (signed per-session token, checked on every POST/PUT/PATCH/DELETE)
- **Security headers** on every response: Content-Security-Policy (no `unsafe-inline` for scripts), X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, and HSTS when served over HTTPS
- **No inline JavaScript** anywhere — this also closed a real injection issue: account/child/inheritance names were previously interpolated into inline `onsubmit="confirm('...')"` handlers, and a name containing `');` could break out of the JS string and execute arbitrary script (HTML-escaping doesn't protect against this — the browser decodes entities before handing inline-handler content to the JS engine). Everything now uses `data-confirm`/`data-auto-submit` attributes read by an external script instead, which can't be escaped out of this way
- **Rate limiting** on login, MFA verification, and MFA setup (10 attempts/minute/IP) — there was no brute-force protection on these before
- **Security event logging** to stdout (`docker logs`) — login successes/failures, MFA changes, password changes, data export/import/full-reset
- **Secure cookie flags** — `HttpOnly` always, `SameSite=Lax` always, `Secure` when `SECURE_COOKIES=true` (see below)
- **`ProxyFix`** middleware so the app correctly recognizes HTTPS/client IP when sitting behind nginx
- **Upload size cap** (5 MB) on the data-import endpoint
- A startup warning if `SECRET_KEY` is still the built-in default

**What you need to do if exposing this to the internet:**

1. **Set `SECRET_KEY`** to a real random value (see [Quick start](#quick-start-docker)) — never run with the default outside your own LAN.
2. **Set `SECURE_COOKIES=true`** once you have real HTTPS in front of this. Leave it `false` for plain-HTTP LAN use — a `Secure` cookie is silently dropped by the browser over HTTP and you won't be able to log in.
3. **Use Cloudflare in "Full (Strict)" SSL mode, not "Flexible."** Flexible mode only encrypts visitor→Cloudflare; the Cloudflare→origin leg stays plain HTTP, so anyone who can see traffic between Cloudflare and your server (e.g. on the same network/host) sees it unencrypted regardless of the padlock in the visitor's browser. Nginx Proxy Manager can issue a free Let's Encrypt cert for the origin so Full (Strict) works properly.
4. **Restrict your origin firewall to Cloudflare's IP ranges** (published at [cloudflare.com/ips](https://www.cloudflare.com/ips/)) on whatever ports nginx listens on. Without this, anyone who discovers your real origin IP (and there are ways to find it) can hit your server directly and skip Cloudflare's proxying, rate limiting, and WAF entirely — the orange cloud only protects you if it's the *only* path in.
5. **Turn on Nginx Proxy Manager's "Block Common Exploits."**
6. **Consider a Cloudflare WAF rate-limiting rule** on `/login` and `/login/verify` as a second layer in front of the app's own rate limiting — the app's limiter is per-process and IP-based, which is reasonable for one person but is no substitute for edge-level protection against a real attacker.
7. **Keep 2FA on** if this is reachable from the open internet — it's optional for a reason, but the reason to actually turn it on goes up a lot once this isn't just sitting on your LAN.

**What's accepted as out of scope, deliberately:**

- The SQLite file itself is not encrypted at rest. Anyone with filesystem access to the host can read it directly (the password field inside is hashed; everything else isn't). This is consistent with the single-user, self-hosted threat model — if someone has that level of server access, the database file is already the least of your problems.
- Security event logs go to stdout only — there's no persistent, rotated log file or alerting. Fine for a personal app you'd notice being down; not a substitute for real monitoring if that matters to you.
- No CAPTCHA or device fingerprinting on login — rate limiting was judged sufficient for a single-account app; revisit if you ever make this multi-user.

## Running without Docker (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Visits `http://localhost:5000`. In dev mode the database defaults to `/data/retirement.db` — change `DATABASE_PATH` in `.env` if you'd rather it sit inside the project folder, e.g. `DATABASE_PATH=./data/retirement.db`.

## Project layout

```
app/
  __init__.py        # app factory, first-run / setup-complete redirects, schema auto-migration
  models.py           # User, Profile, Account, Snapshot, Inheritance, Child
  projections.py      # pure-Python compounding engine (no Flask deps — easy to unit test)
  data_io.py           # export/import field mapping + validation (also framework-light)
  routes/
    auth.py            # create-account (first run only), login, logout
    setup.py            # onboarding wizard: profile -> accounts -> inheritance
    dashboard.py        # main view + /api/projection JSON for the charts
    accounts.py          # ongoing account CRUD
    inheritances.py       # ongoing inheritance CRUD
    history.py             # record actual balances that override the projection
    kids.py                 # children + their JISA/JSIPP accounts, kept out of the main figures
    settings.py               # assumptions, password, theme, export/import/reset
  templates/, static/    # server-rendered Jinja2 + vanilla CSS/JS, Chart.js via CDN
run.py
Dockerfile / docker-compose.yml
```

It's deliberately a single Flask app with server-rendered pages rather than a separate frontend build — simplest possible thing to keep running long-term in one container.

## How the projection works

For each account, each year: `balance = balance × (1 + growth_rate) + contribution` (contribution stops at retirement if you've ticked that option, and contributions can themselves grow year-on-year if you set a contribution growth rate — handy if you expect contributions to rise with salary or inflation).

If you've recorded an actual balance for an account at a given age (via History), that figure replaces the computed one for that age, and every subsequent year compounds forward from it instead of from the original assumption. Ages before your current age with no recorded snapshot simply aren't shown — there's no way to compute history backwards, only to record it.

Inheritance is added in the year you specify, at `gross_amount × share_percent`. If you don't assign it to an account it's tracked as unallocated cash and shown as its own line on the chart.

Each account has a "counts as a retirement asset" flag. **Total net worth** sums every account. **Retirement assets** (and the withdrawal capacity calculated from it: `retirement assets × withdrawal rate`) only sums accounts with that flag ticked — untick it for property/home equity so it doesn't inflate the income figure you're actually planning to live on.

## Notes / things you might want to change

- **Single user by default.** The data model already scopes everything by `user_id`, so multi-user support mostly just needs a normal sign-up flow instead of the current "only one account can ever be created" guard in `auth.py` — but for a personal tracker, one password is usually all you want.
- **Charts use a CDN.** `dashboard.html` loads Chart.js from jsDelivr. If you're running this somewhere with no outbound internet access, download `chart.umd.min.js` yourself into `app/static/js/` and change the `<script>` tag in `dashboard.html` to point at it.
- **No currency setting yet** — everything assumes £. Easy to add a `currency` field to `Profile` and swap the `£` literals in templates/JS for it if you need other currencies.
- **No currency conversion** — the currency picker (Settings → Currency) only changes which symbol is shown; it doesn't convert or rescale any of your existing figures. If you switch from GBP to USD, a balance of 50,000 just becomes $50,000 — re-enter figures yourself if you actually mean a different amount of money.
- **Backups**: Settings → Data management → Export gives you a portable JSON snapshot of everything except your password — do this periodically and keep the file somewhere safe. The underlying SQLite file (`data/retirement.db`) is the full source of truth (including your password hash) if you want a complete file-level backup instead.
- **Import replaces, it doesn't merge.** Importing a file deletes all current accounts/history/inheritance entries first, then recreates them from the file. Inheritance-to-account links are matched by account *name* — if you renamed an account between export and import, that link will be left unallocated (you'll get a warning naming which one).
