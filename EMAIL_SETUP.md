# Email setup and manager responses

The contact form and device quote/repair forms use SMTP from the Flask server. New device requests are saved in the app's SQLite database, emailed to yazezewkassa@gmail.com, and acknowledged to the customer. The manager page can send a price estimate, repair feedback, and status update to the customer's email.

The manager page is at /manager. Set ADMIN_PANEL_PASSWORD to a strong, private password in the app environment before using it. Without this value the manager page stays locked. Do not put the password in the website source or commit it to GitHub.

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

Start or restart the Flask app after setting the variables. Add these values in a hosting provider's private environment-variable or secrets settings and redeploy. If SMTP is not configured or delivery fails, a device request is still saved and appears in the manager page; a failed customer response remains saved so you can send it again after fixing SMTP. The regular contact form continues to email messages directly.
