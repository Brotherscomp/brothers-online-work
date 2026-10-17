# Production operations

This guide is for the original Flask application deployed on Render. Render deployments are intentionally manual (`autoDeployTrigger: off` in `render.yaml`).

## Confirm the live database

Sign in at `/manager`, then open **System status**. The database should show **PostgreSQL**, **Connected**, and the hosted database URL as **Configured**. A response of `{"status":"ok"}` from `/health` confirms that the app can query its configured database. Never copy the database URL into a public issue, screenshot, or Git commit.

If the page says SQLite, the service is using local storage. On Render, configure `DATABASE_URL` with the Neon PostgreSQL connection string in the service's private environment settings. Save the setting and use **Manual Deploy**. The app creates or updates its schema at startup, but this does not copy rows from an old SQLite database into Neon; transfer existing data separately before switching customers to the new database.

## Back up and restore PostgreSQL

Run these from Git Bash on a trusted computer with PostgreSQL client tools installed. Set `DATABASE_URL` only in your private terminal session; do not paste its value into chat or commit it.

Create a compressed logical backup:

```bash
pg_dump --format=custom --file="brothers-online-work-$(date +%F).dump" "$DATABASE_URL"
```

Restore into a separate, empty PostgreSQL database first, so you can check the result without overwriting the live database:

```bash
pg_restore --no-owner --dbname="$RESTORE_DATABASE_URL" "brothers-online-work-YYYY-MM-DD.dump"
```

Replace the filename with the backup you made and set `RESTORE_DATABASE_URL` privately to the empty restore database. Inspect the restored site before considering any recovery complete. Keep backup files somewhere private and make backups regularly; `/health` checks connectivity but does not create backups.

## Email and manager access

Open `/manager/system` to check whether SMTP settings are present and send one test email. If the message fails, inspect the Render service logs for the provider response. The status page never displays passwords or connection strings.

Because a previous screenshot exposed an email app password and the app secret, replace both values in Render before launch:

- Revoke the old email app password with its email provider, create a replacement, and save it as `MAIL_PASSWORD`.
- Generate a new random `SECRET_KEY` and save it in Render. Keep `REQUIRE_SECRET_KEY=true`.
- Confirm `ADMIN_PANEL_PASSWORD` is set to a strong private value.
- Save the variables, then manually deploy the service.

Changing `SECRET_KEY` signs existing browsers out. Do not share any of these values in screenshots or source files.

## Orders and transfer payments

Customers can choose cash at pickup, cash on delivery, Telebirr, CBE, Abay Bank, or BOA. Bank and mobile wallet methods are manual transfer preferences: this app does not connect to payment provider APIs and does not take money online. Confirm availability, final amount, delivery or pickup details, and cancellation/refund terms before asking a customer to pay. In the manager **Orders** page, enter the correct transfer instructions for that individual order and use **Save and email details**. Mark an order **Paid** only after you verify receipt outside the app.

## Customer policies

The public policy page explains that delivery options, fees, timing, cancellations, and refunds are confirmed for each order. Replace the interim wording in `website/templates/policies.html` with your actual business rules before launch; no exact delivery or refund terms were supplied for this implementation.
