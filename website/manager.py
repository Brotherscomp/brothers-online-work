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
    save_device_request_response,
    save_order_payment_instructions,
    set_admin_product_active,
    update_order_status,
    update_order_payment_status,
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
    password_is_configured = bool(current_app.config.get('ADMIN_PANEL_PASSWORD'))
    login_error = None
    if session.get('manager_authenticated'):
        return redirect(url_for('manager.dashboard'))

    if request.method == 'POST':
        configured_password = current_app.config.get('ADMIN_PANEL_PASSWORD', '')
        supplied_password = request.form.get('password', '')
        if not valid_csrf_token():
            login_error = translate('Your manager sign-in session expired. Refresh this page and try again.')
        elif configured_password and compare_digest(supplied_password, configured_password):
            session['manager_authenticated'] = True
            session.permanent = True
            destination = request.args.get('next', '')
            if destination.startswith('/manager/') and not destination.startswith('//'):
                return redirect(destination)
            return redirect(url_for('manager.dashboard'))
        elif configured_password:
            login_error = translate('The manager password is incorrect.')

    return render_template(
        'manager/login.html',
        password_is_configured=password_is_configured,
        login_error=login_error,
    )


@manager.route('/dashboard')
@manager_required
def dashboard():
    from datetime import date, timedelta

    selected_period = request.args.get('range', '7d')
    if selected_period not in {'7d', '30d', '6m', '12m'}:
        selected_period = '7d'
    report = get_manager_dashboard_data(selected_period)
    totals = report['totals']
    today = date.today()
    sales_by_period = {
        str(row['period_key'])[:10]: {'value_cents': row['value_cents'], 'order_count': row['order_count']}
        for row in report['sales_rows']
    }
    sales_buckets = []
    if report['period_unit'] == 'day':
        for offset in range(report['period_count'] - 1, -1, -1):
            day = today - timedelta(days=offset)
            label = day.strftime('%b %d').replace(' 0', ' ')
            bucket_key = day.isoformat()
            bucket_data = sales_by_period.get(bucket_key, {})
            sales_buckets.append({
                'label': label,
                'value_cents': bucket_data.get('value_cents', 0),
                'order_count': bucket_data.get('order_count', 0),
            })
    else:
        for offset in range(report['period_count'] - 1, -1, -1):
            month_index = today.month - 1 - offset
            year = today.year + month_index // 12
            month = month_index % 12 + 1
            first_day = date(year, month, 1)
            bucket_key = f'{year:04d}-{month:02d}'
            bucket_data = sales_by_period.get(bucket_key, {})
            sales_buckets.append({
                'label': first_day.strftime('%b %y'),
                'value_cents': bucket_data.get('value_cents', 0),
                'order_count': bucket_data.get('order_count', 0),
            })
    largest_bucket = max((item['value_cents'] for item in sales_buckets), default=0)
    for item in sales_buckets:
        item['bar_height'] = max(3, round(item['value_cents'] / largest_bucket * 100)) if largest_bucket else 3

    status_colors = {
        'Request received': '#e2a53a',
        'Confirmed': '#4f82e8',
        'Preparing': '#865ac7',
        'Ready for pickup': '#18a477',
        'Completed': '#38a169',
        'Cancelled': '#dc5963',
    }
    status_counts = {row['status']: row['order_count'] for row in report['order_status_counts']}
    display_statuses = list(ORDER_STATUSES)
    display_statuses.extend(status for status in status_counts if status not in status_colors)
    status_total = sum(status_counts.values())
    order_status_breakdown = [
        {
            'status': status,
            'count': status_counts.get(status, 0),
            'color': status_colors.get(status, '#8793a5'),
        }
        for status in display_statuses
    ]
    donut_parts = []
    current_angle = 0.0
    if status_total:
        for item in order_status_breakdown:
            if item['count']:
                next_angle = current_angle + item['count'] * 360 / status_total
                donut_parts.append(f"{item['color']} {current_angle:.2f}deg {next_angle:.2f}deg")
                current_angle = next_angle
    status_donut = (
        f"conic-gradient({', '.join(donut_parts)})"
        if donut_parts else 'conic-gradient(#e8edf5 0deg 360deg)'
    )

    top_categories = [dict(row) for row in report['top_categories']]
    largest_category = max((row['order_value_cents'] for row in top_categories), default=0)
    for category in top_categories:
        category['bar_width'] = max(4, round(category['order_value_cents'] / largest_category * 100)) if largest_category else 4

    return render_template(
        'manager/dashboard.html',
        totals=totals,
        recent_orders=report['recent_orders'],
        recent_order_items=report['recent_order_items'],
        recent_requests=report['recent_requests'],
        top_products=report['top_products'],
        top_categories=top_categories,
        top_customers=report['top_customers'],
        low_stock_products=report['low_stock_products'],
        sales_buckets=sales_buckets,
        selected_period=selected_period,
        order_status_breakdown=order_status_breakdown,
        status_donut=status_donut,
        order_statuses=ORDER_STATUSES,
        database_backend=report['database_backend'],
    )


