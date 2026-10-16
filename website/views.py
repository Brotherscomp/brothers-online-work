from decimal import Decimal, InvalidOperation
import secrets

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from .authss import _normalize_email, valid_auth_csrf_token
from .emailing import MailConfigurationError, MailDeliveryError, send_email
from .models import (
    create_device_request, get_chapa_order_by_reference, get_product, get_products,
    get_products_by_ids, mark_chapa_order_paid, place_order, set_chapa_payment_reference,
)
from .payments import (
    ChapaPaymentError, PAYMENT_DETAILS, PAYMENT_METHODS, start_chapa_checkout,
    verify_chapa_checkout,
)
from .translations import get_language, translate

views = Blueprint('views', __name__)


@views.route('/language/<language>', methods=['POST'])
def set_language(language):
    if not valid_auth_csrf_token():
        abort(400)
    if language in ('en', 'am'):
        session['language'] = language
    destination = request.form.get('next', '')
    if destination.startswith('/') and not destination.startswith('//'):
        return redirect(destination)
    return redirect(url_for('views.home'))


def cart_products():
    cart = session.get('cart', {})
    products = get_products_by_ids(cart.keys())
    lines = []
    total_cents = 0
    valid_cart = {}
    for product in products:
        quantity = max(1, min(int(cart.get(str(product['id']), 1)), product['stock']))
        if product['stock'] < 1:
            continue
        valid_cart[str(product['id'])] = quantity
        line_total = product['price_cents'] * quantity
        total_cents += line_total
        lines.append({'product': product, 'quantity': quantity, 'line_total': line_total})
    if valid_cart != cart:
        session['cart'] = valid_cart
    return lines, total_cents


def format_order_items(lines):
    return '\n'.join(
        f"{line['quantity']} x {line['product']['name']} — ETB {line['line_total'] / 100:,.2f}"
        for line in lines
    )


def _online_checkout_available(lines):
    return bool(current_app.config.get('CHAPA_SECRET_KEY')) and bool(lines) and all(
        line['product']['pricing_kind'] == 'fixed' for line in lines
    )


def _verified_chapa_order(tx_ref):
    order = get_chapa_order_by_reference(tx_ref)
    if order is None:
        return None, False
    if order['payment_status'] == 'Paid':
        return order, True

    result = verify_chapa_checkout(current_app.config.get('CHAPA_SECRET_KEY', ''), tx_ref)
    data = result.get('data')
    if not isinstance(data, dict):
        return order, False
    try:
        amount_cents = int((Decimal(str(data.get('amount'))) * 100).quantize(Decimal('1')))
    except (InvalidOperation, TypeError, ValueError):
        return order, False

    is_verified_live_payment = (
        result.get('status') == 'success'
        and str(data.get('status', '')).lower() == 'success'
        and data.get('tx_ref') == tx_ref
        and str(data.get('currency', '')).upper() == 'ETB'
        and str(data.get('mode', '')).lower() == 'live'
        and amount_cents == order['total_cents']
    )
    if not is_verified_live_payment:
        return order, False

    newly_paid = mark_chapa_order_paid(tx_ref, str(data.get('reference') or '')[:200])
    if newly_paid:
        paid_order = get_chapa_order_by_reference(tx_ref)
        if paid_order is not None:
            _notify_chapa_payment(paid_order)
    return get_chapa_order_by_reference(tx_ref), True


def _notify_chapa_payment(order):
    manager_body = '\n'.join([
        f'Chapa verified payment for order #{order["id"]}.',
        f'Customer: {order["customer_name"]}',
        f'Email: {order["email"]}',
        f'Paid amount: ETB {order["total_cents"] / 100:,.2f}',
    ])
    try:
        send_email(
            f'Payment received for order #{order["id"]} | Brothers-Online-Work',
            manager_body,
            current_app.config['DEVICE_REQUEST_RECIPIENT'],
            reply_to=order['email'],
        )
    except (MailConfigurationError, MailDeliveryError):
        current_app.logger.exception('Chapa payment was verified, but the store payment email failed.')

    customer_body = '\n'.join([
        f'Hello {order["customer_name"]},',
        '',
        f'We verified your payment for Brothers-Online-Work order #{order["id"]}.',
        f'Paid amount: ETB {order["total_cents"] / 100:,.2f}',
        '',
        'Thank you. Our team will confirm the order details with you.',
        '',
        'Brothers-Online-Work',
        '0909847775',
    ])
    try:
        send_email(
            f'Payment confirmed for order #{order["id"]} | Brothers-Online-Work',
            customer_body,
            order['email'],
            reply_to=current_app.config['CONTACT_RECIPIENT'],
        )
    except (MailConfigurationError, MailDeliveryError):
        current_app.logger.exception('Chapa payment was verified, but the customer payment email failed.')


