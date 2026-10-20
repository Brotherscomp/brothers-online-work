# Hosting and store operations

## Deploying this Flask app

The Render blueprint keeps `autoDeployTrigger: off`. Save code changes to GitHub when ready, then open the Render service's **Deploys** page and choose **Manual Deploy → Deploy latest commit**. A Git push by itself does not publish these changes. After deploy, open `/health`; it reports `ok` only when the app can reach its configured database.

The blueprint sets `APP_ENV=production`. Production startup now requires a `SECRET_KEY` with at least 32 characters, `DATABASE_URL`, `PUBLIC_BASE_URL` set to the site's public HTTPS origin, `SESSION_COOKIE_SECURE=true`, and an `ADMIN_PANEL_PASSWORD` with at least 20 characters. Configure these values in Render before deploying; the app will stop at startup with a configuration error if one is missing or too short. Password-reset links use `PUBLIC_BASE_URL`, so they do not depend on an untrusted request host. The app also applies request-size limits, security headers, and database-backed per-IP rate limits.

## Confirm which database is live

The manager **System status** page shows whether the running service uses PostgreSQL or SQLite, and whether a database connection succeeds. On Render, set `DATABASE_URL` to the connection URL for the intended hosted PostgreSQL database. Do not put a database URL in GitHub or share it in screenshots.

Production requires the PostgreSQL URL in `DATABASE_URL`. Local development uses SQLite when `DATABASE_URL` is unset. Pointing the app at a hosted database does not copy records from an existing SQLite file. Export/import or migrate the records before switching if they need to be preserved.

## Make and restore a PostgreSQL export

Install PostgreSQL command-line tools on a trusted computer. In PowerShell, after setting `DATABASE_URL` privately in the current shell, create a dated custom-format export:

```powershell
$backupFile = "brothers-online-work-$(Get-Date -Format yyyyMMdd-HHmm).dump"
pg_dump "$env:DATABASE_URL" --format=custom --file="$backupFile"
```

Keep the export somewhere separate from Render and Neon, with access limited to you. To practice a restore without changing production, first create a separate empty PostgreSQL database and put its URL in `RESTORE_DATABASE_URL`, then run:

```powershell
pg_restore --no-owner --dbname="$env:RESTORE_DATABASE_URL" "$backupFile"
```

Check the restored tables and records in that separate database. Do not restore over production as a test. Neon also provides branch and point-in-time recovery features; confirm the current retention available to your account in the Neon console before relying on it.

## Rotate exposed secrets

The earlier screenshots and the local `.env.example` exposed application credentials. Revoke any exposed mail app password and payment credentials at their providers, create replacements, and update Render. Replace `SECRET_KEY` with a newly generated random value too. Keep `DATABASE_URL` and `ADMIN_PANEL_PASSWORD` private. The checked-in `.env.example` contains placeholders only; put local values in the ignored `.env` file. After changing Render environment values, manually deploy or rebuild the service so the running app receives them. A secret key change signs users out and invalidates existing password-reset links.

## Payments, delivery, cancellation, and returns

The checkout records the chosen payment preference. It does not connect to an automated Telebirr, CBE, Abay, or BOA payment API. For a transfer request, confirm stock and final price, then enter your verified payment details on the manager Orders page to email them to the customer. Check the incoming payment yourself before marking the order paid.

The current checkout is manual. It records the order request and preferred transfer method, then sends instructions; it does not call a payment provider or verify payment callbacks. The unused Telebirr helper and environment settings do not enable automated checkout. Do not describe an order as paid until the incoming transfer has been checked. Before adding an online gateway, implement server-side signature verification, order/amount checks, and idempotent callback handling.

The customer policy page asks customers to confirm delivery location, cost, timing, and applicable return/refund terms with the store before payment or work authorization. Replace that provisional wording with your exact business policy before treating it as a final legal policy.
