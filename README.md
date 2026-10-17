# Brothers-Online-Work Flask store

This is the existing Flask web app. The manager area lives at `/manager` and includes a live overview, order and payment-status management, products and stock, customer lookup, device requests, and system status. Customer accounts include email confirmation, sign-in, sign-out, order history, and password recovery.

The checkout accepts Telebirr as the payment preference. Transfer instructions are emailed after order confirmation; manual transfers are not automatically verified.

See [EMAIL_SETUP.md](EMAIL_SETUP.md) for SMTP setup and [OPERATIONS.md](OPERATIONS.md) for database, backup, credential, and manual deployment guidance.