@views.route('/')
def home():
    products = get_products()
    groups = []
    for product in products:
        if not groups or groups[-1][0] != product['category']:
            groups.append((product['category'], []))
        groups[-1][1].append(product)
    featured_names = {
        'Black-and-white printing',
        'Computer repair: software setup',
        'Smartphones',
        'DV registration form assistance',
    }
    highlights = [product for product in products if product['name'] in featured_names]
    return render_template('home.html', catalog_groups=groups, highlights=highlights)


@views.route('/policies')
def policies():
    return render_template(
        'policies.html',
        contact_email=current_app.config['CONTACT_RECIPIENT'],
        contact_phone='0909847775',
    )


@views.route('/contact', methods=['POST'])
def contact():
    if not valid_auth_csrf_token():
        abort(400)
    home_contact = redirect(url_for('views.home') + '#contact')
    if request.form.get('website', '').strip():
        return home_contact

    first_name = ' '.join(request.form.get('first_name', '').split())
    last_name = ' '.join(request.form.get('last_name', '').split())
    email = _normalize_email(request.form.get('email', ''))
    phone = ' '.join(request.form.get('phone', '').split())
    service = request.form.get('service', '').strip()
    message = request.form.get('message', '').strip()

    valid_email = bool(email)
    if (
        not first_name or len(first_name) > 80
        or not last_name or len(last_name) > 80
        or not valid_email or len(email) > 254
        or len(phone) > 40
        or not message or len(message) > 5000
    ):
        flash(translate('Please check the required contact fields and try again.'), 'error')
        return home_contact

    available_services = {product['name'] for product in get_products()}
    if service not in available_services:
        flash(translate('Please select one of our listed services.'), 'error')
        return home_contact

    client_name = f'{first_name} {last_name}'
    manager_body = '\n'.join([
        'A new message was sent from the Brothers-Online-Work website.',
        '',
        f'Name: {client_name}',
        f'Email: {email}',
        f'Phone: {phone or "Not provided"}',
        f'Service: {service}',
        '',
        'Message:',
        message,
    ])

    try:
        send_email(
            'New website message | Brothers-Online-Work',
            manager_body,
            current_app.config['CONTACT_RECIPIENT'],
            reply_to=email,
        )
    except MailConfigurationError:
        current_app.logger.error('The contact form email settings are incomplete.')
        flash(translate('Email is not set up yet. Please call 0909847775.'), 'error')
        return home_contact
    except MailDeliveryError:
        current_app.logger.exception('Could not deliver a website message to the store inbox.')
        flash(translate('Your message could not be delivered. Please call 0909847775.'), 'error')
        return home_contact

    confirmation_body = '\n'.join([
        f"{translate('Hello')} {first_name},",
        '',
        translate('Thank you for contacting Brothers-Online-Work.'),
        translate('We received your message and will get back to you soon.'),
        '',
        f"{translate('Your selected service')}: {translate(service)}",
        '',
        'Brothers-Online-Work',
        'Yazezee Kassa',
        '0909847775',
        'yazezewkassa@gmail.com',
    ])
    try:
        send_email(
            translate('We received your message | Brothers-Online-Work'),
            confirmation_body,
            email,
            reply_to=current_app.config['CONTACT_RECIPIENT'],
        )
    except (MailConfigurationError, MailDeliveryError):
        current_app.logger.exception('The store received the contact request, but its confirmation email failed.')
        flash(translate('Your message was received, but we could not email a confirmation.'), 'success')
    else:
        flash(translate('Your message was sent. We will contact you soon.'), 'success')
    return home_contact


