#!/usr/bin/env bash
# Zero-disruption deploy: updates the panel app in place without touching
# strongSwan/xl2tpd, so established IKEv2/L2TP tunnels are never dropped.
set -euo pipefail

APP_DIR="/opt/ikev2-l2tp-gui"
REPO_DIR="${REPO_DIR:-/opt/ikev2-gui-src}"
BRANCH="${1:-main}"

if [[ $EUID -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "cloning repo into $REPO_DIR" >&2
  git clone --branch "$BRANCH" https://github.com/navidhaghpanah/multivpn-panel.git "$REPO_DIR"
fi

cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

python3 -c "import ast; ast.parse(open('panel/app.py').read())"

# Only the panel app files change here — ipsec.conf/ipsec.secrets/xl2tpd
# config are left untouched, so no VPN session is interrupted.
cp -a "$REPO_DIR/panel/." "$APP_DIR/"
rm -f "$APP_DIR/ikev2-l2tp-gui.service"
cp -a "$REPO_DIR/clients" "$APP_DIR/clients"

systemctl restart ikev2-l2tp-gui
sleep 1
systemctl is-active --quiet ikev2-l2tp-gui && echo "panel restarted OK" || {
  echo "panel failed to start, check: journalctl -u ikev2-l2tp-gui -n 50" >&2
  exit 1
}
