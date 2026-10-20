
import os

from datetime import timedelta
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, jsonify, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from .translations import get_language, translate


def create_app():
    load_dotenv()
    app = Flask(__name__)
    app_environment = os.environ.get('APP_ENV', 'development').strip().lower()
    secret_key = os.environ.get('SECRET_KEY', '').strip()
    database_url = os.environ.get('DATABASE_URL', '').strip()
    public_base_url = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    secure_cookie = os.environ.get('SESSION_COOKIE_SECURE', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
    manager_password = os.environ.get('ADMIN_PANEL_PASSWORD', '')

    if app_environment in {'production', 'prod'}:
        missing_settings = []
        if len(secret_key) < 32:
            missing_settings.append('SECRET_KEY (at least 32 characters)')
        if not database_url:
            missing_settings.append('DATABASE_URL (PostgreSQL is required)')
        parsed_public_url = urlsplit(public_base_url)
        try:
            parsed_public_url.port
            public_url_valid = (
                parsed_public_url.scheme == 'https'
                and bool(parsed_public_url.hostname)
                and not parsed_public_url.username
                and not parsed_public_url.password
                and not parsed_public_url.query
                and not parsed_public_url.fragment
                and parsed_public_url.path in {'', '/'}
            )
        except ValueError:
            public_url_valid = False
        if not public_url_valid:
            missing_settings.append('PUBLIC_BASE_URL (the public HTTPS origin)')
        if not secure_cookie:
            missing_settings.append('SESSION_COOKIE_SECURE=true')
        if len(manager_password) < 20 or len(manager_password) > 1024:
            missing_settings.append('ADMIN_PANEL_PASSWORD (20 to 1024 characters)')
        if missing_settings:
            raise RuntimeError(
                'Production configuration is incomplete: ' + ', '.join(missing_settings)
            )

    app.config['APP_ENV'] = app_environment
    app.config['PUBLIC_BASE_URL'] = public_base_url
    app.config['SECRET_KEY'] = secret_key or os.urandom(32)
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = secure_cookie
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=14)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', '').strip()
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', '587'))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '').strip()
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME']).strip()
    app.config['CONTACT_RECIPIENT'] = os.environ.get('CONTACT_RECIPIENT', 'yazezewkassa@gmail.com').strip()
    app.config['DEVICE_REQUEST_RECIPIENT'] = os.environ.get(
        'DEVICE_REQUEST_RECIPIENT', app.config['CONTACT_RECIPIENT']
    ).strip()
    app.config['ADMIN_PANEL_PASSWORD'] = manager_password
    app.config['TELEBIRR_APP_ID'] = os.environ.get('TELEBIRR_APP_ID', '').strip()
    app.config['TELEBIRR_APP_KEY'] = os.environ.get('TELEBIRR_APP_KEY', '').strip()
    app.config['TELEBIRR_PUBLIC_KEY'] = os.environ.get('TELEBIRR_PUBLIC_KEY', '').strip()
    app.config['TELEBIRR_SHORT_CODE'] = os.environ.get('TELEBIRR_SHORT_CODE', '').strip()
    app.config['TELEBIRR_RECEIVE_NAME'] = os.environ.get('TELEBIRR_RECEIVE_NAME', '').strip()
    app.config['TELEBIRR_NOTIFY_URL'] = os.environ.get('TELEBIRR_NOTIFY_URL', '').strip()
    app.config['TELEBIRR_RETURN_URL'] = os.environ.get('TELEBIRR_RETURN_URL', '').strip()
    app.jinja_env.filters['money'] = lambda cents: (
        f"ብር {cents / 100:,.2f}" if get_language() == 'am' else f"ETB {cents / 100:,.2f}"
    )
    app.jinja_env.globals['tr'] = translate
    app.jinja_env.globals['get_language'] = get_language
    if database_url:
        app.config['DATABASE_URL'] = database_url
    else:
        database_path = os.environ.get('DATABASE_PATH') or os.path.join(app.instance_path, 'users.sqlite3')
        os.makedirs(os.path.dirname(os.path.abspath(database_path)), exist_ok=True)
        app.config['DATABASE'] = database_path
    from .views import views
    from .authss import auth, auth_csrf_token
    from .manager import manager, csrf_token
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/auth')
    app.register_blueprint(manager, url_prefix='/manager')
    app.jinja_env.globals['csrf_token'] = csrf_token
    app.jinja_env.globals['auth_csrf_token'] = auth_csrf_token

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; img-src 'self' data:; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'",
        )
        if request.is_secure:
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
        return response

    from .models import get_db_connection, get_user_session_version

    @app.before_request
    def invalidate_stale_customer_sessions():
        user_id = session.get('user_id')
        if not user_id or request.endpoint == 'static':
            return None
        current_version = get_user_session_version(user_id)
        if current_version is None or current_version != session.get('session_version', 0):
            for key in ('user_id', 'first_name', 'email', 'session_version'):
                session.pop(key, None)
        return None

    @app.get('/health')
    def health():
        try:
            with get_db_connection() as connection:
                connection.execute('SELECT 1').fetchone()
        except Exception:
            app.logger.exception('Health check could not reach the configured database.')
            return jsonify(status='unhealthy', database='unavailable'), 503
        return jsonify(status='ok', database='connected'), 200

    from .models import init_db
    with app.app_context():
        init_db()

    return app
