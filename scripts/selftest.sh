#!/bin/bash
# Syntax + file + config-generation test. Does not install packages or touch /etc.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FAIL=0

ok() { echo "  OK  $*"; }
bad() { echo "  FAIL  $*"; FAIL=1; }

echo "== bash -n"
bash -n "$ROOT/install.sh" && ok install.sh || bad install.sh
bash -n "$ROOT/uninstall.sh" && ok uninstall.sh || bad uninstall.sh
bash -n "$ROOT/scripts/selftest.sh" && ok selftest.sh || bad selftest.sh

echo "== required files"
while IFS= read -r f; do
  if [[ -f "$ROOT/$f" ]]; then ok "$f"; else bad "missing $f"; fi
done << 'EOF'
install.sh
uninstall.sh
LICENSE
README.md
.gitignore
.gitattributes
panel/app.py
panel/templates/login.html
panel/templates/index.html
panel/templates/settings.html
panel/static/style.css
panel/ppp-ip-up
panel/ppp-ip-down
panel/ikev2-l2tp-gui.service
EOF

echo "== no provider / host leftovers"
if grep -RInE 'arvan|130\.185|nhaghbayanpsk|arv\.nhaghbayan|HpBayan|eu-west|\b0114\b' --include='*.sh' --include='*.py' --include='*.md' --include='*.html' --include='*.css' --include='*.service' "$ROOT" | grep -v selftest.sh; then
  bad "found host-specific strings"
else
  ok "no host-specific strings"
fi
if grep -RInE '(^|[^a-z])navid([^a-z]|$)|navid[0-9]' --include='*.sh' --include='*.py' --include='*.md' --include='*.html' --include='*.css' --include='*.service' "$ROOT" | grep -v selftest.sh | grep -v navidhaghpanah; then
  bad "found vpn username leftovers"
else
  ok "no vpn username leftovers"
fi

echo "== python compile"
if command -v python3 >/dev/null; then
  python3 -m py_compile "$ROOT/panel/app.py" && ok "app.py compiles" || bad "app.py compile"
else
  echo "  skip python3 not installed"
fi

echo "== generate sample configs in temp dir"
TMP=$(mktemp -d /tmp/ikev2-l2tp-gui-test.XXXXXX)
DOMAIN=vpn.example.com
PUBLIC_IP=203.0.113.10
PSK=ExamplePskValue
PANEL_USER=admin
PANEL_PASS=ExamplePass1
VPN_USER=user1
VPN_PASS=ExamplePass1
HAVE_SSL=0
mkdir -p "$TMP/app" "$TMP/cfg" "$TMP/data" "$TMP/nginx" "$TMP/ipsec" "$TMP/ppp"
cp -a "$ROOT/panel/." "$TMP/app/"

cat >"$TMP/ipsec/ipsec.conf" << EOF
conn L2TP-PSK
  leftid=${PUBLIC_IP}
conn IKEv2-EAP
  leftid=@${DOMAIN}
  rightdns=9.9.9.9,1.0.0.1
EOF
grep -q "$PUBLIC_IP" "$TMP/ipsec/ipsec.conf" && ok "ipsec.conf leftid IP" || bad "ipsec.conf IP"
grep -q "@${DOMAIN}" "$TMP/ipsec/ipsec.conf" && ok "ipsec.conf leftid domain" || bad "ipsec.conf domain"

cat >"$TMP/nginx/site.conf" << EOF
server_name ${DOMAIN};
ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
proxy_pass http://127.0.0.1:8765;
EOF
grep -q vpn.example.com "$TMP/nginx/site.conf" && ok "nginx server_name" || bad "nginx"

if command -v python3 >/dev/null; then
  python3 - << PY
import json, os, secrets, sys
from pathlib import Path
try:
    from werkzeug.security import generate_password_hash
except ImportError:
    print("  skip werkzeug not installed")
    sys.exit(0)
cfg_dir = Path("$TMP/cfg")
data_dir = Path("$TMP/data")
cfg = {
  "domain": "$DOMAIN",
  "public_ip": "$PUBLIC_IP",
  "psk": "$PSK",
  "dns": ["9.9.9.9", "1.0.0.1"],
  "https": False,
}
(cfg_dir / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
admin = {
  "user": "$PANEL_USER",
  "password": generate_password_hash("$PANEL_PASS"),
  "secret": secrets.token_hex(32),
}
(cfg_dir / "admin.json").write_text(json.dumps(admin, indent=2) + "\n")
users = {"user1": {"password": "$VPN_PASS", "expires": "2027-01-01", "quota_gb": 50, "used_bytes": 0, "created": "2026-08-24", "enabled": True}}
(data_dir / "users.json").write_text(json.dumps(users, indent=2) + "\n")
cfg2 = json.loads((cfg_dir / "config.json").read_text())
assert cfg2["domain"] == "vpn.example.com"
assert "nhaghbayan" not in json.dumps(cfg2)
print("  OK  python config json")
PY
fi

echo "== Farsi UI strings"
for s in 'داشبورد' 'افراد آنلاین' 'پردازنده' 'حافظه' 'تاریخ انقضا' 'کلید مشترک' 'ورود'; do
  if grep -q "$s" "$ROOT/panel/templates/"*.html; then ok "ui: $s"; else bad "ui missing $s"; fi
done

rm -rf "$TMP"
echo
if [[ "$FAIL" -ne 0 ]]; then
  echo "SELFTEST FAILED"
  exit 1
fi
echo "SELFTEST PASSED"
