
import os

from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

from .translations import get_language, translate


def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=14)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
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
    app.config['ADMIN_PANEL_PASSWORD'] = os.environ.get('ADMIN_PANEL_PASSWORD', '')
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
    database_url = os.environ.get('DATABASE_URL', '').strip()
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

    from .models import get_db_connection

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
