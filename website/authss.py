import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .models import create_user, find_user_by_email
from .translations import translate

auth = Blueprint('auth', __name__)


@auth.route('/Hello')
def hello():
    return '<h1>Hello</h1>'


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = find_user_by_email(email) if email and password else None

        if user is None or not check_password_hash(user['password_hash'], password):
            flash(translate('Email or password is incorrect.'), 'error')
        else:
            language = session.get('language', 'en')
            session.clear()
            session['language'] = language
            session['user_id'] = user['id']
            session['first_name'] = user['first_name']
            flash(translate('Login successful.'), 'success')
            return redirect(url_for('views.home'))

    return render_template('auth/login.html')


@auth.route('/logout', methods=['GET', 'POST'])
def logout():
    if request.method == 'POST':
        language = session.get('language', 'en')
        session.clear()
        session['language'] = language
        flash(translate('You have been logged out.'), 'success')
        return redirect(url_for('views.home'))
    if not session.get('user_id'):
        return redirect(url_for('views.home'))
    return render_template('auth/logout.html')


@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        first_name = request.form.get('first_name', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not email or not first_name or not password:
            flash(translate('Please complete all fields.'), 'error')
        elif password != confirm_password:
            flash(translate('Passwords do not match.'), 'error')
        elif len(password) < 8:
            flash(translate('Password must be at least 8 characters.'), 'error')
        elif find_user_by_email(email):
            flash(translate('An account with that email already exists.'), 'error')
        else:
            try:
                create_user(email, first_name, generate_password_hash(password))
            except sqlite3.IntegrityError:
                flash(translate('An account with that email already exists.'), 'error')
            else:
                flash(translate('Account created. Please log in.'), 'success')
                return redirect(url_for('auth.login'))

    return render_template('auth/sign_up.html')
