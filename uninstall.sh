#!/bin/bash
set -euo pipefail
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "sudo bash uninstall.sh"
  exit 1
fi
systemctl disable --now ikev2-l2tp-gui nginx xl2tpd strongswan-starter 2>/dev/null || true
rm -f /etc/nginx/sites-enabled/ikev2-l2tp-gui /etc/nginx/sites-available/ikev2-l2tp-gui
rm -f /etc/systemd/system/ikev2-l2tp-gui.service
rm -f /etc/ppp/ip-up.d/ikev2-l2tp-gui /etc/ppp/ip-down.d/ikev2-l2tp-gui
rm -rf /opt/ikev2-l2tp-gui
echo "Panel va service ha hazf shodand."
echo "Config VPN (/etc/ipsec.* /etc/xl2tpd /etc/ikev2-l2tp-gui) pak nashod."
echo "Baraye pak kardan kamel: rm -rf /etc/ikev2-l2tp-gui /var/lib/ikev2-l2tp-gui"
systemctl daemon-reload
