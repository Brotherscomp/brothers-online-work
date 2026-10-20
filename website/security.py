import hashlib
import hmac
import time
from urllib.parse import urlsplit

from flask import abort, current_app, request

from .models import consume_rate_limit


def is_safe_local_redirect(target):
    if not isinstance(target, str) or not target.startswith('/'):
        return False
    if target.startswith('//') or '\\' in target or any(ord(char) < 32 for char in target):
        return False
    parsed = urlsplit(target)
    return not parsed.scheme and not parsed.netloc and parsed.path.startswith('/')


def enforce_rate_limit(scope, max_requests, window_seconds):
    """Apply a shared database-backed limit without storing raw client IPs."""
    secret_key = current_app.config['SECRET_KEY']
    if isinstance(secret_key, str):
        secret_key = secret_key.encode('utf-8')
    source = request.remote_addr or 'unknown'
    bucket_key = hmac.new(
        secret_key,
        f'{scope}:{source}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    if not consume_rate_limit(bucket_key, max_requests, window_seconds, int(time.time())):
        abort(429, description='Too many requests. Please wait before trying again.')
