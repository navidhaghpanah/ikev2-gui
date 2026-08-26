#!/bin/bash
# IKEv2 GUI installer
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "in script bayad ba root ejra beshe: sudo bash install.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/opt/ikev2-l2tp-gui"
CFG_DIR="/etc/ikev2-l2tp-gui"
DATA_DIR="/var/lib/ikev2-l2tp-gui"

ask() {
  local prompt="$1" def="${2:-}" var
  if [[ -n "${NONINTERACTIVE:-}" ]]; then
    printf '%s\n' "$def"
    return
  fi
  if [[ -n "$def" ]]; then
    read -r -p "$prompt [$def]: " var || true
    printf '%s\n' "${var:-$def}"
  else
    read -r -p "$prompt: " var || true
    printf '%s\n' "$var"
  fi
}

ask_secret() {
  local prompt="$1" def="${2:-}" var
  if [[ -n "${NONINTERACTIVE:-}" ]]; then
    printf '%s\n' "$def"
    return
  fi
  read -r -s -p "$prompt: " var || true
  echo
  if [[ -z "$var" && -n "$def" ]]; then
    printf '%s\n' "$def"
  else
    printf '%s\n' "$var"
  fi
}

detect_ip() {
  hostname -I 2>/dev/null | awk '{print $1}'
  curl -4 -fsS --max-time 8 https://ifconfig.me 2>/dev/null || true
}

need=(
  "$SCRIPT_DIR/panel/app.py"
  "$SCRIPT_DIR/panel/templates/login.html"
  "$SCRIPT_DIR/panel/templates/index.html"
  "$SCRIPT_DIR/panel/templates/settings.html"
  "$SCRIPT_DIR/panel/static/style.css"
  "$SCRIPT_DIR/panel/ikev2-l2tp-gui.service"
  "$SCRIPT_DIR/panel/ppp-ip-up"
  "$SCRIPT_DIR/panel/ppp-ip-down"
  "$SCRIPT_DIR/clients/windows/Install-IKEv2.ps1"
  "$SCRIPT_DIR/clients/windows/Install-IKEv2.bat"
  "$SCRIPT_DIR/clients/windows/Check-Windows.bat"
  "$SCRIPT_DIR/clients/windows/RAHNAMA.txt"
  "$SCRIPT_DIR/clients/ios/IKEv2.mobileconfig"
  "$SCRIPT_DIR/clients/ios/RAHNAMA.txt"
)
for f in "${need[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "missing file: $f"
    exit 1
  fi
done

echo
echo "=========================================="
echo "   IKEv2 GUI  —  installer"
echo "=========================================="
echo

PUB_GUESS="$(curl -4 -fsS --max-time 8 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
IFACE="$(ip -4 route show default | awk '{print $5; exit}')"
IFACE="${IFACE:-eth0}"

DOMAIN="${DOMAIN:-$(ask 'Domain (mesle vpn.example.com)' '')}"
PUBLIC_IP="${PUBLIC_IP:-$(ask 'IP omumi server' "$PUB_GUESS")}"
EMAIL="${EMAIL:-$(ask 'Email baraye Lets Encrypt (khaali = bedune email)' '')}"
PSK="${PSK:-$(ask 'PSK / Secret L2TP (hadaghal 8 character)' '')}"
PANEL_USER="${PANEL_USER:-$(ask 'User vorud panel' '')}"
if [[ -n "${PANEL_PASS:-}" ]]; then
  :
else
  PANEL_PASS="$(ask_secret 'Password vorud panel')"
fi
VPN_USER="${VPN_USER:-$(ask 'Avalin user VPN (khaali = nemisaze)' '')}"
VPN_PASS="${VPN_PASS:-}"
if [[ -n "$VPN_USER" && -z "$VPN_PASS" ]]; then
  VPN_PASS="$(ask_secret "Password user VPN $VPN_USER")"
fi

if [[ -z "$DOMAIN" || -z "$PUBLIC_IP" || -z "$PSK" || -z "$PANEL_USER" || -z "$PANEL_PASS" ]]; then
  echo "domain, IP, PSK, user/pass panel lazeman por bashan."
  exit 1
