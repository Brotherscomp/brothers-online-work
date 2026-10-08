import re

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from .emailing import MailConfigurationError, MailDeliveryError, send_email
from .models import get_product, get_products, get_products_by_ids, place_order
from .translations import translate

views = Blueprint('views', __name__)


@views.route('/language/<language>', methods=['POST'])
def set_language(language):
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


@views.route('/contact', methods=['POST'])
def contact():
    home_contact = redirect(url_for('views.home') + '#contact')
    if request.form.get('website', '').strip():
        return home_contact

    first_name = ' '.join(request.form.get('first_name', '').split())
    last_name = ' '.join(request.form.get('last_name', '').split())
    email = request.form.get('email', '').strip().lower()
    phone = ' '.join(request.form.get('phone', '').split())
    service = request.form.get('service', '').strip()
    message = request.form.get('message', '').strip()

    valid_email = re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)
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
@views.route('/product/<int:product_id>')
def product_detail(product_id):
    product = get_product(product_id)
    if product is None:
        return render_template('store/not_found.html'), 404
    return render_template('store/product.html', product=product)


@views.route('/cart')
def cart():
    lines, total_cents = cart_products()
    return render_template('store/cart.html', lines=lines, total_cents=total_cents)


@views.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
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
        flash(translate('Item added to your request.'), 'success')
    return redirect(url_for('views.cart'))


@views.route('/cart/update', methods=['POST'])
def update_cart():
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

    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        address = request.form.get('address', '').strip()
        if not customer_name or not email or '@' not in email:
            flash(translate('Enter your name and a valid email address.'), 'error')
        else:
            try:
                order_id, total_cents = place_order(
                    customer_name, email, address, session.get('cart', {}), session.get('user_id')
                )
            except ValueError as error:
                flash(translate(str(error)), 'error')
                return redirect(url_for('views.cart'))
            session.pop('cart', None)
            return render_template('store/order_complete.html', order_id=order_id, total_cents=total_cents)

    return render_template(
        'store/checkout.html',
        lines=lines,
        total_cents=total_cents,
        customer_name=session.get('first_name', ''),
    )
