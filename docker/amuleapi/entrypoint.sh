#!/usr/bin/env bash
set -euo pipefail
umask 077

CONFIG_DIR=/data/config
EC_PASSWORD_FILE=/run/secrets/amule_ec_password
ADMIN_PASSWORD_FILE=/run/secrets/amuleapi_admin_password

for secret_file in "$EC_PASSWORD_FILE" "$ADMIN_PASSWORD_FILE"; do
    if [[ ! -r "$secret_file" ]]; then
        echo "Required Docker secret is unavailable: $secret_file" >&2
        exit 64
    fi
done

EC_PASSWORD=$(<"$EC_PASSWORD_FILE")
ADMIN_PASSWORD=$(<"$ADMIN_PASSWORD_FILE")
if [[ -z "$EC_PASSWORD" || -z "$ADMIN_PASSWORD" ]]; then
    echo "aMule secrets must not be empty" >&2
    exit 64
fi

install -d -o amule -g amule -m 700 "$CONFIG_DIR" /data/incoming /data/temp
if [[ ! -f "$CONFIG_DIR/amule.conf" ]]; then
    gosu amule amuled -c "$CONFIG_DIR" -o -i >/dev/null 2>&1 || true
fi

EC_PASSWORD_MD5=$(printf '%s' "$EC_PASSWORD" | md5sum | cut -d' ' -f1 | tr 'a-f' 'A-F')
gosu amule python3 - "$CONFIG_DIR/amule.conf" "$EC_PASSWORD_MD5" <<'PY'
import re
import sys

path, password = sys.argv[1:]
content = open(path).read()
for key, value in (
    ("AcceptExternalConnections", "1"),
    ("TCPPort", "4662"),
    ("UDPPort", "4672"),
    ("ECPort", "4712"),
    ("ECPassword", password),
    ("IncomingDir", "/data/incoming"),
    ("TempDir", "/data/temp"),
):
    if re.search(rf"^{key}=.*$", content, flags=re.MULTILINE):
        content = re.sub(rf"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}\n"
open(path, "w").write(content)
PY

gosu amule amuleapi --config-dir="$CONFIG_DIR" --set-admin-pass="$ADMIN_PASSWORD"
timeout 3 gosu amule amuleapi --config-dir="$CONFIG_DIR" --password="$EC_PASSWORD" \
    --http-port=4713 >/dev/null 2>&1 || true
gosu amule python3 - "$CONFIG_DIR/amuleapi.conf" <<'PY'
import re
import sys

path = sys.argv[1]
content = open(path).read()
content = re.sub(r"^BindAddress=.*$", "BindAddress=0.0.0.0", content, flags=re.MULTILINE)
content = re.sub(r"^Port=.*$", "Port=4713", content, count=1, flags=re.MULTILINE)
open(path, "w").write(content)
PY
chown amule:amule "$CONFIG_DIR/amule.conf" "$CONFIG_DIR/amuleapi.conf"
chmod 600 "$CONFIG_DIR/amule.conf" "$CONFIG_DIR/amuleapi.conf"

gosu amule amuled -c "$CONFIG_DIR" -o >"$CONFIG_DIR/amuled.log" 2>&1 &
for _ in $(seq 1 30); do
    if (echo > /dev/tcp/127.0.0.1/4712) 2>/dev/null; then
        break
    fi
    sleep 1
done
exec gosu amule amuleapi --config-dir="$CONFIG_DIR" --host=127.0.0.1 --port=4712 \
    --password="$EC_PASSWORD" --http-port=4713 --bind=0.0.0.0 --no-log-file
