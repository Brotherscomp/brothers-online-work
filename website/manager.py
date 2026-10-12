from decimal import Decimal, InvalidOperation
from functools import wraps
from hmac import compare_digest
import secrets

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

from .emailing import MailConfigurationError, MailDeliveryError, send_email
from .models import (
    ORDER_PAYMENT_STATUSES,
    ORDER_STATUSES,
    get_admin_customers,
    get_admin_order,
    get_admin_orders,
    get_admin_product,
    get_admin_products,
    get_device_request,
    get_device_requests,
    get_db_connection,
    get_manager_dashboard_data,
    mark_device_request_response_sent,
    save_admin_product,
    save_order_payment_instructions,
    save_device_request_response,
    set_admin_product_active,
    update_order_payment_status,
    update_order_status,
)
from .payments import TRANSFER_PAYMENT_METHODS, payment_method_label
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
    password_is_configured = bool(
        current_app.config.get('ADMIN_PANEL_PASSWORD'))
    if session.get('manager_authenticated'):
        return redirect(url_for('manager.dashboard'))

    if request.method == 'POST':
        configured_password = current_app.config.get(
            'ADMIN_PANEL_PASSWORD', '')
        supplied_password = request.form.get('password', '')
        if not valid_csrf_token():
            abort(400)
        if configured_password and compare_digest(supplied_password, configured_password):
            session['manager_authenticated'] = True
            session.permanent = True
            destination = request.args.get('next', '')
            if destination.startswith('/manager/') and not destination.startswith('//'):
                return redirect(destination)
            return redirect(url_for('manager.dashboard'))
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
            flash(
                translate('Enter a valid price in ETB or leave the price blank.'), 'error')
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
            translate(
                'The final price may change after inspection or availability confirmation.', language),
        ])
    if feedback:
        lines.extend(['', translate('Our feedback', language) + ':', feedback])
    lines.extend([
        '',
        translate(
            'Reply to this email or contact us if you have questions.', language),
        'Brothers-Online-Work',
        'Yazezee Kassa',
        '0909847775',
        current_app.config['CONTACT_RECIPIENT'],
    ])

    try:
        send_email(
            translate(
                'Update on your device request | Brothers-Online-Work', language),
            '\n'.join(lines),
            device_request['email'],
            reply_to=current_app.config['CONTACT_RECIPIENT'],
        )
    except MailConfigurationError:
        current_app.logger.error(
            'Manager feedback was saved, but SMTP is not configured.')
        flash(translate(
            'Feedback was saved, but email is not configured. Set up SMTP and send it again.'), 'error')
    except MailDeliveryError:
        current_app.logger.exception(
            'Manager feedback was saved, but its email could not be delivered.')
        flash(translate(
            'Feedback was saved, but the email could not be delivered. Please try sending it again.'), 'error')
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