@manager.route('/requests')
@manager_required
def requests():
    return render_template(
        'manager/requests.html',
        device_requests=get_device_requests(),
        request_statuses=REQUEST_STATUSES,
    )


@manager.route('/orders')
@manager_required
def orders():
    status = request.args.get('status', '').strip()
    if status not in ORDER_STATUSES:
        status = ''
    search = request.args.get('q', '').strip()[:100]
    order_rows, order_items = get_admin_orders(status=status, search=search)
    return render_template(
        'manager/orders.html',
        orders=order_rows,
        order_items=order_items,
        order_statuses=ORDER_STATUSES,
        payment_statuses=ORDER_PAYMENT_STATUSES,
        transfer_payment_methods=TRANSFER_PAYMENT_METHODS,
        selected_status=status,
        search=search,
    )


@manager.route('/orders/<int:order_id>/status', methods=['POST'])
@manager_required
def change_order_status(order_id):
    if not valid_csrf_token():
        abort(400)
    status = request.form.get('status', '').strip()
    if status not in ORDER_STATUSES:
        flash(translate('Choose a valid order status.'), 'error')
    else:
        result = update_order_status(order_id, status)
        if result == 'updated':
            flash(translate('Order status updated.'), 'success')
        elif result == 'insufficient_stock':
            flash(translate('There is not enough stock to confirm this order. Stock and order status were not changed.'), 'error')
        else:
            abort(404)
    return redirect(url_for('manager.orders'))


@manager.route('/orders/<int:order_id>/payment', methods=['POST'])
@manager_required
def change_order_payment(order_id):
    if not valid_csrf_token():
        abort(400)
    payment_status = request.form.get('payment_status', '').strip()
    if payment_status not in ORDER_PAYMENT_STATUSES:
        flash(translate('Choose a valid payment status.'), 'error')
    elif update_order_payment_status(order_id, payment_status):
        flash(translate('Payment status updated.'), 'success')
    else:
        flash(translate('Payment cannot be changed for a cancelled order.'), 'error')
    return redirect(url_for('manager.orders'))


@manager.route('/orders/<int:order_id>/payment-instructions', methods=['POST'])
@manager_required
def send_payment_instructions(order_id):
    if not valid_csrf_token():
        abort(400)
    order = get_admin_order(order_id)
    if order is None:
        abort(404)
    if order['payment_method'] not in TRANSFER_PAYMENT_METHODS:
        flash(translate('Payment instructions are only available for bank or mobile transfers.'), 'error')
        return redirect(url_for('manager.orders'))
    if order['status'] in {'Request received', 'Cancelled'}:
        flash(translate('Confirm the order before sending payment instructions.'), 'error')
        return redirect(url_for('manager.orders'))

    instructions = request.form.get('payment_instructions', '').strip()
    if not instructions or len(instructions) > 2000:
        flash(translate('Enter transfer instructions up to 2,000 characters.'), 'error')
        return redirect(url_for('manager.orders'))
    if not save_order_payment_instructions(order_id, instructions):
        abort(404)

    body = '\n'.join([
        f'Hello {order["customer_name"]},',
        '',
        f'Here are the payment instructions for your order request #{order_id}.',
        f'Preferred method: {payment_method_label(order["payment_method"])}',
        '',
        'Instructions:',
        instructions,
        '',
        f'Current estimate: ETB {order["total_cents"] / 100:,.2f}. This is not the final confirmed price.',
        'Please confirm the final total and availability with us before transferring money. We will update the order to Paid after we verify the transfer.',
        '',
        'Brothers-Online-Work',
        '0909847775',
        current_app.config['CONTACT_RECIPIENT'],
    ])
    try:
        send_email(
            f'Payment instructions for order #{order_id} | Brothers-Online-Work',
            body,
            order['email'],
            reply_to=current_app.config['CONTACT_RECIPIENT'],
        )
    except MailConfigurationError:
        current_app.logger.error('Payment instructions were saved for order %s, but SMTP is not configured.', order_id)
        flash(translate('Instructions were saved, but email is not configured. Set up SMTP and send them again.'), 'error')
    except MailDeliveryError:
        current_app.logger.exception('Payment instructions were saved for order %s, but delivery failed.', order_id)
        flash(translate('Instructions were saved, but the email could not be delivered. Try sending them again.'), 'error')
    else:
        flash(translate('Payment instructions were emailed to the customer.'), 'success')
    return redirect(url_for('manager.orders'))