fi
if [[ ${#PSK} -lt 8 ]]; then
  echo "PSK bayad hadaghal 8 character bashe."
  exit 1
fi

echo
echo "Nasb package ha..."
apt-get update -y
apt-get install -y \
  strongswan strongswan-pki libcharon-extra-plugins libstrongswan-extra-plugins \
  libstrongswan-standard-plugins xl2tpd ppp iptables iptables-persistent \
  certbot nginx python3-flask python3-pip python3-venv curl openssl

python3 -m pip install --break-system-packages gunicorn flask werkzeug >/dev/null 2>&1 || true

install -d "$APP_DIR" "$APP_DIR/templates" "$APP_DIR/static" "$CFG_DIR" "$DATA_DIR" \
  /var/run/ikev2-l2tp-gui /var/www/html /etc/ipsec.d/certs /etc/ipsec.d/private /etc/ipsec.d/cacerts

cp -a "$SCRIPT_DIR/panel/." "$APP_DIR/"
rm -rf "$APP_DIR/clients"
cp -a "$SCRIPT_DIR/clients" "$APP_DIR/clients"
chmod 755 "$APP_DIR/app.py" "$APP_DIR/ppp-ip-up" "$APP_DIR/ppp-ip-down"
install -m 0755 "$APP_DIR/ppp-ip-up" /etc/ppp/ip-up.d/ikev2-l2tp-gui
install -m 0755 "$APP_DIR/ppp-ip-down" /etc/ppp/ip-down.d/ikev2-l2tp-gui

# disable plugins that break L2TP
for f in /etc/strongswan.d/charon/forecast.conf /etc/strongswan.d/charon/farp.conf; do
  if [[ -f "$f" ]]; then
    sed -i 's/^[[:space:]]*load.*/    load = no/' "$f" || true
  fi
done

echo "SSL (Let's Encrypt)..."
HAVE_SSL=0
systemctl stop nginx 2>/dev/null || true
CERT_MAIL=(--register-unsafely-without-email)
if [[ -n "$EMAIL" ]]; then
  CERT_MAIL=(--email "$EMAIL")
fi
KEEP=(--force-renewal)
if [[ -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem ]]; then
  KEEP=(--keep-until-expiring)
fi
certbot certonly --standalone --non-interactive --agree-tos \
  --cert-name "$DOMAIN" --key-type rsa --rsa-key-size 2048 \
  "${KEEP[@]}" -d "$DOMAIN" "${CERT_MAIL[@]}" || true

if [[ -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem ]]; then
  HAVE_SSL=1
  cp -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" /etc/ipsec.d/certs/server.crt
  cp -f "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" /etc/ipsec.d/private/server.key
  chmod 600 /etc/ipsec.d/private/server.key
  mkdir -p /etc/letsencrypt/renewal-hooks/deploy
  cat >/etc/letsencrypt/renewal-hooks/deploy/ikev2-l2tp-gui.sh << EOF
#!/bin/bash
cp -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /etc/ipsec.d/certs/server.crt
cp -f /etc/letsencrypt/live/${DOMAIN}/privkey.pem /etc/ipsec.d/private/server.key
chmod 600 /etc/ipsec.d/private/server.key
ipsec rereadall >/dev/null 2>&1 || true
systemctl reload nginx >/dev/null 2>&1 || true
EOF
  chmod +x /etc/letsencrypt/renewal-hooks/deploy/ikev2-l2tp-gui.sh
  if [[ -f /etc/letsencrypt/renewal/${DOMAIN}.conf ]]; then
    sed -i 's/authenticator = standalone/authenticator = webroot/' "/etc/letsencrypt/renewal/${DOMAIN}.conf" || true
    grep -q webroot_path "/etc/letsencrypt/renewal/${DOMAIN}.conf" || \
      printf '\nwebroot_path = /var/www/html\n' >> "/etc/letsencrypt/renewal/${DOMAIN}.conf"
  fi
else
  echo "SSL nashod — cert khod-emza misazam (IKEv2 ruye iPhone warning mide)."
  ipsec pki --gen --type rsa --size 2048 --outform pem > /tmp/ike-ca.key
  ipsec pki --self --ca --lifetime 3650 --in /tmp/ike-ca.key --type rsa \
    --dn "CN=${DOMAIN}-ca" --outform pem > /etc/ipsec.d/cacerts/ca.crt
  ipsec pki --gen --type rsa --size 2048 --outform pem > /etc/ipsec.d/private/server.key
  ipsec pki --pub --in /etc/ipsec.d/private/server.key --type rsa | \
    ipsec pki --issue --lifetime 825 --cacert /etc/ipsec.d/cacerts/ca.crt \
    --cakey /tmp/ike-ca.key --dn "CN=${DOMAIN}" --san "${DOMAIN}" --san "${PUBLIC_IP}" \
    --flag serverAuth --flag ikeIntermediate --outform pem \
    > /etc/ipsec.d/certs/server.crt
  chmod 600 /etc/ipsec.d/private/server.key
  rm -f /tmp/ike-ca.key
fi

echo "Config IPsec / L2TP..."
cat >/etc/ipsec.conf << EOF
config setup
  uniqueids=no
  charondebug="ike 1, knl 1, cfg 1"

conn %default
  keyingtries=%forever
  dpddelay=30s
  dpdtimeout=120s
  dpdaction=clear
  compress=no
  rekey=no
  fragmentation=yes
  forceencaps=yes
  mobike=yes

conn L2TP-PSK
  keyexchange=ikev1
  type=transport
  authby=secret
  pfs=no
  mobike=no
  ike=aes256-sha1-modp1024,aes256-sha1-modp2048,aes128-sha1-modp1024,3des-sha1-modp1024,aes256-sha256-modp2048!
  esp=aes256-sha1,aes128-sha1,3des-sha1,aes256-sha256!
  left=%any
  leftid=${PUBLIC_IP}
  leftprotoport=17/1701
  right=%any
  rightprotoport=17/%any
  auto=add

conn IKEv2-EAP
  keyexchange=ikev2
  type=tunnel
  ike=aes256-sha256-ecp256,aes256-sha256-modp2048,aes256gcm16-prfsha256-ecp256,aes128-sha256-ecp256,aes256-sha1-modp2048,aes256-sha256-modp1024!
  esp=aes256-sha256,aes128-sha256,aes256gcm16,aes128gcm16,aes256-sha1,aes128-sha1!
  left=%any
  leftid=@${DOMAIN}
  leftcert=server.crt
  leftauth=pubkey
  leftsendcert=always
  leftsubnet=0.0.0.0/0
  right=%any
  rightid=%any
  rightauth=eap-mschapv2
  eap_identity=%identity
  rightsourceip=10.8.3.0/24
  rightdns=9.9.9.9,1.0.0.1
  auto=add
EOF

cat >/etc/xl2tpd/xl2tpd.conf << 'EOF'
[global]
port = 1701
auth file = /etc/ppp/chap-secrets
access control = no

[lns default]
ip range = 10.8.2.10-10.8.2.200
local ip = 10.8.2.1
require chap = yes
refuse pap = yes
require authentication = yes
name = l2tpd
ppp debug = yes
pppoptfile = /etc/ppp/options.xl2tpd
length bit = yes
EOF

cat >/etc/ppp/options.xl2tpd << 'EOF'
ipcp-accept-local
ipcp-accept-remote
refuse-pap
refuse-chap
refuse-mschap
require-mschap-v2
noccp
auth
mtu 1200
mru 1200
hide-password
name l2tpd
connect-delay 5000
ms-dns 9.9.9.9
ms-dns 1.0.0.1
nobsdcomp
nodeflate
nopcomp
noaccomp
noipv6
noproxyarp
lock
EOF

cat >/etc/sysctl.d/99-ikev2-l2tp-gui.conf << EOF
net.ipv4.ip_forward=1
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.accept_redirects=0
net.ipv4.conf.default.send_redirects=0
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.default.rp_filter=0
net.ipv4.conf.${IFACE}.rp_filter=0
EOF
sysctl -p /etc/sysctl.d/99-ikev2-l2tp-gui.conf >/dev/null

iptables -t nat -C POSTROUTING -s 10.8.2.0/24 -o "$IFACE" -j SNAT --to-source "$PUBLIC_IP" 2>/dev/null || \
  iptables -t nat -A POSTROUTING -s 10.8.2.0/24 -o "$IFACE" -j SNAT --to-source "$PUBLIC_IP"
iptables -t nat -C POSTROUTING -s 10.8.3.0/24 -o "$IFACE" -j SNAT --to-source "$PUBLIC_IP" 2>/dev/null || \
  iptables -t nat -A POSTROUTING -s 10.8.3.0/24 -o "$IFACE" -j SNAT --to-source "$PUBLIC_IP"
iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1200 2>/dev/null || \
  iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1200
iptables -C FORWARD -s 10.8.2.0/24 -j ACCEPT 2>/dev/null || iptables -A FORWARD -s 10.8.2.0/24 -j ACCEPT
iptables -C FORWARD -d 10.8.2.0/24 -j ACCEPT 2>/dev/null || iptables -A FORWARD -d 10.8.2.0/24 -j ACCEPT
iptables -C FORWARD -s 10.8.3.0/24 -j ACCEPT 2>/dev/null || iptables -A FORWARD -s 10.8.3.0/24 -j ACCEPT
iptables -C FORWARD -d 10.8.3.0/24 -j ACCEPT 2>/dev/null || iptables -A FORWARD -d 10.8.3.0/24 -j ACCEPT
netfilter-persistent save >/dev/null 2>&1 || iptables-save > /etc/iptables/rules.v4 || true

python3 - << PY
import json, os, secrets
from pathlib import Path
from werkzeug.security import generate_password_hash
cfg_dir = Path("${CFG_DIR}")
data_dir = Path("${DATA_DIR}")
cfg_dir.mkdir(parents=True, exist_ok=True)
data_dir.mkdir(parents=True, exist_ok=True)
cfg = {
  "domain": "${DOMAIN}",
  "public_ip": "${PUBLIC_IP}",
  "psk": """${PSK}""",
  "dns": ["9.9.9.9", "1.0.0.1"],
  "https": bool(${HAVE_SSL}),
}
(cfg_dir / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
os.chmod(cfg_dir / "config.json", 0o600)
admin_file = cfg_dir / "admin.json"
admin = {
  "user": "${PANEL_USER}",
  "password": generate_password_hash("""${PANEL_PASS}"""),
  "secret": secrets.token_hex(32),
}
admin_file.write_text(json.dumps(admin, indent=2) + "\n")
os.chmod(admin_file, 0o600)
users_file = data_dir / "users.json"
users = {}
if users_file.exists():
    try:
        users = json.loads(users_file.read_text())
    except Exception:
        users = {}
vpn_user = "${VPN_USER}"
vpn_pass = """${VPN_PASS}"""
if vpn_user:
    users[vpn_user] = {
        "password": vpn_pass,
        "expires": "",
        "quota_gb": 0,
        "used_bytes": users.get(vpn_user, {}).get("used_bytes", 0),
        "created": users.get(vpn_user, {}).get("created", ""),
        "enabled": True,
    }
users_file.write_text(json.dumps(users, ensure_ascii=False, indent=2) + "\n")
os.chmod(users_file, 0o600)
print("config json ok")
PY

python3 - << PY
import os, sys
sys.path.insert(0, "${APP_DIR}")
os.chdir("${APP_DIR}")
os.environ["IKEGUI_APP"] = "${APP_DIR}"
os.environ["IKEGUI_CFG"] = "${CFG_DIR}"
os.environ["IKEGUI_DATA"] = "${DATA_DIR}"
from app import import_secrets_if_needed, write_secrets, load_users
users = import_secrets_if_needed()
write_secrets(users)
print("secrets ok", list(users))
PY

# nginx
if [[ "$HAVE_SSL" -eq 1 ]]; then
  cat >/etc/nginx/sites-available/ikev2-l2tp-gui << EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};
    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
EOF
else
  cat >/etc/nginx/sites-available/ikev2-l2tp-gui << EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto http;
    }
}
EOF
fi
ln -sfn /etc/nginx/sites-available/ikev2-l2tp-gui /etc/nginx/sites-enabled/ikev2-l2tp-gui
rm -f /etc/nginx/sites-enabled/default

cp "$APP_DIR/ikev2-l2tp-gui.service" /etc/systemd/system/ikev2-l2tp-gui.service
systemctl daemon-reload
systemctl enable xl2tpd strongswan-starter ikev2-l2tp-gui nginx >/dev/null
systemctl restart xl2tpd
systemctl restart strongswan-starter
systemctl restart ikev2-l2tp-gui
nginx -t
systemctl restart nginx

python3 - << PY
from pathlib import Path
import uuid
src = Path("${APP_DIR}/clients")
out = src / "out"
out.mkdir(parents=True, exist_ok=True)
domain = """${DOMAIN}"""
vpn = str(uuid.uuid5(uuid.NAMESPACE_DNS, domain + ":vpn")).upper()
payload = str(uuid.uuid5(uuid.NAMESPACE_DNS, domain + ":profile")).upper()
for rel in (
    "windows/Install-IKEv2.ps1",
    "windows/Install-IKEv2.bat",
    "windows/Check-Windows.bat",
    "windows/RAHNAMA.txt",
    "ios/IKEv2.mobileconfig",
    "ios/RAHNAMA.txt",
):
    text = (src / rel).read_text(encoding="utf-8")
    text = text.replace("__DOMAIN__", domain).replace("__VPN_UUID__", vpn).replace("__PAYLOAD_UUID__", payload)
    (out / Path(rel).name).write_text(text, encoding="utf-8")
print("clients stamped")
PY

echo
echo "=========================================="
echo "Nasb tamom shod."
if [[ "$HAVE_SSL" -eq 1 ]]; then
  echo "Panel:   https://${DOMAIN}"
else
  echo "Panel:   http://${DOMAIN}   (SSL nashod)"
fi
echo "Panel user: ${PANEL_USER}"
echo "IKEv2:  server + Remote ID = ${DOMAIN}"
echo "Windows: panel > download zip   ya  ${APP_DIR}/clients/out/Install-IKEv2.bat"
echo "iOS:     panel > download profile ya  ${APP_DIR}/clients/out/IKEv2.mobileconfig"
echo "=========================================="
