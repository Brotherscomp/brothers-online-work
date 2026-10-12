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