@manager.route('/dashboard')
@manager_required
def dashboard():
    selected_period = request.args.get('period', '7d')
    data = get_manager_dashboard_data(selected_period)
    from datetime import date, timedelta

    rows = {row['period_key']: row for row in data['sales_rows']}
    today = date.today()
    if data['period_unit'] == 'day':
        start = today - timedelta(days=data['period_count'] - 1)
        keys = [(start + timedelta(days=index)).isoformat() for index in range(data['period_count'])]
        labels = [
            (start + timedelta(days=index)).strftime('%a' if data['period_count'] <= 7 else '%d')
            for index in range(data['period_count'])
        ]
    else:
        first_index = today.year * 12 + today.month - 1 - (data['period_count'] - 1)
        keys, labels = [], []
        for offset in range(data['period_count']):
            month_index = first_index + offset
            month = date(month_index // 12, month_index % 12 + 1, 1)
            keys.append(month.strftime('%Y-%m'))
            labels.append(month.strftime('%b'))
    chart_values = [int(rows[key]['value_cents']) if key in rows else 0 for key in keys]
    max_value = max(chart_values or [0]) or 1
    sales_buckets = [
        {'label': label, 'value_cents': value, 'height': max(6, round(value * 100 / max_value))}
        for label, value in zip(labels, chart_values)
    ]
    return render_template(
        'manager/dashboard.html', data=data, sales_buckets=sales_buckets,
        selected_period=selected_period,
    )


@manager.route('/orders')
@manager_required
def orders():
    selected_status = request.args.get('status', '')
    search = request.args.get('q', '').strip()[:120]
    orders, order_items = get_admin_orders(selected_status, search)
    return render_template(
        'manager/orders.html', orders=orders, order_items=order_items,
        order_statuses=ORDER_STATUSES, payment_statuses=ORDER_PAYMENT_STATUSES,
        selected_status=selected_status, search=search,
        payment_method_label=payment_method_label,
    )


@manager.route('/orders/<int:order_id>/status', methods=['POST'])
@manager_required
def change_order_status(order_id):
    if not valid_csrf_token():
        abort(400)
    result = update_order_status(order_id, request.form.get('status', ''))
    if result == 'updated':
        flash('Order status and physical stock were updated.', 'success')
    elif result == 'insufficient_stock':
        flash('There is not enough stock to confirm this order. Review stock first.', 'error')
    else:
        flash('The order or selected status could not be found.', 'error')
    return redirect(url_for('manager.orders'))


@manager.route('/orders/<int:order_id>/payment', methods=['POST'])
@manager_required
def change_payment_status(order_id):
    if not valid_csrf_token():
        abort(400)
    if update_order_payment_status(order_id, request.form.get('payment_status', '')):
        flash('Payment status updated.', 'success')
    else:
        flash('Confirm the order before marking it paid. Cancelled orders cannot be marked paid.', 'error')
    return redirect(url_for('manager.orders'))


@manager.route('/orders/<int:order_id>/payment-instructions', methods=['POST'])
@manager_required
def send_payment_instructions(order_id):
    if not valid_csrf_token():
        abort(400)
    order = get_admin_order(order_id)
    if order is None:
        abort(404)
    if order['status'] not in {'Confirmed', 'Preparing', 'Ready for pickup'}:
        flash('Confirm the order before sending payment instructions.', 'error')
        return redirect(url_for('manager.orders'))
    if order['payment_method'] not in TRANSFER_PAYMENT_METHODS:
        flash('This order uses cash payment; no transfer instructions are needed.', 'error')
        return redirect(url_for('manager.orders'))
    instructions = request.form.get('payment_instructions', '').strip()
    if not instructions or len(instructions) > 2000:
        flash('Enter payment details, up to 2,000 characters.', 'error')
        return redirect(url_for('manager.orders'))
    if not save_order_payment_instructions(order_id, instructions):
        flash('The order was cancelled before payment instructions could be saved.', 'error')
        return redirect(url_for('manager.orders'))
    body = '\n'.join([
        f"Hello {order['customer_name']},", '',
        f"Your order #{order_id} has been confirmed. The current estimate is ETB {order['total_cents'] / 100:,.2f}.",
        f"Preferred method: {payment_method_label(order['payment_method'])}.",
        'Payment instructions:', instructions, '',
        'Please confirm the final amount and availability with us before you pay. After payment, contact us with your order number and proof of payment. Do not send account passwords or verification codes.',
        '', 'Brothers-Online-Work', '0909847775', current_app.config['CONTACT_RECIPIENT'],
    ])
    try:
        send_email(
            f'Payment instructions for order #{order_id} | Brothers-Online-Work',
            body, order['email'], reply_to=current_app.config['CONTACT_RECIPIENT'],
        )
    except MailConfigurationError:
        current_app.logger.error('Payment instructions were saved, but SMTP is not configured.')
        flash('Payment instructions were saved, but email is not configured.', 'error')
    except MailDeliveryError:
        current_app.logger.exception('Payment instructions were saved, but the customer email failed.')
        flash('Payment instructions were saved, but the email could not be delivered.', 'error')
    else:
        flash('Payment instructions emailed. Mark the order paid only after verifying payment.', 'success')
    return redirect(url_for('manager.orders'))


@manager.route('/products')
@manager_required
def products():
    return render_template('manager/products.html', products=get_admin_products())


@manager.route('/products/new', methods=['GET', 'POST'])
@manager.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@manager_required
def edit_product(product_id=None):
    product = get_admin_product(product_id) if product_id else None
    if product_id and product is None:
        abort(404)
    if request.method == 'POST':
        if not valid_csrf_token():
            abort(400)
        name = ' '.join(request.form.get('name', '').split())
        description = request.form.get('description', '').strip()
        category = ' '.join(request.form.get('category', '').split())
        emoji = request.form.get('emoji', '').strip()[:16] or '🛍️'
        unit_label = request.form.get('unit_label', '')
        pricing_kind = request.form.get('pricing_kind', '')
        try:
            price = Decimal(request.form.get('price_etb', '').replace(',', '').strip())
            price_valid = price.is_finite() and 0 <= price <= Decimal('100000000')
            price_cents = int((price * 100).quantize(Decimal('1')))
        except (InvalidOperation, ValueError):
            price_valid, price_cents = False, -1
        try:
            stock = int(request.form.get('stock', ''))
        except ValueError:
            stock = -1
        valid = (
            bool(name) and len(name) <= 160 and bool(description) and len(description) <= 5000
            and bool(category) and len(category) <= 100 and price_valid
            and 0 <= stock <= 100000000
            and unit_label in {'each', 'device', 'page', 'service', 'application', 'entry'}
            and pricing_kind in {'fixed', 'from'}
        )
        if not valid:
            flash('Check the product name, description, category, price, stock, and unit.', 'error')
            return render_template('manager/product_form.html', product=product)
        save_admin_product(product_id, name, description, price_cents, emoji, stock, category, unit_label, pricing_kind)
        flash('Product saved.', 'success')
        return redirect(url_for('manager.products'))
    return render_template('manager/product_form.html', product=product)


@manager.route('/products/<int:product_id>/visibility', methods=['POST'])
@manager_required
def toggle_product_visibility(product_id):
    if not valid_csrf_token():
        abort(400)
    product = get_admin_product(product_id)
    if product is None:
        abort(404)
    set_admin_product_active(product_id, not bool(product['active']))
    flash('Product visibility updated.', 'success')
    return redirect(url_for('manager.products'))


@manager.route('/customers')
@manager_required
def customers():
    search = request.args.get('q', '').strip()[:120]
    return render_template('manager/customers.html', customers=get_admin_customers(search), search=search)


@manager.route('/system', methods=['GET', 'POST'])
@manager_required
def system():
    if request.method == 'POST':
        if not valid_csrf_token():
            abort(400)
        if request.form.get('action') == 'send_test_email':
            try:
                send_email(
                    'Brothers-Online-Work email configuration check',
                    'This is a test message requested from the manager system page.',
                    current_app.config['CONTACT_RECIPIENT'],
                )
            except MailConfigurationError:
                current_app.logger.error('Manager email check failed because SMTP is not configured.')
                flash('Email settings are incomplete. Check the environment variable names and values.', 'error')
            except MailDeliveryError:
                current_app.logger.exception('Manager email check could not be delivered.')
                flash('The mail server could not deliver the test message. Review service logs.', 'error')
            else:
                flash('Test email sent to the configured contact address.', 'success')
        return redirect(url_for('manager.system'))
    database_backend = 'PostgreSQL' if current_app.config.get('DATABASE_URL') else 'SQLite'
    database_healthy = False
    try:
        with get_db_connection() as connection:
            connection.execute('SELECT 1').fetchone()
            database_healthy = True
    except Exception:
        current_app.logger.exception('Manager database health check failed.')
    config = {
        'database_backend': database_backend,
        'database_configured': bool(current_app.config.get('DATABASE_URL') or current_app.config.get('DATABASE')),
        'database_healthy': database_healthy,
        'smtp_configured': all(current_app.config.get(key) for key in ('MAIL_SERVER', 'MAIL_PORT', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER')),
        'manager_password_configured': bool(current_app.config.get('ADMIN_PANEL_PASSWORD')),
        'secure_cookies': current_app.config.get('SESSION_COOKIE_SECURE', False),
    }
    return render_template('manager/system.html', config=config)
