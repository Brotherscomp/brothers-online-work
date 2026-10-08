import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


class MailConfigurationError(RuntimeError):
    pass


class MailDeliveryError(RuntimeError):
    pass


def send_email(subject, body, recipient, reply_to=None):
    server = current_app.config.get('MAIL_SERVER', '')
    sender = current_app.config.get('MAIL_DEFAULT_SENDER', '')
    port = current_app.config.get('MAIL_PORT', 587)
    use_tls = current_app.config.get('MAIL_USE_TLS', True)
    use_ssl = current_app.config.get('MAIL_USE_SSL', False)
    username = current_app.config.get('MAIL_USERNAME', '')
    password = current_app.config.get('MAIL_PASSWORD', '')

    if not server or not sender:
        raise MailConfigurationError('SMTP server and sender must be configured.')
    if use_tls and use_ssl:
        raise MailConfigurationError('Choose either SMTP TLS or SMTP SSL, not both.')
    if username and not password:
        raise MailConfigurationError('SMTP password is missing.')

    try:
        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = sender
        message['To'] = recipient
        if reply_to:
            message['Reply-To'] = reply_to
        message.set_content(body)
    except (TypeError, ValueError) as error:
        raise MailConfigurationError('The email sender or recipient settings are invalid.') from error

    try:
        context = ssl.create_default_context()
        if use_ssl:
            with smtplib.SMTP_SSL(server, port, timeout=15, context=context) as smtp:
                smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(server, port, timeout=15) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as error:
        raise MailDeliveryError('The email provider could not deliver the message.') from error