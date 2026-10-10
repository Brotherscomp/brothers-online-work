import sqlite3
from contextlib import contextmanager

from flask import current_app


@contextmanager
def get_db_connection():
    connection = sqlite3.connect(current_app.config['DATABASE'])
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with get_db_connection() as connection:
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                first_name TEXT NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
                emoji TEXT NOT NULL DEFAULT '🛍️',
                stock INTEGER NOT NULL DEFAULT 20 CHECK (stock >= 0),
                active INTEGER NOT NULL DEFAULT 1,
                category TEXT NOT NULL DEFAULT 'Shop',
                unit_label TEXT NOT NULL DEFAULT 'each',
                pricing_kind TEXT NOT NULL DEFAULT 'fixed'
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                address TEXT NOT NULL,
                total_cents INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Received',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id INTEGER REFERENCES products(id),
                product_name TEXT NOT NULL,
                unit_price_cents INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0)
            );
            CREATE TABLE IF NOT EXISTS device_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                request_type TEXT NOT NULL,
                device_type TEXT NOT NULL,
                brand TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL,
                budget_cents INTEGER,
                language TEXT NOT NULL DEFAULT 'en',
                status TEXT NOT NULL DEFAULT 'Received',
                quote_cents INTEGER,
                feedback TEXT NOT NULL DEFAULT '',
                response_sent_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(products)')}
        if 'category' not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'Shop'")
        if 'unit_label' not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN unit_label TEXT NOT NULL DEFAULT 'each'")
        if 'pricing_kind' not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN pricing_kind TEXT NOT NULL DEFAULT 'fixed'")

        # Hide the starter demo catalog from earlier versions of the app.
        connection.execute("UPDATE products SET active = 0 WHERE name IN ('Everyday T-Shirt', 'Canvas Tote Bag', 'Ceramic Coffee Mug', 'National ID print and update')")

        offerings = [
            ('Laptop computers', 'New and used computer models. Price depends on brand, specifications, and condition; ask us to confirm the exact model.', 7900000, '💻', 'Computers', 'each', 'from'),
            ('Computer repair: software setup', 'Operating system installation, updates, and basic software setup. Data backup and software licenses are separate.', 80000, '🛠️', 'Computers', 'device', 'from'),
            ('Computer repair: cooling service', 'Internal cleaning and thermal service. Replacement parts, if needed, are quoted separately.', 120000, '🧰', 'Computers', 'device', 'from'),
            ('Smartphones', 'Entry-level smartphones. Exact model, memory, warranty, and availability determine the final price.', 1420000, '📱', 'Mobile Phones', 'each', 'from'),
            ('Mobile phone repair', 'Screen repair starting price for basic models. Final price depends on the phone model and replacement part.', 280000, '🔧', 'Mobile Phones', 'device', 'from'),
            ('Mobile phone software repair', 'Software troubleshooting, updates, reset support, and basic setup. Data backup and paid software licenses are separate.', 20000, '📲', 'Mobile Phones', 'device', 'from'),
            ('Printers', 'Home and small-office printers. Price depends on model, features, and current stock.', 4025000, '🖨️', 'Printers', 'each', 'from'),
            ('Used printer and computer buying and selling', 'We buy and sell used printers and computers. The final value depends on the model, condition, specifications, and included accessories.', 500000, '♻️', 'Printers', 'each', 'from'),
            ('Printer inspection and repair', 'Initial printer inspection and basic service. Parts and complex repairs are quoted before work begins.', 50000, '🪛', 'Printers', 'device', 'from'),
            ('Black-and-white printing', 'A4 document printing on standard paper.', 1000, '📄', 'Print & Copy', 'page', 'fixed'),
            ('Color printing', 'A4 color document printing on standard paper. Photo paper and larger formats cost extra.', 2000, '🖨️', 'Print & Copy', 'page', 'fixed'),
            ('Photocopying', 'A4 black-and-white photocopy on standard paper.', 1000, '📑', 'Print & Copy', 'page', 'fixed'),
            ('A4 laminating', 'A4 document lamination. Larger sizes and special pouches are priced separately.', 2000, '🪪', 'Print & Copy', 'page', 'fixed'),
            ('National ID print', 'National ID document printing service.', 35000, '🪪', 'Print & Copy', 'service', 'fixed'),
            ('National ID update', 'Assistance with updating National ID details online. Official government fees are not included.', 25000, '📝', 'Print & Copy', 'service', 'fixed'),
            ('Passport application and appointment assistance', 'Help preparing and submitting an online passport application and appointment request. Government passport fees are not included; appointment availability is controlled by the relevant authority.', 50000, '🛂', 'Online Form Assistance', 'application', 'fixed'),
            ('DV registration form assistance', 'Help preparing a Diversity Visa entry during the official registration period. This is an assistance fee only; entry submission is free through the U.S. government. No selection or visa outcome is guaranteed.', 50000, '📝', 'Online Form Assistance', 'entry', 'fixed'),
        ]
        for name, description, price_cents, emoji, category, unit_label, pricing_kind in offerings:
            exists = connection.execute('SELECT 1 FROM products WHERE name = ?', (name,)).fetchone()
            if not exists:
                connection.execute(
                    '''INSERT INTO products
                       (name, description, price_cents, emoji, stock, active, category, unit_label, pricing_kind)
                       VALUES (?, ?, ?, ?, 9999, 1, ?, ?, ?)''',
                    (name, description, price_cents, emoji, category, unit_label, pricing_kind),
                )


