
import os

from flask import Flask

from .translations import get_language, translate


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32)
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', '').strip()
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', '587'))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '').strip()
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME']).strip()
    app.config['CONTACT_RECIPIENT'] = os.environ.get('CONTACT_RECIPIENT', 'yazezewkassa@gmail.com').strip()
    app.jinja_env.filters['money'] = lambda cents: (
        f"ብር {cents / 100:,.2f}" if get_language() == 'am' else f"ETB {cents / 100:,.2f}"
    )
    app.jinja_env.globals['tr'] = translate
    app.jinja_env.globals['get_language'] = get_language
    os.makedirs(app.instance_path, exist_ok=True)
    app.config['DATABASE'] = os.path.join(app.instance_path, 'users.sqlite3')
    from .views import views
    from .authss import auth
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/auth')

    from .models import init_db
    with app.app_context():
        init_db()

    return app