@views.route('/device-request', methods=['POST'])
def device_request():
    if not valid_auth_csrf_token():
        flash(translate('Your form session expired. Please refresh the page and submit your request again.'), 'error')
        return redirect(url_for('views.home') + '#device-request')
    home_request = redirect(url_for('views.home') + '#device-request')
    if request.form.get('website', '').strip():
        return home_request

    customer_name = ' '.join(request.form.get('customer_name', '').split())
    email = _normalize_email(request.form.get('email', ''))
    phone = ' '.join(request.form.get('phone', '').split())
    request_type = request.form.get('request_type', '').strip()
    device_type_value = request.form.get('device_type', '').strip()
    brand = ' '.join(request.form.get('brand', '').split())
    model = ' '.join(request.form.get('model', '').split())
    details = request.form.get('details', '').strip()
    budget_text = request.form.get('budget_etb', '').strip().replace(',', '')
    budget_cents = None
    valid_email = bool(email)
    request_types = {'purchase': 'New device purchase', 'repair': 'Device repair'}
    device_types = {
        'computer': 'Computer',
        'mobile': 'Mobile phone',
        'printer': 'Printer',
        'projector': 'Projector',
        'other': 'Other device',
    }

    valid = (
        customer_name and len(customer_name) <= 160
        and valid_email and len(email) <= 254
        and len(phone) <= 40
        and request_type in request_types
        and device_type_value in device_types
        and brand and len(brand) <= 100
        and len(model) <= 120
        and details and len(details) <= 5000
    )
    if not valid:
        flash(translate('Please complete the required device request fields and try again.'), 'error')
        return home_request

    if budget_text:
        try:
            budget = Decimal(budget_text)
            if not budget.is_finite() or budget <= 0 or budget > Decimal('100000000'):
                raise InvalidOperation
            budget_cents = int((budget * 100).quantize(Decimal('1')))
        except InvalidOperation:
            flash(translate('Enter a valid optional budget in ETB.'), 'error')
            return home_request

    request_id = create_device_request(
        customer_name,
        email,
        phone,
        request_type,
        device_types[device_type_value],
        brand,
        model,
        details,
        budget_cents,
        get_language(),
    )
    manager_body = '\n'.join([
        f'A new device quote or repair request was submitted (#{request_id}).',
        '',
        f'Customer: {customer_name}',
        f'Email: {email}',
        f'Phone: {phone or "Not provided"}',
        f'Request: {request_types[request_type]}',
        f'Device: {device_types[device_type_value]}',
        f'Brand: {brand}',
        f'Model: {model or "Not provided"}',
        f'Budget: ETB {budget_cents / 100:,.2f}' if budget_cents is not None else 'Budget: Not provided',
        '',
        'Customer details:',
        details,
        '',
        f'Reply directly to this email to contact {customer_name}.',
    ])

    try:
        send_email(
            f'New device request #{request_id} | Brothers-Online-Work',
            manager_body,
            current_app.config['DEVICE_REQUEST_RECIPIENT'],
            reply_to=email,
        )
    except MailConfigurationError:
        current_app.logger.error('A device request was saved, but SMTP is not configured.')
        return render_template(
            'store/device_request_received.html',
            request_id=request_id,
            customer_email=email,
            manager_notified=False,
            confirmation_sent=False,
        )
    except MailDeliveryError:
        current_app.logger.exception('A device request was saved, but the store email could not be delivered.')
        return render_template(
            'store/device_request_received.html',
            request_id=request_id,
            customer_email=email,
            manager_notified=False,
            confirmation_sent=False,
        )

    confirmation_body = '\n'.join([
        f"{translate('Hello', get_language())} {customer_name},",
        '',
        translate('We received your device request and will review the brand and details.', get_language()),
        f"{translate('Request number:', get_language())} {request_id}",
        f"{translate('Request type', get_language())}: {translate(request_types[request_type], get_language())}",
        f"{translate('Device', get_language())}: {translate(device_types[device_type_value], get_language())}",
        f"{translate('Brand', get_language())}: {brand}",
        f"{translate('Model', get_language())}: {model or translate('Not provided', get_language())}",
        '',
        translate('We will email you with a price estimate or repair feedback. Final pricing is confirmed with you before work begins.', get_language()),
        '',
        'Brothers-Online-Work',
        'Yazezee Kassa',
        '0909847775',
    ])
    confirmation_sent = False
    try:
        send_email(
            translate('We received your device request | Brothers-Online-Work', get_language()),
            confirmation_body,
            email,
            reply_to=current_app.config['CONTACT_RECIPIENT'],
        )
    except (MailConfigurationError, MailDeliveryError):
        current_app.logger.exception('The store received a device request, but the customer acknowledgement failed.')
    else:
        confirmation_sent = True

    return render_template(
        'store/device_request_received.html',
        request_id=request_id,
        customer_email=email,
        manager_notified=True,
        confirmation_sent=confirmation_sent,
    )


@views.route('/product/<int:product_id>')
def product_detail(product_id):
    product = get_product(product_id)
    if product is None:
        return render_template('store/not_found.html'), 404
    return render_template('store/product.html', product=product)


@views.route('/cart')
def cart():
    lines, total_cents = cart_products()
    return render_template(
        'store/cart.html',
        lines=lines,
        total_cents=total_cents,
        online_checkout_available=_online_checkout_available(lines),
    )


