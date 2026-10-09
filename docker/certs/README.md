# Local Docker CA certificates

Put a PEM-encoded trusted organization root certificate here with a `.crt`
extension when the host network intercepts TLS. The API imports it into the
system CA store; browser runners also add it to Chromium's NSS trust database.

Do not put private keys, server certificates, or untrusted certificates here.
The `.crt` files are ignored by Git because trust roots can be machine-specific.
