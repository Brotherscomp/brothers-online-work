import hashlib
import re
import secrets
import time
from hmac import compare_digest
from urllib.parse import urljoin

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .emailing import MailConfigurationError, MailDeliveryError, send_email
from .models import (
    consume_email_verification_token, consume_password_reset_token,
    create_email_verification_token, create_password_reset_token, create_user,
    delete_email_verification_token, delete_password_reset_token,
    email_verification_token_is_valid, find_user_by_email, get_customer_orders,
    is_integrity_error, password_reset_token_is_valid,
)
from .security import enforce_rate_limit, is_safe_local_redirect
from .translations import translate

auth = Blueprint('auth', __name__)
_EMAIL_LOCAL_PART = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+\Z")
_EMAIL_DOMAIN_LABEL = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z')


def auth_csrf_token():
    token = session.get('auth_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['auth_csrf_token'] = token
    return token


def valid_auth_csrf_token():
    expected = session.get('auth_csrf_token', '')
    supplied = request.form.get('csrf_token', '')
    return bool(expected and supplied and compare_digest(expected, supplied))


def _normalize_email(value):
    value = (value or '').strip()
    if not value or len(value) > 254 or value.count('@') != 1:
        return None
    local_part, domain = value.rsplit('@', 1)
    if (not local_part or len(local_part) > 64 or local_part.startswith('.')
            or local_part.endswith('.') or '..' in local_part
            or not _EMAIL_LOCAL_PART.fullmatch(local_part)):
        return None
    try:
        domain = domain.encode('idna').decode('ascii').lower()
    except UnicodeError:
        return None
    labels = domain.split('.')
    if (len(labels) < 2 or len(domain) > 253
            or any(not _EMAIL_DOMAIN_LABEL.fullmatch(label) for label in labels)
            or not re.fullmatch(r'(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})', labels[-1])):
        return None
    return f'{local_part.lower()}@{domain}'


def _external_url(endpoint, **values):
    path = url_for(endpoint, **values)
    public_base_url = current_app.config.get('PUBLIC_BASE_URL')
    if public_base_url:
        return urljoin(public_base_url + '/', path.lstrip('/'))
    return url_for(endpoint, _external=True, **values)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if not valid_auth_csrf_token():
            flash(translate('Your sign-in session expired. Refresh the page and try again.'), 'error')
            return render_template('auth/login.html', form_email=request.form.get('email', '').strip())
        enforce_rate_limit('customer-login', 10, 900)
        email = _normalize_email(request.form.get('email', ''))
        password = request.form.get('password', '')
        if not email:
            flash(translate('Enter a valid email address.'), 'error')
        else:
            user = find_user_by_email(email) if password and len(password) <= 1024 else None
            if user is None or not check_password_hash(user['password_hash'], password):
                flash(translate('Email or password is incorrect.'), 'error')
            elif not user['email_verified']:
                flash(translate('Confirm your email address before signing in.'), 'error')
                return redirect(url_for('auth.verify_email_resend'))
            else:
                language = session.get('language', 'en')
                cart = session.get('cart', {})
                session.clear()
                session['language'] = language
                if cart:
                    session['cart'] = cart
                session['user_id'] = user['id']
                session['first_name'] = user['first_name']
                session['email'] = user['email']
                session['session_version'] = user['session_version']
                session.permanent = True
                flash(translate('Login successful.'), 'success')
                destination = request.args.get('next', '')
                if is_safe_local_redirect(destination):
                    return redirect(destination)
                return redirect(url_for('views.home'))
    return render_template('auth/login.html', form_email=request.form.get('email', '').strip())


@auth.route('/logout', methods=['GET', 'POST'])
def logout():
    if request.method == 'POST':
        if not valid_auth_csrf_token():
            abort(400)
        language = session.get('language', 'en')
        session.clear()
        session['language'] = language
        flash(translate('You have been logged out.'), 'success')
        return redirect(url_for('views.home'))
    if not session.get('user_id'):
        return redirect(url_for('views.home'))
    return render_template('auth/logout.html')


@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        if not valid_auth_csrf_token():
            flash(translate('Your sign-up session expired. Refresh the page and try again.'), 'error')
            return render_template('auth/sign_up.html')
        enforce_rate_limit('customer-sign-up', 5, 3600)
        email = _normalize_email(request.form.get('email', ''))
        first_name = ' '.join(request.form.get('first_name', '').split())
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not email:
            flash(translate('Enter a valid email address.'), 'error')
        elif not first_name or len(first_name) > 120 or not password:
            flash(translate('Please complete all fields.'), 'error')
        elif password != confirm_password:
            flash(translate('Passwords do not match.'), 'error')
        elif len(password) < 12 or len(password) > 1024:
            flash(translate('Password must be between 12 and 1024 characters.'), 'error')
        elif find_user_by_email(email):
            flash(translate('An account with that email already exists.'), 'error')
        else:
            try:
                user_id = create_user(email, first_name, generate_password_hash(password))
            except Exception as error:
                if not is_integrity_error(error):
                    raise
                flash(translate('An account with that email already exists.'), 'error')
            else:
                token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
                create_email_verification_token(user_id, token_hash, int(time.time()) + 86400)
                verification_url = _external_url('auth.verify_email', token=token)
                message = '\n'.join([
                    f'Hello {first_name},', '',
                    'Confirm this email address to activate your Brothers-Online-Work account. This link expires in 24 hours.',
                    verification_url, '',
                    'If you did not create this account, you can ignore this message.',
                ])
                try:
                    send_email('Confirm your Brothers-Online-Work account', message, email,
                               reply_to=current_app.config.get('CONTACT_RECIPIENT'))
                except (MailConfigurationError, MailDeliveryError):
                    delete_email_verification_token(token_hash)
                    current_app.logger.exception('A customer email verification message could not be delivered.')
                    flash(translate('Your account is saved but not active yet. We could not send the confirmation. Try sending it again.'), 'error')
                    session['pending_verification_email'] = email
                    return redirect(url_for('auth.verify_email_resend'))
                flash(translate('Check your email for a link to confirm your account.'), 'success')
                return redirect(url_for('auth.login'))
    return render_template(
        'auth/sign_up.html',
        form_email=request.form.get('email', '').strip(),
        form_first_name=request.form.get('first_name', '').strip(),
    )


@auth.route('/verify-email/<token>', methods=['GET', 'POST'])
def verify_email(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    if not email_verification_token_is_valid(token_hash, int(time.time())):
        flash(translate('That email confirmation link is invalid or expired. Request a new one.'), 'error')
        return redirect(url_for('auth.verify_email_resend'))
    if request.method == 'POST':
        if not valid_auth_csrf_token():
            flash(translate('Your confirmation session expired. Open the email link again and retry.'), 'error')
            return render_template('auth/verify_email.html', token=token)
        if not consume_email_verification_token(token_hash, int(time.time())):
            flash(translate('That email confirmation link is invalid or expired. Request a new one.'), 'error')
            return redirect(url_for('auth.verify_email_resend'))
        flash(translate('Your email is confirmed. You can now sign in.'), 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/verify_email.html', token=token)


@auth.route('/verify-email', methods=['GET', 'POST'])
def verify_email_resend():
    if request.method == 'POST':
        if not valid_auth_csrf_token():
            flash(translate('Your request session expired. Refresh the page and try again.'), 'error')
            return render_template('auth/verify_email_resend.html')
        enforce_rate_limit('email-verification-resend', 5, 3600)
        email = _normalize_email(request.form.get('email', ''))
        if not email:
            flash(translate('Enter a valid email address.'), 'error')
            return render_template('auth/verify_email_resend.html', form_email=request.form.get('email', '').strip())
        session['pending_verification_email'] = email
        user = find_user_by_email(email)
        delivery_failed = False
        if user and not user['email_verified']:
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
            create_email_verification_token(user['id'], token_hash, int(time.time()) + 86400)
            verify_url = _external_url('auth.verify_email', token=token)
            body = '\n'.join([
                f"Hello {user['first_name']},", '',
                'Confirm this email address to activate your account. This link expires in 24 hours.',
                verify_url,
            ])
            try:
                send_email('Confirm your Brothers-Online-Work account', body, email,
                           reply_to=current_app.config.get('CONTACT_RECIPIENT'))
            except (MailConfigurationError, MailDeliveryError):
                delete_email_verification_token(token_hash)
                current_app.logger.exception('A customer email verification message could not be delivered.')
                delivery_failed = True
        if delivery_failed:
            flash(translate('The confirmation email could not be delivered. Check the email service settings or try again later. You can also call 0909847775.'), 'error')
        else:
            flash(translate('If the address has an unconfirmed account, a confirmation link will be sent.'), 'success')
            session.pop('pending_verification_email', None)
        return redirect(url_for('auth.verify_email_resend'))
    return render_template(
        'auth/verify_email_resend.html',
        form_email=session.pop('pending_verification_email', ''),
    )


@auth.route('/password-reset', methods=['GET', 'POST'])
def password_reset_request():
    if request.method == 'POST':
        if not valid_auth_csrf_token():
            flash(translate('Your request session expired. Refresh the page and try again.'), 'error')
            return render_template('auth/password_reset_request.html')
        enforce_rate_limit('password-reset-request', 5, 3600)
        email = _normalize_email(request.form.get('email', ''))
        if not email:
            flash(translate('Enter a valid email address.'), 'error')
            return render_template('auth/password_reset_request.html', form_email=request.form.get('email', '').strip())
        user = find_user_by_email(email)
        if user:
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
            create_password_reset_token(user['id'], token_hash, int(time.time()) + 3600)
            reset_url = _external_url('auth.reset_password', token=token)
            body = '\n'.join([
                f"Hello {user['first_name']},", '',
                'Use the link below to choose a new password. It expires in one hour and can be used once.',
                reset_url, '', 'If you did not request this, you can ignore this message.', '',
                'Brothers-Online-Work',
            ])
            try:
                send_email('Reset your Brothers-Online-Work password', body, email,
                           reply_to=current_app.config.get('CONTACT_RECIPIENT'))
            except (MailConfigurationError, MailDeliveryError):
                delete_password_reset_token(token_hash)
                current_app.logger.exception('A customer password reset email could not be sent.')
        flash(translate('If an account uses that email, a password reset link will be sent.'), 'success')
        return redirect(url_for('auth.password_reset_request'))
    return render_template('auth/password_reset_request.html')


@auth.route('/password-reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    if not password_reset_token_is_valid(token_hash, int(time.time())):
        flash(translate('That password reset link is invalid or expired. Request a new one.'), 'error')
        return redirect(url_for('auth.password_reset_request'))
    if request.method == 'POST':
        if not valid_auth_csrf_token():
            flash(translate('Your password reset session expired. Refresh the page and try again.'), 'error')
            return render_template('auth/password_reset.html')
        password = request.form.get('password', '')
        confirmation = request.form.get('confirm_password', '')
        if len(password) < 12 or len(password) > 1024:
            flash(translate('Password must be between 12 and 1024 characters.'), 'error')
        elif password != confirmation:
            flash(translate('Passwords do not match.'), 'error')
        elif not consume_password_reset_token(token_hash, generate_password_hash(password), int(time.time())):
            flash(translate('That password reset link is invalid or expired. Request a new one.'), 'error')
            return redirect(url_for('auth.password_reset_request'))
        else:
            session.pop('user_id', None)
            session.pop('first_name', None)
            session.pop('email', None)
            session.pop('session_version', None)
            flash(translate('Your password has been updated. You can now log in.'), 'success')
            return redirect(url_for('auth.login'))
    return render_template('auth/password_reset.html')


@auth.route('/orders')
def orders():
    user_id = session.get('user_id')
    if not user_id:
        flash(translate('Log in to see your orders.'), 'error')
        return redirect(url_for('auth.login', next=url_for('auth.orders')))
    customer_orders, order_items = get_customer_orders(user_id)
    return render_template('auth/orders.html', orders=customer_orders, order_items=order_items)