@views.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if not valid_auth_csrf_token():
        abort(400)
    product = get_product(product_id)
    if product is None or product['stock'] < 1:
        flash(translate('That product is currently unavailable.'), 'error')
        return redirect(url_for('views.home'))
    cart = session.get('cart', {})
    key = str(product_id)
    quantity = max(1, int(cart.get(key, 0)) + 1)
    if quantity > product['stock']:
        flash(translate('There are no more of that item available.'), 'error')
    else:
        cart[key] = quantity
        session['cart'] = cart
        flash(translate('Item added to your cart.'), 'success')
    return redirect(url_for('views.cart'))


@views.route('/cart/update', methods=['POST'])
def update_cart():
    if not valid_auth_csrf_token():
        abort(400)
    current_cart = session.get('cart', {})
    updated_cart = {}
    for product_id in current_cart:
        raw_quantity = request.form.get(f'quantity_{product_id}', '0')
        try:
            quantity = int(raw_quantity)
        except ValueError:
            quantity = 0
        product = get_product(int(product_id))
        if product and quantity > 0:
            updated_cart[product_id] = min(quantity, product['stock'])
    session['cart'] = updated_cart
    flash(translate('Cart updated.'), 'success')
    return redirect(url_for('views.cart'))


@views.route('/checkout', methods=['GET', 'POST'])
def checkout():
    lines, total_cents = cart_products()
    if not lines:
        flash(translate('Add a product to your cart before checkout.'), 'error')
        return redirect(url_for('views.home'))

    online_checkout_available = _online_checkout_available(lines)
    payment_methods = PAYMENT_METHODS
    if online_checkout_available:
        payment_methods += (('chapa', 'Online payment via Chapa (Telebirr, CBE, and supported cards/banks)'),)
    payment_method_labels = dict(payment_methods)

    if request.method == 'POST':
        if not valid_auth_csrf_token():
            abort(400)
        customer_name = ' '.join(request.form.get('customer_name', '').split())
        email = _normalize_email(request.form.get('email', ''))
        address = request.form.get('address', '').strip()
        payment_method = request.form.get('payment_method', '')
        if payment_method == 'chapa' and not online_checkout_available:
            flash(translate('Online checkout is only available for exact fixed-price items after the payment account is connected.'), 'error')
        elif (not customer_name or len(customer_name) > 160 or not email or len(address) > 5000
                or payment_method not in payment_method_labels):
            flash(translate('Enter your name, a valid email address, and a payment method.'), 'error')
        else:
            try:
                order_id, total_cents = place_order(
                    customer_name, email, address, session.get('cart', {}), session.get('user_id'), payment_method
                )
            except ValueError as error:
                flash(translate(str(error)), 'error')
                return redirect(url_for('views.cart'))

            if payment_method == 'chapa':
                tx_ref = f'brothers-{order_id}-{secrets.token_hex(16)}'
                if not set_chapa_payment_reference(order_id, tx_ref):
                    current_app.logger.error('Could not store the Chapa payment reference for order #%s.', order_id)
                    session.pop('cart', None)
                    return render_template(
                        'store/payment_result.html',
                        order={'id': order_id, 'total_cents': total_cents},
                        payment_confirmed=False,
                        payment_start_failed=True,
                    )

                first_name, _, last_name = customer_name.partition(' ')
                invoice_items = [
                    {'key': line['product']['name'][:100], 'value': f"{line['quantity']} x {line['line_total'] / 100:.2f} ETB"}
                    for line in lines
                ]
                try:
                    checkout_url = start_chapa_checkout(
                        current_app.config.get('CHAPA_SECRET_KEY', ''),
                        amount_cents=total_cents,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                        tx_ref=tx_ref,
                        callback_url=url_for('views.chapa_callback', _external=True),
                        return_url=url_for('views.chapa_return', _external=True, tx_ref=tx_ref),
                        items=invoice_items,
                    )
                except ChapaPaymentError:
                    current_app.logger.exception('Could not start Chapa checkout for order #%s.', order_id)
                    session.pop('cart', None)
                    return render_template(
                        'store/payment_result.html',
                        order={'id': order_id, 'total_cents': total_cents},
                        payment_confirmed=False,
                        payment_start_failed=True,
                    )

                session.pop('cart', None)
                return redirect(checkout_url, code=303)

            items_text = format_order_items(lines)
            manager_body = '\n'.join([
                f'A new shop request was submitted (#{order_id}).',
                '',
                f'Customer: {customer_name}',
                f'Email: {email}',
                f'Address or service details: {address or "Not provided"}',
                f'Preferred payment method: {dict(PAYMENT_METHODS)[payment_method]}',
                '',
                'Requested items:',
                items_text,
                f'Estimated total: ETB {total_cents / 100:,.2f}',
                '',
                'No payment was collected. Confirm availability, final pricing, and payment instructions with the customer.',
            ])
            manager_notified = False
            try:
                send_email(
                    f'New shop request #{order_id} | Brothers-Online-Work',
                    manager_body,
                    current_app.config['DEVICE_REQUEST_RECIPIENT'],
                    reply_to=email,
                )
            except (MailConfigurationError, MailDeliveryError):
                current_app.logger.exception('A shop request was saved, but the store email notification failed.')
            else:
                manager_notified = True

            confirmation_body = '\n'.join([
                f'Hello {customer_name},',
                '',
                f'We received your Brothers-Online-Work request #{order_id}.',
                '',
                'Requested items:',
                items_text,
                f'Estimated total: ETB {total_cents / 100:,.2f}',
                f'Preferred payment method: {dict(PAYMENT_METHODS)[payment_method]}',
                '',
                'No payment was collected. We will confirm availability, final pricing, and payment instructions with you before completing your request.',
                '',
                'Brothers-Online-Work',
                'Yazezee Kassa',
                '0909847775',
                'yazezewkassa@gmail.com',
            ])
            transfer_details = PAYMENT_DETAILS.get(payment_method)
            if transfer_details:
                confirmation_body += '\n' + '\n'.join([
                    '',
                    'Manual transfer details:',
                    f"{transfer_details['provider']} — {transfer_details['account_label']}: {transfer_details['account_number']}",
                    f"Account holder: {transfer_details['account_holder']}",
                    f'Wait for us to confirm availability and the final amount before transferring. Use request #{order_id} as the transfer reference.',
                    'After paying, reply to this email with the transaction reference so we can verify it manually. Never send your PIN or one-time code.',
                    'Before confirming a transfer, check that the recipient name shown in your payment app matches the shop.',
                ])
            confirmation_sent = False
            try:
                send_email(
                    f'We received your shop request #{order_id} | Brothers-Online-Work',
                    confirmation_body,
                    email,
                    reply_to=current_app.config['CONTACT_RECIPIENT'],
                )
            except (MailConfigurationError, MailDeliveryError):
                current_app.logger.exception('A shop request was saved, but the customer confirmation email failed.')
            else:
                confirmation_sent = True

            session.pop('cart', None)
            return render_template(
                'store/order_complete.html',
                order_id=order_id,
                total_cents=total_cents,
                manager_notified=manager_notified,
                confirmation_sent=confirmation_sent,
                customer_email=email,
                payment_method=payment_method,
                payment_method_label=payment_method_labels[payment_method],
                payment_details=PAYMENT_DETAILS.get(payment_method),
            )

    return render_template(
        'store/checkout.html',
        lines=lines,
        total_cents=total_cents,
        customer_name=session.get('first_name', ''),
        customer_email=session.get('email', ''),
        payment_methods=payment_methods,
        selected_payment_method=request.form.get('payment_method', 'cash_pickup'),
        payment_details=PAYMENT_DETAILS,
        online_checkout_available=online_checkout_available,
    )


