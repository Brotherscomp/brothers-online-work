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


def payment_method_label(method):
    return PAYMENT_METHOD_LABELS.get(method, 'Payment preference')