def find_user_by_email(email):
    with get_db_connection() as connection:
        return connection.execute(
            'SELECT id, email, first_name, password_hash FROM users WHERE email = ?',
            (email,),
        ).fetchone()


def create_user(email, first_name, password_hash):
    with get_db_connection() as connection:
        cursor = connection.execute(
            'INSERT INTO users (email, first_name, password_hash) VALUES (?, ?, ?)',
            (email, first_name, password_hash),
        )
        return cursor.lastrowid


def get_products():
    with get_db_connection() as connection:
        return connection.execute(
            '''SELECT * FROM products WHERE active = 1
               ORDER BY CASE category
                   WHEN 'Computers' THEN 1
                   WHEN 'Mobile Phones' THEN 2
                   WHEN 'Printers' THEN 3
                   WHEN 'Print & Copy' THEN 4
                   ELSE 5 END, id'''
        ).fetchall()


def get_products_by_ids(product_ids):
    clean_ids = [int(product_id) for product_id in product_ids if str(product_id).isdigit()]
    if not clean_ids:
        return []
    placeholders = ','.join('?' for _ in clean_ids)
    with get_db_connection() as connection:
        return connection.execute(
            f'SELECT * FROM products WHERE active = 1 AND id IN ({placeholders})', clean_ids
        ).fetchall()


def get_product(product_id):
    with get_db_connection() as connection:
        return connection.execute(
            'SELECT * FROM products WHERE id = ? AND active = 1', (product_id,)
        ).fetchone()


def place_order(customer_name, email, address, cart, user_id=None):
    with get_db_connection() as connection:
        order_lines = []
        total_cents = 0
        for product_id, quantity in cart.items():
            product = connection.execute(
                'SELECT id, name, price_cents, stock, pricing_kind FROM products WHERE id = ? AND active = 1',
                (product_id,),
            ).fetchone()
            if product is None or quantity < 1 or product['stock'] < quantity:
                raise ValueError('One or more items are unavailable in the requested quantity.')
            order_lines.append((product, quantity))
            total_cents += product['price_cents'] * quantity

        if not order_lines:
            raise ValueError('Your cart is empty.')

        cursor = connection.execute(
            'INSERT INTO orders (user_id, customer_name, email, address, total_cents, status) VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, customer_name, email, address, total_cents, 'Request received'),
        )
        order_id = cursor.lastrowid
        for product, quantity in order_lines:
            connection.execute(
                'INSERT INTO order_items (order_id, product_id, product_name, unit_price_cents, quantity) VALUES (?, ?, ?, ?, ?)',
                (order_id, product['id'], product['name'], product['price_cents'], quantity),
            )
        return order_id, total_cents


def create_device_request(
    customer_name, email, phone, request_type, device_type, brand, model,
    details, budget_cents, language,
):
    with get_db_connection() as connection:
        cursor = connection.execute(
            '''INSERT INTO device_requests
               (customer_name, email, phone, request_type, device_type, brand,
                model, details, budget_cents, language)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                customer_name, email, phone, request_type, device_type, brand,
                model, details, budget_cents, language,
            ),
        )
        return cursor.lastrowid


def get_device_requests():
    with get_db_connection() as connection:
        return connection.execute(
            'SELECT * FROM device_requests ORDER BY created_at DESC, id DESC'
        ).fetchall()


def get_device_request(request_id):
    with get_db_connection() as connection:
        return connection.execute(
            'SELECT * FROM device_requests WHERE id = ?', (request_id,)
        ).fetchone()


def save_device_request_response(request_id, status, quote_cents, feedback):
    with get_db_connection() as connection:
        cursor = connection.execute(
            '''UPDATE device_requests
               SET status = ?, quote_cents = ?, feedback = ?, response_sent_at = NULL
               WHERE id = ?''',
            (status, quote_cents, feedback, request_id),
        )
        return cursor.rowcount > 0


def mark_device_request_response_sent(request_id):
    with get_db_connection() as connection:
        connection.execute(
            'UPDATE device_requests SET response_sent_at = CURRENT_TIMESTAMP WHERE id = ?',
            (request_id,),
        )
