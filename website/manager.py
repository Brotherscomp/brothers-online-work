from decimal import Decimal, InvalidOperation
from functools import wraps
from hmac import compare_digest
import secrets

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

from .emailing import MailConfigurationError, MailDeliveryError, send_email
from .models import (
    get_device_request,
    get_device_requests,
    mark_device_request_response_sent,
    save_device_request_response,
)
from .translations import translate


manager = Blueprint('manager', __name__)
REQUEST_STATUSES = (
    'Received',
    'In review',
    'Quote sent',
    'Work in progress',
    'Ready for pickup',
    'Completed',
    'Unable to help',
)


def csrf_token():
    token = session.get('manager_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['manager_csrf_token'] = token
    return token


def valid_csrf_token():
    expected = session.get('manager_csrf_token', '')
    supplied = request.form.get('csrf_token', '')
    return bool(expected and supplied and compare_digest(expected, supplied))


def manager_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('manager_authenticated'):
            return redirect(url_for('manager.login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


@manager.route('/', methods=['GET', 'POST'])
def login():
    password_is_configured = bool(current_app.config.get('ADMIN_PANEL_PASSWORD'))
    if session.get('manager_authenticated'):
        return redirect(url_for('manager.requests'))

    if request.method == 'POST':
        configured_password = current_app.config.get('ADMIN_PANEL_PASSWORD', '')
        supplied_password = request.form.get('password', '')
        if not valid_csrf_token():
            abort(400)
        if configured_password and compare_digest(supplied_password, configured_password):
            session['manager_authenticated'] = True
            destination = request.args.get('next', '')
            if destination.startswith('/manager/') and not destination.startswith('//'):
                return redirect(destination)
            return redirect(url_for('manager.requests'))
        flash(
            translate('Manager access is not configured yet.')
            if not configured_password
            else translate('The manager password is incorrect.'),
            'error',
        )

    return render_template(
        'manager/login.html',
        password_is_configured=password_is_configured,
    )


@manager.route('/requests')
@manager_required
def requests():
    return render_template(
        'manager/requests.html',
        device_requests=get_device_requests(),
        request_statuses=REQUEST_STATUSES,
    )


@manager.route('/requests/<int:request_id>/feedback', methods=['POST'])
@manager_required
def send_feedback(request_id):
    if not valid_csrf_token():
        abort(400)
    device_request = get_device_request(request_id)
    if device_request is None:
        abort(404)

    status = request.form.get('status', '').strip()
    feedback = request.form.get('feedback', '').strip()
    quote_text = request.form.get('quote_etb', '').strip().replace(',', '')
    quote_cents = None

    if status not in REQUEST_STATUSES or len(feedback) > 5000:
        flash(translate('Please review the status and feedback, then try again.'), 'error')
        return redirect(url_for('manager.requests') + f'#request-{request_id}')
    if quote_text:
        try:
            if len(quote_text) > 25:
                raise InvalidOperation
            quote = Decimal(quote_text)
            if not quote.is_finite() or quote <= 0 or quote > Decimal('100000000'):
                raise InvalidOperation
            quote_cents = int((quote * 100).quantize(Decimal('1')))
        except InvalidOperation:
            flash(translate('Enter a valid price in ETB or leave the price blank.'), 'error')
            return redirect(url_for('manager.requests') + f'#request-{request_id}')
    if not feedback and quote_cents is None:
        flash(translate('Add feedback or an estimated price before sending.'), 'error')
        return redirect(url_for('manager.requests') + f'#request-{request_id}')

    save_device_request_response(request_id, status, quote_cents, feedback)

    language = device_request['language']
    lines = [
        f"{translate('Hello', language)} {device_request['customer_name']},",
        '',
        translate('Here is our update on your device request.', language),
        f"{translate('Request number:', language)} {request_id}",
        f"{translate('Status', language)}: {translate(status, language)}",
    ]
    if quote_cents is not None:
        lines.extend([
            f"{translate('Estimated price', language)}: ETB {quote_cents / 100:,.2f}",
            translate('The final price may change after inspection or availability confirmation.', language),
        ])
    if feedback:
        lines.extend(['', translate('Our feedback', language) + ':', feedback])
    lines.extend([
        '',
        translate('Reply to this email or contact us if you have questions.', language),
        'Brothers-Online-Work',
        'Yazezee Kassa',
        '0909847775',
        current_app.config['CONTACT_RECIPIENT'],
    ])

    try:
        send_email(
            translate('Update on your device request | Brothers-Online-Work', language),
            '\n'.join(lines),
            device_request['email'],
            reply_to=current_app.config['CONTACT_RECIPIENT'],
        )
    except MailConfigurationError:
        current_app.logger.error('Manager feedback was saved, but SMTP is not configured.')
        flash(translate('Feedback was saved, but email is not configured. Set up SMTP and send it again.'), 'error')
    except MailDeliveryError:
        current_app.logger.exception('Manager feedback was saved, but its email could not be delivered.')
        flash(translate('Feedback was saved, but the email could not be delivered. Please try sending it again.'), 'error')
    else:
        mark_device_request_response_sent(request_id)
        flash(translate('Feedback was emailed to the customer.'), 'success')

    return redirect(url_for('manager.requests') + f'#request-{request_id}')


@manager.route('/logout', methods=['POST'])
@manager_required
def logout():
    if not valid_csrf_token():
        abort(400)
    session.pop('manager_authenticated', None)
    flash(translate('You have been logged out of the manager page.'), 'success')
    return redirect(url_for('manager.login'))