@views.route('/payments/chapa/callback', methods=['GET'])
def chapa_callback():
    tx_ref = (request.args.get('trx_ref') or request.args.get('tx_ref') or '').strip()
    if not tx_ref or len(tx_ref) > 120:
        return jsonify(status='invalid_reference'), 400
    try:
        order, payment_confirmed = _verified_chapa_order(tx_ref)
    except ChapaPaymentError:
        current_app.logger.exception('Chapa callback verification could not reach the payment provider.')
        return jsonify(status='verification_unavailable'), 503
    if order is None:
        return jsonify(status='unknown_reference'), 404
    return jsonify(status='verified' if payment_confirmed else 'not_verified'), 200


@views.route('/payments/chapa/return', methods=['GET'])
def chapa_return():
    tx_ref = (request.args.get('tx_ref') or request.args.get('trx_ref') or '').strip()
    if not tx_ref or len(tx_ref) > 120:
        abort(404)
    try:
        order, payment_confirmed = _verified_chapa_order(tx_ref)
    except ChapaPaymentError:
        current_app.logger.exception('Could not verify the returning Chapa payment.')
        order = get_chapa_order_by_reference(tx_ref)
        payment_confirmed = False
    if order is None:
        abort(404)
    return render_template(
        'store/payment_result.html',
        order=order,
        payment_confirmed=payment_confirmed,
        payment_start_failed=False,
    )
