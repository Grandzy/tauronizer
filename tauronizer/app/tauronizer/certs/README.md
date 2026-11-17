PGE DataHub's server, checked 2026-11-17, omits its intermediate certificate.
`certum-dv-tls-g2-r39.pem` is the public Certum DV TLS G2 R39 CA intermediate,
obtained via HTTPS from the CA's official repository:
https://certumdvtlsg2r39ca.repository.certum.pl/certumdvtlsg2r39ca.cer

It supplements Python's normal certifi chain building. Root trust, hostname
validation, signature validation and expiry checks remain enabled. It is not a
pinned PGE leaf certificate, and TLS verification is never disabled.
