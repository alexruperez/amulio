#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR=/data/config
EC_PASSWORD=fixture-ec-password
ADMIN_PASSWORD=fixture-admin-password

mkdir -p "$CONFIG_DIR" /data/incoming /data/temp
if [[ ! -f "$CONFIG_DIR/amule.conf" ]]; then
    timeout 10 amuled -c "$CONFIG_DIR" -o -i >/dev/null 2>&1 || true
    pkill -f "amuled -c $CONFIG_DIR" 2>/dev/null || true
fi

EC_PASSWORD_MD5=$(printf '%s' "$EC_PASSWORD" | md5sum | cut -d' ' -f1 | tr 'a-f' 'A-F')
python3 - "$CONFIG_DIR/amule.conf" "$EC_PASSWORD_MD5" <<'PY'
import re
import sys

path, password = sys.argv[1:]
content = open(path).read()
for key, value in (
    ("AcceptExternalConnections", "1"),
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

amuleapi --config-dir="$CONFIG_DIR" --set-admin-pass="$ADMIN_PASSWORD"
timeout 3 amuleapi --config-dir="$CONFIG_DIR" --password="$EC_PASSWORD" --http-port=4713 \
    >/dev/null 2>&1 || true
pkill -f "amuleapi --config-dir=$CONFIG_DIR" 2>/dev/null || true
python3 - "$CONFIG_DIR/amuleapi.conf" <<'PY'
import re
import sys

path = sys.argv[1]
content = open(path).read()
content = re.sub(r"^BindAddress=.*$", "BindAddress=0.0.0.0", content, flags=re.MULTILINE)
content = re.sub(r"^Port=.*$", "Port=4713", content, count=1, flags=re.MULTILINE)
open(path, "w").write(content)
PY

amuled -c "$CONFIG_DIR" -o >"$CONFIG_DIR/amuled.log" 2>&1 &
for _ in $(seq 1 30); do
    if (echo > /dev/tcp/127.0.0.1/4712) 2>/dev/null; then
        break
    fi
    sleep 1
done
exec amuleapi --config-dir="$CONFIG_DIR" --host=127.0.0.1 --port=4712 --password="$EC_PASSWORD" \
    --http-port=4713 --bind=0.0.0.0 --no-log-file
