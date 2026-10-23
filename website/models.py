import sqlite3
import threading
from contextlib import contextmanager

from flask import current_app


_rate_limit_cleanup_lock = threading.Lock()
_last_rate_limit_cleanup = 0


class DatabaseConnection:
    """Small DB-API adapter so existing qmark SQL works with both databases."""

    def __init__(self, connection, is_postgres=False):
        self.connection = connection
        self.is_postgres = is_postgres

    def execute(self, sql, parameters=()):
        if self.is_postgres:
            sql = sql.replace('?', '%s')
        return self.connection.execute(sql, parameters)


@contextmanager
def get_db_connection():
    database_url = current_app.config.get('DATABASE_URL')
    if database_url:
        import psycopg
        from psycopg.rows import dict_row

        raw_connection = psycopg.connect(database_url, row_factory=dict_row)
        connection = DatabaseConnection(raw_connection, is_postgres=True)
    else:
        raw_connection = sqlite3.connect(current_app.config['DATABASE'], timeout=15)
        raw_connection.execute('PRAGMA foreign_keys = ON')
        raw_connection.execute('PRAGMA busy_timeout = 15000')
        raw_connection.row_factory = sqlite3.Row
        connection = DatabaseConnection(raw_connection)
    try:
        yield connection
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def is_integrity_error(error):
    if isinstance(error, sqlite3.IntegrityError):
        return True
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(error, psycopg.IntegrityError)


def consume_rate_limit(bucket_key, max_requests, window_seconds, now):
    global _last_rate_limit_cleanup
    window_threshold = now - window_seconds
    with get_db_connection() as connection:
        row = connection.execute(
            '''INSERT INTO rate_limits (bucket_key, window_started_at, request_count)
               VALUES (?, ?, 1)
               ON CONFLICT (bucket_key) DO UPDATE SET
                 request_count = CASE
                   WHEN rate_limits.window_started_at <= ? THEN 1
                   ELSE rate_limits.request_count + 1
                 END,
                 window_started_at = CASE
                   WHEN rate_limits.window_started_at <= ? THEN excluded.window_started_at
                   ELSE rate_limits.window_started_at
                 END
               RETURNING request_count''',
            (bucket_key, now, window_threshold, window_threshold),
        ).fetchone()
        if now - _last_rate_limit_cleanup >= 3600:
            with _rate_limit_cleanup_lock:
                if now - _last_rate_limit_cleanup >= 3600:
                    connection.execute(
                        'DELETE FROM rate_limits WHERE window_started_at < ?', (now - 86400,)
                    )
                    _last_rate_limit_cleanup = now
        return int(row['request_count']) <= max_requests


def _insert_id(connection, sql, parameters):
    if connection.is_postgres:
        return connection.execute(f'{sql} RETURNING id', parameters).fetchone()['id']
    return connection.execute(sql, parameters).lastrowid


