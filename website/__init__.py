
import os

from flask import Flask, jsonify, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .translations import get_language, translate


def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.get('/service-worker.js')
    def service_worker():
        response = send_from_directory(
            app.static_folder,
            'service-worker.js',
            mimetype='application/javascript',
        )
        response.headers['Service-Worker-Allowed'] = '/'
        response.headers['Cache-Control'] = 'no-cache'
        return response
    configured_secret = os.environ.get('SECRET_KEY', '').strip()
    if os.environ.get('REQUIRE_SECRET_KEY', '').strip().lower() in {'1', 'true', 'yes', 'on'} and not configured_secret:
        raise RuntimeError('SECRET_KEY must be configured before starting this production service.')
    app.config['SECRET_KEY'] = configured_secret or os.urandom(32)
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 14
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
    app.config['ADMIN_PANEL_PASSWORD'] = os.environ.get('ADMIN_PANEL_PASSWORD', '').strip()
    app.jinja_env.filters['money'] = lambda cents: (
        f"ብር {cents / 100:,.2f}" if get_language() == 'am' else f"ETB {cents / 100:,.2f}"
    )
    from .payments import payment_method_label
    app.jinja_env.filters['payment_method'] = lambda method: translate(payment_method_label(method))
    app.jinja_env.globals['tr'] = translate
    app.jinja_env.globals['get_language'] = get_language
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if os.environ.get('REQUIRE_DATABASE_URL', '').strip().lower() in {'1', 'true', 'yes', 'on'} and not database_url:
        raise RuntimeError('DATABASE_URL must be configured before starting this production service.')
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

    @app.get('/health')
    def health():
        from .models import get_db_connection

        try:
            with get_db_connection() as connection:
                connection.execute('SELECT 1').fetchone()
        except Exception:
            app.logger.exception('The database health check failed.')
            return jsonify({'status': 'unavailable'}), 503
        return jsonify({'status': 'ok'})

    from .models import init_db
    with app.app_context():
        init_db()

    return app
