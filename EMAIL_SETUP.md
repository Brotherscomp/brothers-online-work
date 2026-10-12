# Email setup and manager responses

The contact form, account confirmation and recovery, order confirmations, and device quote/repair responses use SMTP from the Flask server. New accounts must confirm their address before signing in. Requests are saved in the configured database before email is attempted. The manager area can send estimates, repair feedback, and verified transfer instructions to customers.

The manager page is at `/manager`. After signing in, use **System status** to check whether the database and SMTP settings are available and to send a test email. Set `ADMIN_PANEL_PASSWORD` to a strong, private password in the app environment before using it. Without this value the manager page stays locked. Do not put the password in the website source or commit it to GitHub.

The contact form uses SMTP from the Flask server. It sends each submitted message to `CONTACT_RECIPIENT` and sends an acknowledgement to the client. SMTP credentials are read from environment variables and are not stored in the website source.

## Configure Windows

Add these user environment variables in Windows **Edit environment variables for your account**, then restart VS Code so the Flask process can read them:

| Variable | Example value |
| --- | --- |
| ADMIN_PANEL_PASSWORD | A long, private manager password |
| `MAIL_SERVER` | Your email provider's SMTP server (Gmail: `smtp.gmail.com`) |
| `MAIL_PORT` | `587` |
| `MAIL_USE_TLS` | `true` |
| `MAIL_USE_SSL` | `false` |
| `MAIL_USERNAME` | The mailbox used to send website email |
| `MAIL_PASSWORD` | An SMTP app password or provider-issued SMTP credential |
| `MAIL_DEFAULT_SENDER` | The same authorized sending address as `MAIL_USERNAME` |
| `CONTACT_RECIPIENT` | `yazezewkassa@gmail.com` |

Google lists `smtp.gmail.com` with TLS on port `587` for SMTP. Google app passwords require 2-Step Verification and are intended for apps that cannot use Sign in with Google; some accounts cannot use app passwords. Do not put your normal Google password in the app settings. See [Google SMTP settings](https://support.google.com/mail/answer/7104828) and [Google app password guidance](https://support.google.com/accounts/answer/185833). Your email provider may require different SMTP values.

For Render, add these values in the service's private environment settings and choose **Save, rebuild, and deploy**. Automatic deploys remain disabled in `render.yaml`; pushing to GitHub does not publish the changes. If SMTP is unavailable, an order or device request is still saved. Read the on-screen status and check Render service logs before retrying.

The password visible in the earlier screenshot must be revoked and replaced with a new provider app password. Also replace the app's `SECRET_KEY` in Render with a newly generated secret. Never reuse the values shown in the screenshot.