SQLITE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        first_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        email_verified INTEGER NOT NULL DEFAULT 1,
        session_version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS email_verification_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        payment_method TEXT NOT NULL DEFAULT 'cash_pickup',
        payment_status TEXT NOT NULL DEFAULT 'Unpaid',
        payment_instructions TEXT NOT NULL DEFAULT '',
        inventory_applied INTEGER NOT NULL DEFAULT 0,
        payment_reference TEXT NOT NULL DEFAULT '',
        gateway_reference TEXT NOT NULL DEFAULT '',
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
'''


POSTGRES_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS users (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        first_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        email_verified INTEGER NOT NULL DEFAULT 1,
        session_version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    );
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at BIGINT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    );
    CREATE TABLE IF NOT EXISTS email_verification_tokens (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at BIGINT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    );
    CREATE TABLE IF NOT EXISTS products (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        price_cents BIGINT NOT NULL CHECK (price_cents >= 0),
        emoji TEXT NOT NULL DEFAULT '🛍️',
        stock BIGINT NOT NULL DEFAULT 20 CHECK (stock >= 0),
        active INTEGER NOT NULL DEFAULT 1,
        category TEXT NOT NULL DEFAULT 'Shop',
        unit_label TEXT NOT NULL DEFAULT 'each',
        pricing_kind TEXT NOT NULL DEFAULT 'fixed'
    );
    CREATE TABLE IF NOT EXISTS orders (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        customer_name TEXT NOT NULL,
        email TEXT NOT NULL,
        address TEXT NOT NULL,
        total_cents BIGINT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Received',
        payment_method TEXT NOT NULL DEFAULT 'cash_pickup',
        payment_status TEXT NOT NULL DEFAULT 'Unpaid',
        payment_instructions TEXT NOT NULL DEFAULT '',
        inventory_applied INTEGER NOT NULL DEFAULT 0,
        payment_reference TEXT NOT NULL DEFAULT '',
        gateway_reference TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    );
    CREATE TABLE IF NOT EXISTS order_items (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        order_id BIGINT NOT NULL REFERENCES orders(id),
        product_id BIGINT REFERENCES products(id),
        product_name TEXT NOT NULL,
        unit_price_cents BIGINT NOT NULL,
        quantity BIGINT NOT NULL CHECK (quantity > 0)
    );
    CREATE TABLE IF NOT EXISTS device_requests (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        customer_name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT NOT NULL DEFAULT '',
        request_type TEXT NOT NULL,
        device_type TEXT NOT NULL,
        brand TEXT NOT NULL,
        model TEXT NOT NULL DEFAULT '',
        details TEXT NOT NULL,
        budget_cents BIGINT,
        language TEXT NOT NULL DEFAULT 'en',
        status TEXT NOT NULL DEFAULT 'Received',
        quote_cents BIGINT,
        feedback TEXT NOT NULL DEFAULT '',
        response_sent_at TEXT,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    );
'''


def init_db():
    with get_db_connection() as connection:
        schema = POSTGRES_SCHEMA if connection.is_postgres else SQLITE_SCHEMA
        for statement in schema.split(';'):
            if statement.strip():
                connection.execute(statement)

        connection.execute(
            '''CREATE TABLE IF NOT EXISTS rate_limits (
                 bucket_key TEXT PRIMARY KEY,
                 window_started_at BIGINT NOT NULL,
                 request_count INTEGER NOT NULL
               )'''
        )
        connection.execute(
            'CREATE INDEX IF NOT EXISTS rate_limits_window_started_at '
            'ON rate_limits(window_started_at)'
        )

        if connection.is_postgres:
            user_columns = {
                row['column_name']
                for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'users'"
                )
            }
        else:
            user_columns = {row['name'] for row in connection.execute('PRAGMA table_info(users)')}
        if 'email_verified' not in user_columns:
            connection.execute('ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1')
        if 'session_version' not in user_columns:
            connection.execute('ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0')
        if 'created_at' not in user_columns:
            if connection.is_postgres:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)"
                )
            else:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT '1970-01-01 00:00:00'"
                )
                connection.execute('UPDATE users SET created_at = CURRENT_TIMESTAMP')

        if connection.is_postgres:
            columns = {
                row['column_name']
                for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'products'"
                )
            }
        else:
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(products)')}
        if 'category' not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'Shop'")
        if 'unit_label' not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN unit_label TEXT NOT NULL DEFAULT 'each'")
        if 'pricing_kind' not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN pricing_kind TEXT NOT NULL DEFAULT 'fixed'")

        if connection.is_postgres:
            order_columns = {
                row['column_name']
                for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'orders'"
                )
            }
        else:
            order_columns = {row['name'] for row in connection.execute('PRAGMA table_info(orders)')}
        for column_name, definition in (
            ('payment_method', "TEXT NOT NULL DEFAULT 'cash_pickup'"),
            ('payment_status', "TEXT NOT NULL DEFAULT 'Unpaid'"),
            ('payment_instructions', "TEXT NOT NULL DEFAULT ''"),
            ('inventory_applied', 'INTEGER NOT NULL DEFAULT 0'),
            ('payment_reference', "TEXT NOT NULL DEFAULT ''"),
            ('gateway_reference', "TEXT NOT NULL DEFAULT ''"),
        ):
            if column_name not in order_columns:
                connection.execute(f'ALTER TABLE orders ADD COLUMN {column_name} {definition}')
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS orders_payment_reference_unique "
            "ON orders(payment_reference) WHERE payment_reference <> ''"
        )
        for index_sql in (
            'CREATE INDEX IF NOT EXISTS orders_created_at_id ON orders(created_at DESC, id DESC)',
            'CREATE INDEX IF NOT EXISTS orders_user_created_at ON orders(user_id, created_at DESC, id DESC)',
            'CREATE INDEX IF NOT EXISTS orders_payment_status_created_at ON orders(payment_status, status, created_at)',
            'CREATE INDEX IF NOT EXISTS order_items_order_id_id ON order_items(order_id, id)',
            'CREATE INDEX IF NOT EXISTS order_items_product_id ON order_items(product_id)',
            'CREATE INDEX IF NOT EXISTS device_requests_created_at_id ON device_requests(created_at DESC, id DESC)',
        ):
            connection.execute(index_sql)

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
            'SELECT id, email, first_name, password_hash, email_verified, session_version FROM users WHERE email = ?',
            (email.lower(),),
        ).fetchone()