@manager.route('/products', methods=['GET', 'POST'])
@manager.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@manager_required
def products(product_id=None):
    product = get_admin_product(product_id) if product_id else None
    if product_id and product is None:
        abort(404)
    if request.method == 'POST':
        if not valid_csrf_token():
            abort(400)
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip() or 'Shop'
        emoji = request.form.get('emoji', '').strip() or '🛍️'
        unit_label = request.form.get('unit_label', '').strip() or 'each'
        pricing_kind = request.form.get('pricing_kind', '').strip()
        try:
            price_text = request.form.get('price_etb', '').strip().replace(',', '')
            price = Decimal(price_text)
            stock = int(request.form.get('stock', '').strip())
            if (not name or len(name) > 120 or len(description) > 2000
                    or len(category) > 60 or len(emoji) > 16 or len(unit_label) > 32
                    or not price.is_finite() or price < 0 or price > Decimal('100000000')
                    or stock < 0 or stock > 1000000000
                    or pricing_kind not in {'fixed', 'from'}):
                raise ValueError
            price_cents = int((price * 100).quantize(Decimal('1')))
        except (InvalidOperation, ValueError, TypeError):
            flash(translate('Check the product name, price, stock, and category, then try again.'), 'error')
        else:
            if not save_admin_product(product_id, name, description, price_cents, emoji, stock, category, unit_label, pricing_kind):
                abort(404)
            flash(translate('Product updated.') if product_id else translate('Product added.'), 'success')
            return redirect(url_for('manager.products'))
    form_values = request.form if request.method == 'POST' else {}
    return render_template(
        'manager/products.html',
        products=get_admin_products(),
        product=product,
        form_values=form_values,
    )


@manager.route('/products/<int:product_id>/availability', methods=['POST'])
@manager_required
def change_product_availability(product_id):
    if not valid_csrf_token():
        abort(400)
    active_value = request.form.get('active', '')
    if active_value not in {'0', '1'}:
        abort(400)
    if not set_admin_product_active(product_id, active_value == '1'):
        abort(404)
    flash(translate('Product visibility updated.'), 'success')
    return redirect(url_for('manager.products'))


@manager.route('/customers')
@manager_required
def customers():
    search = request.args.get('q', '').strip()[:100]
    return render_template('manager/customers.html', customers=get_admin_customers(search), search=search)


@manager.route('/system', methods=['GET', 'POST'])
@manager_required
def system():
    if request.method == 'POST':
        if not valid_csrf_token():
            abort(400)
        recipient = current_app.config.get('CONTACT_RECIPIENT', '')
        try:
            send_email(
                'Brothers-Online-Work email test',
                'This test message confirms that the website can send email.',
                recipient,
            )
        except MailConfigurationError:
            current_app.logger.exception('Manager requested an email test, but SMTP configuration is incomplete.')
            flash(translate('Email test failed. Check the SMTP settings below and the Render service logs.'), 'error')
        except MailDeliveryError:
            current_app.logger.exception('Manager requested an email test, but the provider rejected or failed delivery.')
            flash(translate('Email test failed. Check the Render service logs for the provider response.'), 'error')
        else:
            flash(translate('Test email sent to the contact address.'), 'success')
        return redirect(url_for('manager.system'))

    database_backend = 'Unavailable'
    database_connected = False
    try:
        with get_db_connection() as connection:
            connection.execute('SELECT 1').fetchone()
            database_backend = 'PostgreSQL' if connection.is_postgres else 'SQLite'
            database_connected = True
    except Exception:
        current_app.logger.exception('Manager opened system status while the database health check failed.')

    mail_checks = {
        'SMTP server': bool(current_app.config.get('MAIL_SERVER')),
        'SMTP username': bool(current_app.config.get('MAIL_USERNAME')),
        'SMTP password': bool(current_app.config.get('MAIL_PASSWORD')),
        'Sender address': bool(current_app.config.get('MAIL_DEFAULT_SENDER')),
        'Contact recipient': bool(current_app.config.get('CONTACT_RECIPIENT')),
    }
    return render_template(
        'manager/system.html',
        database_backend=database_backend,
        database_connected=database_connected,
        database_url_configured=bool(current_app.config.get('DATABASE_URL')),
        mail_checks=mail_checks,
        mail_ready=all(mail_checks.values()),
        contact_recipient=current_app.config.get('CONTACT_RECIPIENT', ''),
        manager_password_configured=bool(current_app.config.get('ADMIN_PANEL_PASSWORD')),
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
