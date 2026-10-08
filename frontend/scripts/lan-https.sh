#!/usr/bin/env bash
# HTTPS for the dev server on your LAN, so phones get the mic (TALK, wake
# word) and notifications, which browsers only allow on secure origins.
#
# Makes a local certificate authority once (certs/jarvis-ca.pem, valid 10
# years) and, on every run, a server certificate signed by it for
# localhost, this Mac's .local name and its current LAN addresses. Trust
# the CA once per device (see README, "Phone and other devices").
#
# Only needs the system openssl. Keys never leave certs/ (gitignored).
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p certs
chmod 700 certs

CA_KEY=certs/jarvis-ca-key.pem
CA=certs/jarvis-ca.pem
KEY=certs/lan-key.pem
CERT=certs/lan.pem

if [[ ! -f "$CA" || ! -f "$CA_KEY" ]]; then
  echo "Creating the Jarvis local CA (certs/jarvis-ca.pem)…"
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "$CA_KEY" -out "$CA" \
    -subj "/CN=Jarvis Local CA ($(scutil --get LocalHostName 2>/dev/null || hostname))" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
  chmod 600 "$CA_KEY"
fi

# Names this machine answers to; LAN addresses change between networks,
# so the certificate is reissued each run.
HOST="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
SAN="DNS:localhost,DNS:${HOST}.local,IP:127.0.0.1,IP:::1"
for ip in $(ifconfig | awk '/inet / && $2 != "127.0.0.1" { print $2 }'); do
  SAN="${SAN},IP:${ip}"
done

EXT="$(mktemp)"
trap 'rm -f "$EXT" certs/lan.csr' EXIT
cat > "$EXT" <<EOF
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${SAN}
EOF

openssl req -newkey rsa:2048 -sha256 -nodes -keyout "$KEY" -out certs/lan.csr \
  -subj "/CN=${HOST}.local" 2>/dev/null
# 397 days: Apple devices reject longer-lived server certificates.
openssl x509 -req -in certs/lan.csr -CA "$CA" -CAkey "$CA_KEY" -CAcreateserial \
  -out "$CERT" -days 397 -sha256 -extfile "$EXT" 2>/dev/null
chmod 600 "$KEY"

echo "HTTPS certificate for: ${SAN//DNS:/}" | sed 's/IP://g'
echo "Open https://${HOST}.local:3000 (or https://<LAN IP>:3000) on your phone."
