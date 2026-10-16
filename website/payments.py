import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


PAYMENT_METHODS = (
    ('cash_pickup', 'Cash at pickup'),
    ('cash_delivery', 'Cash on delivery'),
    ('telebirr', 'Telebirr transfer'),
    ('cbe', 'CBE transfer'),
    ('abay', 'Abay Bank transfer'),
    ('boa', 'Bank of Abyssinia (BOA) transfer'),
)

PAYMENT_METHOD_LABELS = dict(PAYMENT_METHODS)
PAYMENT_METHOD_LABELS['transfer_after_confirmation'] = 'Bank or mobile transfer after confirmation'
PAYMENT_METHOD_LABELS['chapa'] = 'Online payment via Chapa (Telebirr, CBE, and supported cards/banks)'
TRANSFER_PAYMENT_METHODS = frozenset({'telebirr', 'cbe', 'abay', 'boa', 'transfer_after_confirmation'})

# These are customer-facing transfer destinations supplied by the shop owner.
# They support manual transfers only; no payment gateway is connected.
PAYMENT_DETAILS = {
    'telebirr': {
        'provider': 'Telebirr',
        'account_label': 'Telebirr number',
        'account_number': '0909847775',
        'account_holder': 'Yazezew Kassa',
    },
    'cbe': {
        'provider': 'Commercial Bank of Ethiopia (CBE)',
        'account_label': 'CBE account number',
        'account_number': '1000226159111',
        'account_holder': 'Yazezew Kassa',
    },
    'abay': {
        'provider': 'Abay Bank',
        'account_label': 'Abay Bank account number',
        'account_number': '2931017252653013',
        'account_holder': 'Yazezew Kassa',
    },
    'boa': {
        'provider': 'Bank of Abyssinia (BOA)',
        'account_label': 'BOA account number',
        'account_number': '9958396',
        'account_holder': 'Yazezew Kassa',
    },
}


def payment_method_label(method):
    return PAYMENT_METHOD_LABELS.get(method, 'Payment preference')


class ChapaPaymentError(RuntimeError):
    pass


def _chapa_request(path, secret_key, payload=None):
    if not secret_key:
        raise ChapaPaymentError('Online payment is not configured.')

    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {secret_key}',
    }
    if body is not None:
        headers['Content-Type'] = 'application/json'
    request = Request(
        f'https://api.chapa.co/v1/{path.lstrip("/")}',
        data=body,
        headers=headers,
        method='POST' if body is not None else 'GET',
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ChapaPaymentError('The payment provider could not process the request.') from error
    if not isinstance(result, dict):
        raise ChapaPaymentError('The payment provider returned an invalid response.')
    return result


def start_chapa_checkout(secret_key, *, amount_cents, email, first_name, last_name,
                         tx_ref, callback_url, return_url, items):
    payload = {
        'amount': f'{amount_cents // 100}.{amount_cents % 100:02d}',
        'currency': 'ETB',
        'email': email,
        'first_name': first_name,
        'last_name': last_name,
        'tx_ref': tx_ref,
        'callback_url': callback_url,
        'return_url': return_url,
        'customization': {
            'title': 'Brothers-Online-Work',
            'description': f'Order payment {tx_ref}',
        },
        'meta': {
            'payment_reason': 'Payment for confirmed fixed-price goods or services',
            'invoices': items,
        },
    }
    result = _chapa_request('transaction/initialize', secret_key, payload)
    data = result.get('data')
    checkout_url = data.get('checkout_url') if isinstance(data, dict) else None
    parsed = urlparse(checkout_url or '')
    host = (parsed.hostname or '').lower()
    if (result.get('status') != 'success' or parsed.scheme != 'https'
            or not (host == 'chapa.co' or host.endswith('.chapa.co'))):
        raise ChapaPaymentError('The payment provider did not return a valid checkout link.')
    return checkout_url


def verify_chapa_checkout(secret_key, tx_ref):
    return _chapa_request(f'transaction/verify/{quote(tx_ref, safe="")}', secret_key)
