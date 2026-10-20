# Hosting and store operations

## Deploying this Flask app

The Render blueprint keeps `autoDeployTrigger: off`. Save code changes to GitHub when ready, then open the Render service's **Deploys** page and choose **Manual Deploy → Deploy latest commit**. A Git push by itself does not publish these changes. After deploy, open `/health`; it reports `ok` only when the app can reach its configured database.

## Confirm which database is live

The manager **System status** page shows whether the running service uses PostgreSQL or SQLite, and whether a database connection succeeds. On Render, set `DATABASE_URL` to the connection URL for the intended hosted PostgreSQL database. Do not put a database URL in GitHub or share it in screenshots.

The application automatically uses the URL in `DATABASE_URL`; without it, it uses SQLite. Pointing the app at a hosted database does not copy records from an existing SQLite file. Export/import or migrate the records before switching if they need to be preserved.

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

The earlier screenshots exposed email and application credentials. Revoke the exposed mail app password at the provider, create a new one, and replace `MAIL_PASSWORD` in Render. Replace `SECRET_KEY` with a newly generated random value too. Keep `DATABASE_URL` and `ADMIN_PANEL_PASSWORD` private. After changing Render environment values, manually deploy or rebuild the service so the running app receives them. A secret key change signs users out and invalidates existing password-reset links.

## Payments, delivery, cancellation, and returns

The checkout records the chosen payment preference. It does not connect to an automated Telebirr, CBE, Abay, or BOA payment API. For a transfer request, confirm stock and final price, then enter your verified payment details on the manager Orders page to email them to the customer. Check the incoming payment yourself before marking the order paid.

Telebirr development credentials can be supplied locally through a root `.env` file. Copy `.env.example` to `.env` and fill in the development merchant values issued by Telebirr. The app reads `TELEBIRR_APP_ID`, `TELEBIRR_APP_KEY`, `TELEBIRR_PUBLIC_KEY`, `TELEBIRR_SHORT_CODE`, `TELEBIRR_RECEIVE_NAME`, `TELEBIRR_NOTIFY_URL`, and `TELEBIRR_RETURN_URL` into its configuration. `.env` is git-ignored; never commit it or use production credentials for development. Credential loading alone does not activate automated checkout: the current checkout still records a manual transfer preference and does not call the Telebirr SDK.

The customer policy page asks customers to confirm delivery location, cost, timing, and applicable return/refund terms with the store before payment or work authorization. Replace that provisional wording with your exact business policy before treating it as a final legal policy.