def get_user_session_version(user_id):
    with get_db_connection() as connection:
        user = connection.execute(
            'SELECT session_version FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        return int(user['session_version']) if user else None


def create_user(email, first_name, password_hash):
    with get_db_connection() as connection:
        return _insert_id(
            connection,
            'INSERT INTO users (email, first_name, password_hash, email_verified) VALUES (?, ?, ?, 0)',
            (email.lower(), first_name, password_hash),
        )


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


def place_order(customer_name, email, address, cart, user_id=None, payment_method='cash_pickup'):
    with get_db_connection() as connection:
        order_lines = []
        total_cents = 0
        for raw_product_id, raw_quantity in cart.items():
            try:
                product_id = int(raw_product_id)
                quantity = int(raw_quantity)
            except (TypeError, ValueError):
                raise ValueError('One or more items are unavailable in the requested quantity.') from None
            if product_id < 1 or quantity < 1:
                raise ValueError('One or more items are unavailable in the requested quantity.')
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

        order_id = _insert_id(
            connection,
            'INSERT INTO orders (user_id, customer_name, email, address, total_cents, status, payment_method) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (user_id, customer_name, email, address, total_cents, 'Request received', payment_method),
        )
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
        return _insert_id(
            connection,
            '''INSERT INTO device_requests
               (customer_name, email, phone, request_type, device_type, brand,
                model, details, budget_cents, language)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                customer_name, email, phone, request_type, device_type, brand,
                model, details, budget_cents, language,
            ),
        )


def get_device_requests(page=1, per_page=50):
    page = max(1, int(page))
    per_page = max(1, min(100, int(per_page)))
    offset = (page - 1) * per_page
    with get_db_connection() as connection:
        total = connection.execute('SELECT COUNT(*) AS total FROM device_requests').fetchone()['total']
        rows = connection.execute(
            '''SELECT * FROM device_requests
               ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?''',
            (per_page, offset),
        ).fetchall()
        return rows, int(total)


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
        sent_at = 'CURRENT_TIMESTAMP::text' if connection.is_postgres else 'CURRENT_TIMESTAMP'
        connection.execute(
            f'UPDATE device_requests SET response_sent_at = {sent_at} WHERE id = ?',
            (request_id,),
        )


def create_password_reset_token(user_id, token_hash, expires_at):
    with get_db_connection() as connection:
        connection.execute('DELETE FROM password_reset_tokens WHERE user_id = ?', (user_id,))
        connection.execute(
            'INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)',
            (user_id, token_hash, expires_at),
        )


def password_reset_token_is_valid(token_hash, now):
    with get_db_connection() as connection:
        return connection.execute(
            'SELECT 1 FROM password_reset_tokens WHERE token_hash = ? AND expires_at > ?',
            (token_hash, now),
        ).fetchone() is not None


def consume_password_reset_token(token_hash, password_hash, now):
    with get_db_connection() as connection:
        lock_clause = ' FOR UPDATE' if connection.is_postgres else ''
        token = connection.execute(
            'SELECT user_id FROM password_reset_tokens WHERE token_hash = ? AND expires_at > ?' + lock_clause,
            (token_hash, now),
        ).fetchone()
        if token is None:
            return False
        deleted = connection.execute(
            'DELETE FROM password_reset_tokens WHERE token_hash = ? AND expires_at > ?',
            (token_hash, now),
        )
        if deleted.rowcount != 1:
            return False
        connection.execute(
            'UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?',
            (password_hash, token['user_id']),
        )
        connection.execute('DELETE FROM password_reset_tokens WHERE user_id = ?', (token['user_id'],))
        return True


def delete_password_reset_token(token_hash):
    with get_db_connection() as connection:
        connection.execute('DELETE FROM password_reset_tokens WHERE token_hash = ?', (token_hash,))


def create_email_verification_token(user_id, token_hash, expires_at):
    with get_db_connection() as connection:
        connection.execute('DELETE FROM email_verification_tokens WHERE user_id = ?', (user_id,))
        connection.execute(
            'INSERT INTO email_verification_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)',
            (user_id, token_hash, expires_at),
        )


def consume_email_verification_token(token_hash, now):
    with get_db_connection() as connection:
        lock_clause = ' FOR UPDATE' if connection.is_postgres else ''
        token = connection.execute(
            'SELECT user_id FROM email_verification_tokens WHERE token_hash = ? AND expires_at > ?' + lock_clause,
            (token_hash, now),
        ).fetchone()
        if token is None:
            return False
        deleted = connection.execute(
            'DELETE FROM email_verification_tokens WHERE token_hash = ? AND expires_at > ?',
            (token_hash, now),
        )
        if deleted.rowcount != 1:
            return False
        connection.execute('UPDATE users SET email_verified = 1 WHERE id = ?', (token['user_id'],))
        connection.execute('DELETE FROM email_verification_tokens WHERE user_id = ?', (token['user_id'],))
        return True


def email_verification_token_is_valid(token_hash, now):
    with get_db_connection() as connection:
        return connection.execute(
            'SELECT 1 FROM email_verification_tokens WHERE token_hash = ? AND expires_at > ?',
            (token_hash, now),
        ).fetchone() is not None


def delete_email_verification_token(token_hash):
    with get_db_connection() as connection:
        connection.execute('DELETE FROM email_verification_tokens WHERE token_hash = ?', (token_hash,))


def get_customer_orders(user_id):
    with get_db_connection() as connection:
        orders = connection.execute(
            '''SELECT id, total_cents, status, payment_method, payment_status,
                      payment_instructions, created_at
               FROM orders WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 100''',
            (user_id,),
        ).fetchall()
        order_ids = [order['id'] for order in orders]
        items_by_order = {order_id: [] for order_id in order_ids}
        if order_ids:
            placeholders = ','.join('?' for _ in order_ids)
            items = connection.execute(
                f'''SELECT order_id, product_name, quantity FROM order_items
                    WHERE order_id IN ({placeholders}) ORDER BY order_id DESC, id''',
                order_ids,
            ).fetchall()
            for item in items:
                items_by_order[item['order_id']].append(item)
        return orders, items_by_order


ORDER_STATUSES = (
    'Request received', 'Confirmed', 'Preparing', 'Ready for pickup', 'Completed', 'Cancelled',
)
ORDER_PAYMENT_STATUSES = ('Unpaid', 'Paid')
PAYMENT_REQUIRED_ORDER_STATUSES = frozenset({'Ready for pickup', 'Completed'})


def get_manager_dashboard_data(selected_period='7d'):
    from datetime import date, timedelta

    period_options = {'7d': ('day', 7), '30d': ('day', 30), '6m': ('month', 6), '12m': ('month', 12)}
    period_unit, period_count = period_options.get(selected_period, ('day', 7))
    today = date.today()
    if period_unit == 'day':
        start_date = today - timedelta(days=period_count - 1)
        period_start = start_date.isoformat()
    else:
        month_index = today.year * 12 + today.month - 1 - (period_count - 1)
        start_date = date(month_index // 12, month_index % 12 + 1, 1)
        period_start = start_date.strftime('%Y-%m')
    date_expr = 'substr(created_at, 1, 10)' if period_unit == 'day' else 'substr(created_at, 1, 7)'

    with get_db_connection() as connection:
        totals = connection.execute(
            '''SELECT
                 (SELECT COUNT(*) FROM orders) AS order_count,
                 (SELECT COUNT(*) FROM orders WHERE status = 'Cancelled') AS cancelled_order_count,
                 (SELECT COUNT(*) FROM orders WHERE status NOT IN ('Completed', 'Cancelled')) AS open_order_count,
                 (SELECT COALESCE(SUM(total_cents), 0) FROM orders WHERE status <> 'Cancelled' AND payment_status = 'Paid') AS paid_sales_cents,
                 (SELECT COALESCE(AVG(total_cents), 0) FROM orders WHERE status <> 'Cancelled' AND payment_status = 'Paid') AS average_paid_order_cents,
                 (SELECT COUNT(*) FROM products WHERE active = 1) AS product_count,
                 (SELECT COUNT(*) FROM products WHERE active = 1 AND stock <= 5) AS low_stock_count,
                 (SELECT COUNT(*) FROM (
                    SELECT LOWER(email) AS email FROM users
                    UNION SELECT LOWER(email) FROM orders
                    UNION SELECT LOWER(email) FROM device_requests
                  ) AS customer_emails) AS customer_count'''
        ).fetchone()
        sales_rows = connection.execute(
            f'''SELECT {date_expr} AS period_key, SUM(total_cents) AS value_cents,
                       COUNT(*) AS order_count
                FROM orders WHERE payment_status = 'Paid' AND status <> 'Cancelled'
                  AND created_at >= ?
                GROUP BY {date_expr} ORDER BY period_key''',
            (period_start,),
        ).fetchall()
        order_status_counts = connection.execute(
            'SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status'
        ).fetchall()
        recent_orders = connection.execute(
            '''SELECT id, customer_name, email, total_cents, status, payment_method,
                      payment_status, payment_instructions, created_at
               FROM orders ORDER BY created_at DESC, id DESC LIMIT 8'''
        ).fetchall()
        recent_order_items = {order['id']: [] for order in recent_orders}
        if recent_orders:
            order_ids = list(recent_order_items)
            placeholders = ','.join('?' for _ in order_ids)
            for item in connection.execute(
                f'''SELECT order_id, product_name, quantity FROM order_items
                    WHERE order_id IN ({placeholders}) ORDER BY order_id DESC, id''', order_ids
            ).fetchall():
                recent_order_items[item['order_id']].append(item)
        top_products = connection.execute(
            '''SELECT oi.product_name AS name, SUM(oi.quantity) AS units_sold,
                      SUM(oi.unit_price_cents * oi.quantity) AS value_cents
               FROM order_items oi JOIN orders o ON o.id = oi.order_id
               WHERE o.status <> 'Cancelled' AND o.payment_status = 'Paid'
               GROUP BY oi.product_name ORDER BY value_cents DESC LIMIT 5'''
        ).fetchall()
        top_categories = connection.execute(
            '''SELECT p.category, SUM(oi.unit_price_cents * oi.quantity) AS order_value_cents
               FROM order_items oi JOIN orders o ON o.id = oi.order_id
               JOIN products p ON p.id = oi.product_id
               WHERE o.status <> 'Cancelled' AND o.payment_status = 'Paid'
               GROUP BY p.category ORDER BY order_value_cents DESC LIMIT 5'''
        ).fetchall()
        top_customers = connection.execute(
            '''SELECT LOWER(email) AS email, MAX(customer_name) AS customer_name,
                      COUNT(*) AS order_count, SUM(total_cents) AS paid_value_cents
               FROM orders WHERE status <> 'Cancelled' AND payment_status = 'Paid'
               GROUP BY LOWER(email) ORDER BY paid_value_cents DESC LIMIT 5'''
        ).fetchall()
        low_stock_products = connection.execute(
            '''SELECT id, name, stock, unit_label FROM products
               WHERE active = 1 AND stock <= 5 ORDER BY stock, name LIMIT 8'''
        ).fetchall()
        recent_requests = connection.execute(
            '''SELECT id, customer_name, request_type, device_type, brand, status, created_at
               FROM device_requests ORDER BY created_at DESC, id DESC LIMIT 5'''
        ).fetchall()
        database_backend = 'PostgreSQL' if connection.is_postgres else 'SQLite'
        return {
            'totals': dict(totals),
            'sales_rows': sales_rows,
            'period_unit': period_unit,
            'period_count': period_count,
            'order_status_counts': order_status_counts,
            'recent_orders': recent_orders,
            'recent_order_items': recent_order_items,
            'top_products': top_products,
            'top_categories': top_categories,
            'top_customers': top_customers,
            'low_stock_products': low_stock_products,
            'recent_requests': recent_requests,
            'database_backend': database_backend,
        }


def get_admin_orders(status='', search=''):
    conditions, parameters = [], []
    if status == 'active':
        conditions.append("status <> 'Cancelled'")
    elif status in ORDER_STATUSES:
        conditions.append('status = ?')
        parameters.append(status)
    if search:
        pattern = f'%{search.lower()}%'
        conditions.append('(LOWER(customer_name) LIKE ? OR LOWER(email) LIKE ? OR CAST(id AS TEXT) LIKE ?)')
        parameters.extend((pattern, pattern, pattern))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ''
    with get_db_connection() as connection:
        orders = connection.execute(
            f'''SELECT id, customer_name, email, address, total_cents, status,
                       payment_method, payment_status, payment_instructions, created_at
                FROM orders {where} ORDER BY created_at DESC, id DESC LIMIT 200''', parameters
        ).fetchall()
        order_ids = [order['id'] for order in orders]
        items_by_order = {order_id: [] for order_id in order_ids}
        if order_ids:
            placeholders = ','.join('?' for _ in order_ids)
            items = connection.execute(
                f'''SELECT order_id, product_name, unit_price_cents, quantity FROM order_items
                    WHERE order_id IN ({placeholders}) ORDER BY order_id DESC, id''', order_ids
            ).fetchall()
            for item in items:
                items_by_order[item['order_id']].append(item)
        return orders, items_by_order


class InventoryUnavailableError(Exception):
    pass


def update_order_status(order_id, status):
    if status not in ORDER_STATUSES:
        return 'not_found'
    try:
        with get_db_connection() as connection:
            # Take a write lock before reading inventory_applied so concurrent
            # manager submissions for the same order cannot apply stock twice.
            locked_order = connection.execute(
                'UPDATE orders SET inventory_applied = inventory_applied WHERE id = ?',
                (order_id,),
            )
            if locked_order.rowcount != 1:
                return 'not_found'
            order = connection.execute(
                'SELECT inventory_applied, payment_status FROM orders WHERE id = ?', (order_id,)
            ).fetchone()
            if status in PAYMENT_REQUIRED_ORDER_STATUSES and order['payment_status'] != 'Paid':
                return 'payment_required'
            should_apply = status not in {'Request received', 'Cancelled'}
            applied = bool(order['inventory_applied'])
            if should_apply and not applied:
                items = connection.execute(
                    '''SELECT oi.product_id, oi.quantity FROM order_items oi
                       JOIN products p ON p.id = oi.product_id
                       WHERE oi.order_id = ? AND p.unit_label = 'each' ''', (order_id,)
                ).fetchall()
                for item in items:
                    cursor = connection.execute(
                        'UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?',
                        (item['quantity'], item['product_id'], item['quantity']),
                    )
                    if cursor.rowcount != 1:
                        raise InventoryUnavailableError
                applied = True
            elif not should_apply and applied:
                items = connection.execute(
                    '''SELECT oi.product_id, oi.quantity FROM order_items oi
                       JOIN products p ON p.id = oi.product_id
                       WHERE oi.order_id = ? AND p.unit_label = 'each' ''', (order_id,)
                ).fetchall()
                for item in items:
                    connection.execute('UPDATE products SET stock = stock + ? WHERE id = ?', (item['quantity'], item['product_id']))
                applied = False
            connection.execute(
                'UPDATE orders SET status = ?, inventory_applied = ? WHERE id = ?',
                (status, int(applied), order_id),
            )
            return 'updated'
    except InventoryUnavailableError:
        return 'insufficient_stock'


def update_order_payment_status(order_id, payment_status):
    if payment_status not in ORDER_PAYMENT_STATUSES:
        return 'not_found'
    with get_db_connection() as connection:
        # Serialize payment edits with order-status changes so the manager
        # cannot leave a fulfilled order unpaid through concurrent updates.
        locked_order = connection.execute(
            'UPDATE orders SET payment_status = payment_status WHERE id = ?',
            (order_id,),
        )
        if locked_order.rowcount != 1:
            return 'not_found'
        order = connection.execute(
            'SELECT status FROM orders WHERE id = ?', (order_id,)
        ).fetchone()
        if order['status'] == 'Cancelled':
            return 'not_found'
        if payment_status == 'Paid' and order['status'] not in {
            'Confirmed', 'Preparing', 'Ready for pickup', 'Completed',
        }:
            return 'confirm_order_first'
        if payment_status == 'Unpaid' and order['status'] in PAYMENT_REQUIRED_ORDER_STATUSES:
            return 'fulfillment_requires_payment'
        if payment_status == 'Paid':
            cursor = connection.execute(
                "UPDATE orders SET payment_status = ? WHERE id = ? AND status IN ('Confirmed', 'Preparing', 'Ready for pickup', 'Completed')",
                (payment_status, order_id),
            )
        else:
            cursor = connection.execute(
                "UPDATE orders SET payment_status = ? WHERE id = ? AND status <> 'Cancelled'",
                (payment_status, order_id),
            )
        return 'updated' if cursor.rowcount > 0 else 'not_found'


def get_admin_order(order_id):
    with get_db_connection() as connection:
        return connection.execute(
            '''SELECT id, customer_name, email, total_cents, status, payment_method,
                      payment_status, payment_instructions FROM orders WHERE id = ?''',
            (order_id,),
        ).fetchone()


def save_order_payment_instructions(order_id, instructions):
    with get_db_connection() as connection:
        cursor = connection.execute(
            "UPDATE orders SET payment_instructions = ? WHERE id = ? AND status <> 'Cancelled'",
            (instructions, order_id),
        )
        return cursor.rowcount > 0


def get_admin_products():
    with get_db_connection() as connection:
        return connection.execute('SELECT * FROM products ORDER BY active DESC, category, name').fetchall()


def get_admin_product(product_id):
    with get_db_connection() as connection:
        return connection.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()


def save_admin_product(product_id, name, description, price_cents, emoji, stock, category, unit_label, pricing_kind):
    with get_db_connection() as connection:
        if product_id:
            cursor = connection.execute(
                '''UPDATE products SET name = ?, description = ?, price_cents = ?, emoji = ?,
                   stock = ?, category = ?, unit_label = ?, pricing_kind = ? WHERE id = ?''',
                (name, description, price_cents, emoji, stock, category, unit_label, pricing_kind, product_id),
            )
            return cursor.rowcount > 0
        _insert_id(
            connection,
            '''INSERT INTO products (name, description, price_cents, emoji, stock, active, category, unit_label, pricing_kind)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)''',
            (name, description, price_cents, emoji, stock, category, unit_label, pricing_kind),
        )
        return True


def set_admin_product_active(product_id, active):
    with get_db_connection() as connection:
        cursor = connection.execute('UPDATE products SET active = ? WHERE id = ?', (1 if active else 0, product_id))
        return cursor.rowcount > 0


def get_admin_customers(search='', page=1, per_page=50):
    # Aggregate and paginate in the database so the manager page stays bounded.
    page = max(1, int(page))
    per_page = max(1, min(100, int(per_page)))
    offset = (page - 1) * per_page
    pattern = f'%{search.strip().lower()}%'
    source_cte = '''
        WITH source_rows AS (
          SELECT email, first_name AS customer_name, 0 AS order_count,
                 0 AS order_value_cents, created_at AS last_activity
          FROM users
          UNION ALL
          SELECT email, customer_name, 1,
                 CASE WHEN status <> 'Cancelled' AND payment_status = 'Paid' THEN total_cents ELSE 0 END,
                 created_at
          FROM orders
          UNION ALL
          SELECT email, customer_name, 0, 0, created_at
          FROM device_requests
        ), grouped_customers AS (
          SELECT LOWER(email) AS email, MAX(customer_name) AS customer_name,
                 SUM(order_count) AS order_count, SUM(order_value_cents) AS order_value_cents,
                 MAX(last_activity) AS last_activity
          FROM source_rows GROUP BY LOWER(email)
        ), filtered_customers AS (
          SELECT * FROM grouped_customers
          WHERE LOWER(email) LIKE ? OR LOWER(customer_name) LIKE ?
        )
    '''
    parameters = (pattern, pattern)
    with get_db_connection() as connection:
        total = connection.execute(
            source_cte + 'SELECT COUNT(*) AS total FROM filtered_customers', parameters
        ).fetchone()['total']
        rows = connection.execute(
            source_cte + '''SELECT email, customer_name, order_count, order_value_cents, last_activity
                            FROM filtered_customers
                            ORDER BY last_activity DESC, email
                            LIMIT ? OFFSET ?''',
            parameters + (per_page, offset),
        ).fetchall()
        return rows, int(total)
