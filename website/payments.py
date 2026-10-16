import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PAYMENT_METHODS = (
    ("cash_pickup", "Cash at pickup"),
    ("cash_delivery", "Cash on delivery"),
    ("telebirr", "Pay with Telebirr"),
)

PAYMENT_METHOD_LABELS = dict(PAYMENT_METHODS)
TRANSFER_PAYMENT_METHODS = frozenset({"telebirr"})

PAYMENT_DETAILS = {
    "telebirr": {
        "provider": "Telebirr",
        "account_label": "Telebirr number",
        "account_number": "0909847775",
        "account_holder": "Yazezew Kassa",
    },
}


def payment_method_label(method):
    return PAYMENT_METHOD_LABELS.get(method, "Payment preference")


class TelebirrPaymentError(RuntimeError):
    pass


def _telebirr_request(url, payload, headers=None):
    body = json.dumps(payload).encode("utf-8")
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        request_headers.update(headers)

    request = Request(
        url,
        data=body,
        headers=request_headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise TelebirrPaymentError(
            "Telebirr could not process the request."
        ) from error

    if not isinstance(result, dict):
        raise TelebirrPaymentError(
            "Telebirr returned an invalid response."
        )

    return result


def start_telebirr_checkout(
    *,
    amount_cents,
    order_id,
    notify_url,
    return_url,
    app_id,
    app_key,
    public_key,
    short_code,
    receive_name,
):
    """
    Start a Telebirr checkout using the Telebirr H5 integration helper.

    Install the helper with:
        pip install telebirr

    Credentials and signing details must match your merchant account.
    """
    if amount_cents <= 0:
        raise TelebirrPaymentError("Payment amount must be positive.")

    if not all(
        [app_id, app_key, public_key, short_code, notify_url, return_url]
    ):
        raise TelebirrPaymentError(
            "Telebirr merchant configuration is incomplete."
        )

    try:
        from telebirr import Telebirr
        import secrets

        payment = Telebirr(
            app_id=app_id,
            app_key=app_key,
            public_key=public_key,
            notify_url=notify_url,
            receive_name=receive_name,
            return_url=return_url,
            short_code=short_code,
            subject=f"Order {order_id}",
            timeout_express="30",
            total_amount=f"{amount_cents / 100:.2f}",
            nonce=secrets.token_hex(16),
            out_trade_no=str(order_id),
        )

        result = payment.send_request()

    except Exception as error:
        raise TelebirrPaymentError(
            "Unable to initialize Telebirr checkout."
        ) from error

    if not isinstance(result, dict) or str(result.get("code")) != "0":
        raise TelebirrPaymentError(
            "Telebirr did not accept the payment request."
        )

    data = result.get("data")
    checkout_url = data.get("toPayUrl") if isinstance(data, dict) else None
    parsed = urlparse(checkout_url or "")

    if parsed.scheme != "https" or not parsed.hostname:
        raise TelebirrPaymentError(
            "Telebirr returned an invalid checkout URL."
        )

    return checkout_url
