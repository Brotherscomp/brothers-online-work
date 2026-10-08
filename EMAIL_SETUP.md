# Email setup for the contact form

The contact form uses SMTP from the Flask server. It sends each submitted message to `CONTACT_RECIPIENT` and sends an acknowledgement to the client. SMTP credentials are read from environment variables and are not stored in the website source.

## Configure Windows

Add these user environment variables in Windows **Edit environment variables for your account**, then restart VS Code so the Flask process can read them:

| Variable | Example value |
| --- | --- |
| `MAIL_SERVER` | Your email provider's SMTP server (Gmail: `smtp.gmail.com`) |
| `MAIL_PORT` | `587` |
| `MAIL_USE_TLS` | `true` |
| `MAIL_USE_SSL` | `false` |
| `MAIL_USERNAME` | The mailbox used to send website email |
| `MAIL_PASSWORD` | An SMTP app password or provider-issued SMTP credential |
| `MAIL_DEFAULT_SENDER` | The same authorized sending address as `MAIL_USERNAME` |
| `CONTACT_RECIPIENT` | `yazezewkassa@gmail.com` |

Google lists `smtp.gmail.com` with TLS on port `587` for SMTP. Google app passwords require 2-Step Verification and are intended for apps that cannot use Sign in with Google; some accounts cannot use app passwords. Do not put your normal Google password in the app settings. See [Google SMTP settings](https://support.google.com/mail/answer/7104828) and [Google app password guidance](https://support.google.com/accounts/answer/185833). Your email provider may require different SMTP values.

Start the Flask app from VS Code after setting the variables. If SMTP is not configured or delivery fails, the form reports that and displays the shop phone number. The site does not store submitted messages in its database.