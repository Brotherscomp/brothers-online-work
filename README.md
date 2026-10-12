# Brothers-Online-Work Flask store

This is the existing Flask web app. The manager area lives at `/manager` and includes a live overview, order and payment-status management, products and stock, customer lookup, device requests, and system status. Customer accounts include email confirmation, sign-in, sign-out, order history, and password recovery.

The checkout records cash pickup, cash delivery, Telebirr, CBE, Abay Bank, or Bank of Abyssinia (BOA) as the customer's payment preference. It does not take an online payment. Transfer instructions are entered by the manager and emailed after order confirmation.

See [EMAIL_SETUP.md](EMAIL_SETUP.md) for SMTP setup and [OPERATIONS.md](OPERATIONS.md) for database, backup, credential, and manual deployment guidance.
