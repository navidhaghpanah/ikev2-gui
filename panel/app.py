#!/usr/bin/env python3
# IKEv2 GUI — پنل مدیریت
import base64
import hashlib
import io
import ipaddress
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = Path(os.environ.get("IKEGUI_APP", "/opt/ikev2-l2tp-gui"))
CFG_DIR = Path(os.environ.get("IKEGUI_CFG", "/etc/ikev2-l2tp-gui"))
DATA_DIR = Path(os.environ.get("IKEGUI_DATA", "/var/lib/ikev2-l2tp-gui"))
CLIENTS_DIR = APP_DIR / "clients"
PPP_ONLINE = Path("/var/run/ikev2-l2tp-gui")
ADMIN_FILE = CFG_DIR / "admin.json"
CONFIG_FILE = CFG_DIR / "config.json"
USERS_FILE = DATA_DIR / "users.json"
SNAP_FILE = DATA_DIR / "traffic-snap.json"
IPSEC_SECRETS = Path("/etc/ipsec.secrets")
CHAP_SECRETS = Path("/etc/ppp/chap-secrets")
IPSEC_CONF = Path("/etc/ipsec.conf")
PPP_OPTS = Path("/etc/ppp/options.xl2tpd")
STROKE = Path("/usr/lib/ipsec/stroke")
XRAY_SS_BIN = Path("/opt/panel-xray/xray")
XRAY_SS_CONFIG = Path("/etc/panel-xray/config.json")
HYSTERIA_BIN = Path("/opt/panel-hysteria/hysteria")
HYSTERIA_CONFIG = Path("/etc/panel-hysteria/config.yaml")
SS_METHOD = "2022-blake3-aes-128-gcm"
TZ = ZoneInfo("Asia/Tehran")
USER_RE = re.compile(r"^[A-Za-z0-9._-]{2,32}$")
FA_D = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
    static_folder=str(APP_DIR / "static"),
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 12

_cpu_prev = None
_net_prev = None
_lock = threading.Lock()
_login_attempts = {}
LOGIN_WINDOW = 15 * 60
LOGIN_MAX_ATTEMPTS = 5


def fa(v):
    return str(v).translate(FA_D)


def now_tehran():
    return datetime.now(TZ)


def today_iso():
    return now_tehran().date().isoformat()


def human(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        n = 0
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"):
        if n < 1024 or unit == "ترابایت":
            if unit == "بایت":
                return fa("%d %s" % (int(n), unit))
            return fa("%.1f %s" % (n, unit))
        n /= 1024.0
    return fa("%.1f ترابایت" % n)


def run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return str(e)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    os.chmod(path, 0o600)


def load_config():
    cfg = load_json(
        CONFIG_FILE,
        {
            "domain": "",
            "public_ip": "",
            "psk": "",
            "dns": ["9.9.9.9", "1.0.0.1"],
            "interface": "",
            "max_sessions_per_user": 3,
        },
    )
    changed = False
    if "ss_next_port" not in cfg:
        cfg["ss_next_port"] = 8388
        changed = True
    if "hy_port" not in cfg:
        cfg["hy_port"] = 443
        changed = True
    if not cfg.get("hy_stats_secret"):
        cfg["hy_stats_secret"] = secrets.token_urlsafe(24)
        changed = True
    if changed:
        save_json(CONFIG_FILE, cfg)
    return cfg


def allocate_ss_port():
    # Caller must already hold _lock (called from users_add/users_update).
    cfg = load_config()
    port = int(cfg.get("ss_next_port") or 8388)
    cfg["ss_next_port"] = port + 1
    save_config(cfg)
    return port


def save_config(cfg):
    save_json(CONFIG_FILE, cfg)


def load_admin():
    data = load_json(ADMIN_FILE, {})
    if data.get("secret"):
        app.secret_key = data["secret"]
    # Installation requires TLS. Never downgrade session cookies to HTTP.
    app.config["SESSION_COOKIE_SECURE"] = True
    return data


def save_admin(data):
    save_json(ADMIN_FILE, data)


def load_users():
    return load_json(USERS_FILE, {})


def save_users(users):
    save_json(USERS_FILE, users)


def login_required(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        if not session.get("ok"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "auth"}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrap


def csrf_token():
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


@app.context_processor
def csrf_context():
    return {"csrf_token": csrf_token}


def csrf_required(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf", "")
        if not expected or not secrets.compare_digest(submitted, expected):
            flash("درخواست نامعتبر یا منقضی شده است.")
            return redirect(request.referrer or url_for("index"))
        return fn(*args, **kwargs)

    return wrap


@app.after_request
def security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src https://fonts.gstatic.com; script-src 'self'; base-uri 'self'; frame-ancestors 'none'"
    )
    if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def parse_secrets_users():
    found = []
    if IPSEC_SECRETS.exists():
        for raw in IPSEC_SECRETS.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r'^([A-Za-z0-9._-]+)\s*:\s*EAP\s+"([^"]*)"\s*$', raw.strip())
            if m:
                found.append((m.group(1), m.group(2)))
    return found


def import_secrets_if_needed():
    users = load_users()
    changed = False
    for name, pw in parse_secrets_users():
        if name not in users:
            users[name] = {
                "password": pw,
                "expires": "",
                "quota_gb": 0,
                "used_bytes": 0,
                "created": today_iso(),
                "enabled": True,
            }
            changed = True
        elif users[name].get("password") != pw:
            users[name]["password"] = pw
            changed = True
    if changed:
        save_users(users)
    return users


def user_blocked(u):
    if not u.get("enabled", True):
        return "غیرفعال"
    exp = (u.get("expires") or "").strip()
    if exp:
        try:
            if date.fromisoformat(exp) < now_tehran().date():
                return "منقضی"
        except ValueError:
            pass
    try:
        q = float(u.get("quota_gb") or 0)
    except (TypeError, ValueError):
        return "حجم نامعتبر"
    if not math.isfinite(q) or q < 0:
        return "حجم نامعتبر"
    if q > 0 and float(u.get("used_bytes") or 0) >= q * (1024 ** 3):
        return "اتمام حجم"
    return ""


def write_secrets(users=None, psk=None, public_ip=None, domain=None):
    # Always read users.json from disk. A stale in-memory copy (traffic
    # collector) must not wipe a user that was just added in the panel.
    users = load_users()
    cfg = load_config()
    psk = psk if psk is not None else cfg.get("psk", "")
    public_ip = public_ip or cfg.get("public_ip", "")
    domain = domain or cfg.get("domain", "")
    lines = [": RSA server.key"]
    if public_ip:
        lines.append(public_ip + ' %any : PSK "' + psk + '"')
    if domain:
        lines.append(domain + ' %any : PSK "' + psk + '"')
    lines.append('%any %any : PSK "' + psk + '"')
    chap = ["# client  server  secret  IP"]
    for name, u in users.items():
        if user_blocked(u):
            continue
        pw = u.get("password") or ""
        # These values are rendered into strongSwan/PPP configuration files.
        # Routes validate them; this guard also protects imported legacy data.
        if not safe_secret(pw, 4, 64):
            continue
        lines.append('%s : EAP "%s"' % (name, pw))
        chap.append('%s  l2tpd  "%s"  *' % (name, pw))
    IPSEC_SECRETS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(IPSEC_SECRETS, 0o600)
    CHAP_SECRETS.write_text("\n".join(chap) + "\n", encoding="utf-8")
    os.chmod(CHAP_SECRETS, 0o600)
    run(["ipsec", "rereadsecrets"])


def safe_secret(value, minimum=8, maximum=128):
    return bool(
        isinstance(value, str)
        and minimum <= len(value) <= maximum
        and re.fullmatch(r"[A-Za-z0-9._~!@#%^&*+=,:;?/-]+", value)
    )


def new_ss_key():
    return base64.b64encode(secrets.token_bytes(16)).decode()


def write_xray_ss_config(users=None):
    # One dedicated inbound per user (own port + own key) rather than a
    # single shared-port multi-user (EIH) inbound: xray-core's shadowsocks
    # *outbound* does not appear to speak the 2022 multi-user identity
    # handshake (verified empirically — a shared port with a "users" array
    # consistently fails with "cipher: message authentication failed"
    # regardless of whether the per-user password is the raw key or
    # "serverKey:userKey"). Per-user ports sidestep that entirely and work
    # with any standard Shadowsocks-2022 client.
    users = load_users() if users is None else users
    inbounds = []
    for name, u in users.items():
        if user_blocked(u) or not u.get("ss_enabled"):
            continue
        key = u.get("ss_key") or ""
        port = u.get("ss_port")
        if not re.fullmatch(r"[A-Za-z0-9+/]{22}==", key) or not port:
            continue
        inbounds.append(
            {
                "tag": "ss-%s" % name,
                "listen": "0.0.0.0",
                "port": int(port),
                "protocol": "shadowsocks",
                "settings": {
                    "network": "tcp,udp",
                    "method": SS_METHOD,
                    "password": key,
                    "email": name,
                },
            }
        )
    doc = {
        "log": {"loglevel": "warning"},
        "stats": {},
        "api": {"tag": "api", "listen": "127.0.0.1:10085", "services": ["StatsService"]},
        "policy": {
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}},
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
        },
        "inbounds": inbounds,
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
    }
    new_text = json.dumps(doc, indent=2)
    # A restart drops every live SS connection, not just the one being
    # edited — skip it when this call didn't actually change anything
    # (e.g. an unrelated IKEv2-only user was added/edited/deleted).
    try:
        unchanged = XRAY_SS_CONFIG.read_text(encoding="utf-8") == new_text
    except OSError:
        unchanged = False
    if unchanged:
        return
    XRAY_SS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = XRAY_SS_CONFIG.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(XRAY_SS_CONFIG)
    if inbounds:
        run(["systemctl", "restart", "panel-shadowsocks"], timeout=15)
    else:
        run(["systemctl", "stop", "panel-shadowsocks"], timeout=15)


def yaml_str(value):
    return json.dumps(str(value))


def write_hysteria_config(users=None):
    users = load_users() if users is None else users
    cfg = load_config()
    port = int(cfg.get("hy_port") or 443)
    domain = (cfg.get("domain") or "").strip()
    secret = cfg.get("hy_stats_secret") or ""
    cert = Path("/etc/letsencrypt/live") / domain / "fullchain.pem"
    key = Path("/etc/letsencrypt/live") / domain / "privkey.pem"
    lines = [
        "listen: :%d" % port,
        "tls:",
        "  cert: %s" % yaml_str(str(cert)),
        "  key: %s" % yaml_str(str(key)),
        "auth:",
        "  type: userpass",
        "  userpass:",
    ]
    any_user = False
    for name, u in users.items():
        if user_blocked(u) or not u.get("hy_enabled"):
            continue
        pw = u.get("password") or ""
        if not safe_secret(pw, 4, 128):
            continue
        lines.append("    %s: %s" % (yaml_str(name), yaml_str(pw)))
        any_user = True
    if not any_user:
        # Deterministic (not freshly random) so an idle config with no
        # Hysteria2 users compares equal across calls and skips the restart.
        placeholder = hashlib.sha256(("hy-placeholder:" + secret).encode()).hexdigest()
        lines.append("    __disabled__: %s" % yaml_str(placeholder))
    lines += [
        "trafficStats:",
        "  listen: 127.0.0.1:9999",
        "  secret: %s" % yaml_str(secret),
    ]
    new_text = "\n".join(lines) + "\n"
    # Same reasoning as write_xray_ss_config: a restart drops every live
    # Hysteria2 connection, so skip it when nothing actually changed.
    try:
        unchanged = HYSTERIA_CONFIG.read_text(encoding="utf-8") == new_text
    except OSError:
        unchanged = False
    if unchanged:
        return
    HYSTERIA_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = HYSTERIA_CONFIG.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(HYSTERIA_CONFIG)
    if cert.is_file() and key.is_file():
        run(["systemctl", "restart", "panel-hysteria"], timeout=15)
    else:
        run(["systemctl", "stop", "panel-hysteria"], timeout=15)


def xray_ss_stats():
    result = {}
    try:
        p = subprocess.run(
            [str(XRAY_SS_BIN), "api", "statsquery", "-server=127.0.0.1:10085"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        data = json.loads(p.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return result
    for stat in data.get("stat", []):
        name = stat.get("name") or ""
        m = re.match(r"^user>>>(.+)>>>traffic>>>(uplink|downlink)$", name)
        if not m:
            continue
        user = m.group(1)
        result[user] = result.get(user, 0) + int(stat.get("value") or 0)
    return result


def hysteria_stats():
    cfg = load_config()
    secret = cfg.get("hy_stats_secret") or ""
    req = urllib.request.Request(
        "http://127.0.0.1:9999/traffic",
        headers={"Authorization": secret},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    result = {}
    for user, v in (data or {}).items():
        if isinstance(v, dict):
            result[user] = int(v.get("tx") or 0) + int(v.get("rx") or 0)
    return result


def parse_sessions():
    text = run(["ipsec", "statusall"])
    sessions = []
    current = None
    for line in text.splitlines():
        s = line.strip()
        m = re.search(
            r"^(IKEv2-EAP|L2TP-PSK)\[(\d+)\]:\s+ESTABLISHED\s+(.+?),\s+"
            r"[\d.]+\[.*?\]\.\.\.([\d.]+)\[",
            s,
        )
        if m:
            if current:
                sessions.append(current)
            current = {
                "conn": m.group(1),
                "id": m.group(2),
                "uptime": m.group(3).replace(" ago", "").replace("minutes", "دقیقه").replace("minute", "دقیقه").replace("hours", "ساعت").replace("hour", "ساعت").replace("seconds", "ثانیه").replace("second", "ثانیه").replace("days", "روز").replace("day", "روز"),
                "remote": m.group(4),
                "user": "",
                "vip": "",
                "bytes_in": 0,
                "bytes_out": 0,
                "bytes_total": 0,
                "proto": "IKEv2" if m.group(1) == "IKEv2-EAP" else "L2TP",
            }
            continue
        if not current:
            continue
        m = re.search(r"Remote EAP identity:\s+(\S+)", s)
        if m:
            current["user"] = m.group(1)
        m = re.search(r"0\.0\.0\.0/0\s+===\s+([\d.]+)/32", s)
        if m:
            current["vip"] = m.group(1)
        m = re.search(
            r"([\d]+)\s+bytes_i\s+\((\d+)\s+pkts.*?\)\s*,\s*([\d]+)\s+bytes_o\s+\((\d+)\s+pkts",
            s,
        )
        if m:
            current["bytes_in"] = int(m.group(1))
            current["bytes_out"] = int(m.group(3))
            current["bytes_total"] = current["bytes_in"] + current["bytes_out"]
    if current:
        sessions.append(current)

    if PPP_ONLINE.exists():
        have = {(s.get("user"), s.get("proto")) for s in sessions}
        for f in PPP_ONLINE.glob("ppp*"):
            try:
                parts = f.read_text(encoding="utf-8", errors="replace").strip().split()
            except OSError:
                continue
            if len(parts) >= 2:
                name = parts[0]
                if (name, "L2TP") not in have:
                    rx = tx = 0
                    try:
                        rx = int(Path("/sys/class/net/%s/statistics/rx_bytes" % f.name).read_text())
                        tx = int(Path("/sys/class/net/%s/statistics/tx_bytes" % f.name).read_text())
                    except (OSError, ValueError):
                        pass
                    sessions.append(
                        {
                            "conn": "L2TP-PPP",
                            "id": f.name,
                            "uptime": "",
                            "remote": "",
                            "user": name,
                            "vip": parts[1],
                            "bytes_in": rx,
                            "bytes_out": tx,
                            "bytes_total": rx + tx,
                            "proto": "L2TP",
                        }
                    )
    return sessions


def max_sessions_per_user():
    try:
        value = int(load_config().get("max_sessions_per_user", 3))
    except (TypeError, ValueError):
        value = 3
    return max(1, min(10, value))


def cleanup_excess_sessions(sessions=None):
    """Keep the newest IKEv2 sessions for each EAP identity.

    IKE IDs are monotonically increasing for the lifetime of charon, so a
    larger ID is a newer session.  We intentionally avoid `uniqueids=yes` as
    clients often present the same outer IKE identity even for different EAP
    users, and enabling it could disconnect unrelated accounts.
    """
    sessions = sessions if sessions is not None else parse_sessions()
    limit = max_sessions_per_user()
    grouped = {}
    for session_info in sessions:
        if session_info.get("proto") != "IKEv2" or not session_info.get("user"):
            continue
        try:
            ike_id = int(session_info.get("id"))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(session_info["user"], []).append((ike_id, session_info))

    terminated = []
    for username, active in grouped.items():
        active.sort(key=lambda item: item[0], reverse=True)
        for _, old_session in active[limit:]:
            target = terminate_ike_session(old_session)
            terminated.append({"user": username, "target": target})
    return terminated


def terminate_ike_session(session_info):
    target = "%s[%s]" % (session_info.get("conn") or "IKEv2-EAP", session_info["id"])
    if STROKE.is_file():
        run([str(STROKE), "down-nb", target], timeout=5)
    else:
        run(["ipsec", "down", target], timeout=5)
    return target


def sample_traffic():
    sessions = parse_sessions()
    cleanup_excess_sessions(sessions)
    with _lock:
        users = load_users()
        snap = load_json(SNAP_FILE, {})
        new_snap = {}
        changed = False
        for s in sessions:
            name = s.get("user") or ""
            if name not in users:
                continue
            total = int(s.get("bytes_total") or 0)
            key = "%s:%s:%s" % (name, s.get("proto"), s.get("id"))
            prev = int(snap.get(key, 0))
            if total >= prev:
                delta = total - prev
            else:
                delta = total
            if delta > 0:
                users[name]["used_bytes"] = int(users[name].get("used_bytes") or 0) + delta
                changed = True
            new_snap[key] = total
        for proto, totals in (("ss", xray_ss_stats()), ("hy", hysteria_stats())):
            for name, total in totals.items():
                if name not in users:
                    continue
                key = "%s:%s" % (name, proto)
                prev = int(snap.get(key, 0))
                delta = total - prev if total >= prev else total
                if delta > 0:
                    users[name]["used_bytes"] = int(users[name].get("used_bytes") or 0) + delta
                    changed = True
                new_snap[key] = total
        if changed:
            save_users(users)
        save_json(SNAP_FILE, new_snap)
        blocked_now = False
        for name, u in users.items():
            if user_blocked(u) and u.get("enabled", True):
                blocked_now = True
        if blocked_now or changed:
            write_secrets()
        if blocked_now:
            # Only regenerate SS/Hysteria2 when someone actually needs to be
            # cut off — both require a process restart (unlike strongSwan's
            # in-place rereadsecrets), which would drop live connections if
            # done on every traffic-accounting tick.
            write_xray_ss_config(users)
            write_hysteria_config(users)
        return users, sessions


def host_stats():
    global _cpu_prev, _net_prev
    load1, load5, load15 = 0.0, 0.0, 0.0
    try:
        a, b, c = Path("/proc/loadavg").read_text().split()[:3]
        load1, load5, load15 = float(a), float(b), float(c)
    except (OSError, ValueError):
        pass
    cpu_pct = 0.0
    try:
        line = Path("/proc/stat").read_text().splitlines()[0].split()
        vals = [int(x) for x in line[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        prev = _cpu_prev
        _cpu_prev = (idle, total)
        if prev:
            didle = idle - prev[0]
            dtotal = total - prev[1]
            if dtotal > 0:
                cpu_pct = max(0.0, min(100.0, 100.0 * (1.0 - didle / dtotal)))
    except (OSError, ValueError, IndexError):
        pass
    mem_total = mem_used = 0
    try:
        info = {}
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, rest = ln.split(":", 1)
            info[k] = int(rest.strip().split()[0]) * 1024
        mem_total = info.get("MemTotal", 0)
        mem_used = mem_total - info.get("MemAvailable", info.get("MemFree", 0))
    except (OSError, ValueError):
        pass
    disk = shutil.disk_usage("/")
    uptime = 0.0
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError):
        pass
    net_iface = (load_config().get("interface") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,32}", net_iface):
        net_iface = ""
    if not net_iface:
        try:
            for line in Path("/proc/net/route").read_text().splitlines()[1:]:
                fields = line.split()
                if len(fields) > 1 and fields[1] == "00000000":
                    net_iface = fields[0]
                    break
        except OSError:
            pass
    net_rx = net_tx = 0
    net_down_bps = net_up_bps = 0.0
    if net_iface:
        try:
            net_rx = int(Path("/sys/class/net").joinpath(net_iface, "statistics", "rx_bytes").read_text())
            net_tx = int(Path("/sys/class/net").joinpath(net_iface, "statistics", "tx_bytes").read_text())
            sampled_at = time.monotonic()
            previous = _net_prev
            _net_prev = (net_iface, net_rx, net_tx, sampled_at)
            if previous and previous[0] == net_iface:
                elapsed = sampled_at - previous[3]
                if elapsed > 0:
                    net_down_bps = max(0.0, (net_rx - previous[1]) / elapsed)
                    net_up_bps = max(0.0, (net_tx - previous[2]) / elapsed)
        except (OSError, ValueError):
            net_rx = net_tx = 0
    cores = os.cpu_count() or 1
    return {
        "cpu": round(cpu_pct, 1),
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "cores": cores,
        "mem_total": mem_total,
        "mem_used": mem_used,
        "mem_pct": round(100.0 * mem_used / mem_total, 1) if mem_total else 0,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_pct": round(100.0 * disk.used / disk.total, 1) if disk.total else 0,
        "uptime": uptime,
        "net_iface": net_iface,
        "net_rx": net_rx,
        "net_tx": net_tx,
        "net_down_bps": net_down_bps,
        "net_up_bps": net_up_bps,
    }


def fmt_uptime(sec):
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, _ = divmod(sec, 60)
    parts = []
    if d:
        parts.append(fa(d) + " روز")
    if h:
        parts.append(fa(h) + " ساعت")
    parts.append(fa(m) + " دقیقه")
    return " ".join(parts)


def dashboard_payload():
    users = import_secrets_if_needed()
    sessions = parse_sessions()
    online = sorted({s["user"] for s in sessions if s.get("user")})
    hs = host_stats()
    rows = []
    for name, u in sorted(users.items()):
        block = user_blocked(u)
        q = float(u.get("quota_gb") or 0)
        used = float(u.get("used_bytes") or 0)
        ses = next((s for s in sessions if s.get("user") == name), None)
        rows.append(
            {
                "name": name,
                "password": u.get("password") or "",
                "expires": u.get("expires") or "",
                "quota_gb": q,
                "used_bytes": used,
                "used_h": human(used),
                "quota_h": "نامحدود" if q <= 0 else fa(gtrim(q)) + " گیگابایت",
                "created": u.get("created") or "",
                "online": name in online,
                "block": block,
                "proto": ses["proto"] if ses else "",
                "vip": ses["vip"] if ses else "",
                "remote": ses["remote"] if ses else "",
                "uptime": ses["uptime"] if ses else "",
                "ss_enabled": bool(u.get("ss_enabled")),
                "hy_enabled": bool(u.get("hy_enabled")),
            }
        )
    cfg = load_config()
    for s in sessions:
        s["bytes_h"] = human(s.get("bytes_total") or 0)
        s["in_h"] = human(s.get("bytes_in") or 0)
        s["out_h"] = human(s.get("bytes_out") or 0)
    return {
        "users": rows,
        "sessions": sessions,
        "online": online,
        "online_count": len(online),
        "total": len(rows),
        "host": cfg.get("domain") or cfg.get("public_ip") or "",
        "dns": ",".join(cfg.get("dns") or []),
        "max_sessions_per_user": max_sessions_per_user(),
        "stats": hs,
        "cpu_fa": fa(hs["cpu"]),
        "mem_fa": fa(hs["mem_pct"]),
        "mem_used_h": human(hs["mem_used"]),
        "mem_total_h": human(hs["mem_total"]),
        "disk_fa": fa(hs["disk_pct"]),
        "load_fa": fa("%.2f" % hs["load1"]),
        "uptime_h": fmt_uptime(hs["uptime"]),
        "net_iface": hs["net_iface"] or "—",
        "net_rx_h": human(hs["net_rx"]),
        "net_tx_h": human(hs["net_tx"]),
        "net_down_h": human(hs["net_down_bps"]) + "/ثانیه",
        "net_up_h": human(hs["net_up_bps"]) + "/ثانیه",
        "now": now_tehran().strftime("%Y/%m/%d %H:%M"),
        "now_fa": fa(now_tehran().strftime("%Y/%m/%d %H:%M")),
    }


def gtrim(q):
    if float(q) == int(q):
        return str(int(q))
    return str(q)


@app.route("/login", methods=["GET", "POST"])
def login():
    load_admin()
    err = ""
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf", "")
        if not expected or not secrets.compare_digest(submitted, expected):
            return render_template("login.html", err="درخواست نامعتبر است؛ صفحه را تازه‌سازی کنید.", host=load_config().get("domain") or ""), 400
        remote = request.headers.get("X-Real-IP", request.remote_addr or "")
        now = time.monotonic()
        attempts = [t for t in _login_attempts.get(remote, []) if now - t < LOGIN_WINDOW]
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            return render_template("login.html", err="تلاش‌های ورود زیاد بوده؛ چند دقیقه بعد دوباره امتحان کنید.", host=load_config().get("domain") or ""), 429
        admin = load_admin()
        user = (request.form.get("user") or "").strip()
        pw = request.form.get("password") or ""
        if user == admin.get("user") and admin.get("password") and check_password_hash(admin["password"], pw):
            session["ok"] = True
            session.permanent = True
            session.pop("csrf", None)
            _login_attempts.pop(remote, None)
            return redirect(url_for("index"))
        attempts.append(now)
        _login_attempts[remote] = attempts
        err = "نام کاربری یا رمز عبور اشتباه است."
    cfg = load_config()
    return render_template("login.html", err=err, host=cfg.get("domain") or "")


@app.route("/logout", methods=["POST"])
@login_required
@csrf_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d["page"] = "dash"
    d["page_title"] = "داشبورد"
    d["page_subtitle"] = "نمای کلی سرور و اتصال‌های فعال"
    return render_template("index.html", **d)


@app.route("/users")
@login_required
def users_page():
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d["page"] = "users"
    d["page_title"] = "کاربران"
    d["page_subtitle"] = "ساخت حساب و مدیریت حجم و انقضا"
    return render_template("users.html", **d)


@app.route("/sessions")
@login_required
def sessions_page():
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d["page"] = "sessions"
    d["page_title"] = "نشست‌ها"
    d["page_subtitle"] = "اتصال‌های زنده و پاک‌سازی نشست‌های قدیمی"
    return render_template("sessions.html", **d)


@app.route("/clients")
@login_required
def clients_page():
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d["page"] = "clients"
    d["page_title"] = "کلاینت‌ها"
    d["page_subtitle"] = "فایل‌های آمادهٔ اتصال برای دستگاه‌ها"
    return render_template("clients.html", **d)


@app.route("/settings")
@login_required
def settings():
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d["page"] = "settings"
    d["page_title"] = "تنظیمات"
    d["page_subtitle"] = "امنیت، DNS و محدودیت نشست‌ها"
    return render_template("settings.html", **d)


def client_domain():
    cfg = load_config()
    return (cfg.get("domain") or "").strip()


def stamp_client_text(text, domain):
    vpn_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, domain + ":vpn")).upper()
    payload_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, domain + ":profile")).upper()
    return (
        text.replace("__DOMAIN__", domain)
        .replace("__VPN_UUID__", vpn_uuid)
        .replace("__PAYLOAD_UUID__", payload_uuid)
    )


def load_client_template(rel, domain):
    path = CLIENTS_DIR / rel
    return stamp_client_text(path.read_text(encoding="utf-8"), domain)


@app.route("/clients/windows.zip")
@login_required
def clients_windows():
    domain = client_domain()
    if not domain:
        flash("دامنه در تنظیمات نیست.")
        return redirect(url_for("clients_page"))
    if not (CLIENTS_DIR / "windows" / "Install-IKEv2.ps1").is_file():
        flash("فایل کلاینت ویندوز روی سرور نیست.")
        return redirect(url_for("clients_page"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in (
            "windows/Install-IKEv2.ps1",
            "windows/Install-IKEv2.bat",
            "windows/Check-Windows.bat",
            "windows/RAHNAMA.txt",
        ):
            z.writestr(Path(rel).name, load_client_template(rel, domain))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="IKEv2-windows.zip",
    )


@app.route("/clients/ios.mobileconfig")
@login_required
def clients_ios():
    domain = client_domain()
    if not domain:
        flash("دامنه در تنظیمات نیست.")
        return redirect(url_for("clients_page"))
    path = CLIENTS_DIR / "ios" / "IKEv2.mobileconfig"
    if not path.is_file():
        flash("فایل پروفایل iOS روی سرور نیست.")
        return redirect(url_for("clients_page"))
    data = load_client_template("ios/IKEv2.mobileconfig", domain).encode("utf-8")
    return send_file(
        io.BytesIO(data),
        mimetype="application/x-apple-aspen-config",
        as_attachment=True,
        download_name="IKEv2.mobileconfig",
    )


def ss_uri(name, u, cfg):
    key = u.get("ss_key") or ""
    port = int(u.get("ss_port") or 0)
    host = (cfg.get("domain") or cfg.get("public_ip") or "").strip()
    plain = "%s:%s" % (SS_METHOD, key)
    userinfo = base64.urlsafe_b64encode(plain.encode()).decode().rstrip("=")
    return "ss://%s@%s:%d#%s" % (userinfo, host, port, urllib.parse.quote(name))


def hy_uri(name, u, cfg):
    pw = u.get("password") or ""
    port = int(cfg.get("hy_port") or 443)
    domain = (cfg.get("domain") or "").strip()
    host = domain or (cfg.get("public_ip") or "").strip()
    auth = "%s:%s" % (urllib.parse.quote(name), urllib.parse.quote(pw))
    q = {"sni": domain, "insecure": "0"} if domain else {"insecure": "1"}
    return "hysteria2://%s@%s:%d/?%s#%s" % (
        auth,
        host,
        port,
        urllib.parse.urlencode(q),
        urllib.parse.quote(name),
    )


def qr_png(data):
    p = subprocess.run(
        ["qrencode", "-o", "-", "-t", "PNG", "-s", "6", "-m", "2", data],
        capture_output=True,
        timeout=5,
    )
    return p.stdout


@app.route("/clients/ss/<name>")
@login_required
def clients_ss(name):
    users = load_users()
    u = users.get(name)
    if not u or not u.get("ss_enabled"):
        flash("Shadowsocks برای این کاربر فعال نیست.")
        return redirect(url_for("clients_page"))
    cfg = load_config()
    uri = ss_uri(name, u, cfg)
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d.update(
        page="clients",
        page_title="Shadowsocks — %s" % name,
        page_subtitle="کانفیگ اتصال Shadowsocks (2022) این کاربر",
        proto_name="Shadowsocks",
        uri=uri,
        qr_url=url_for("clients_ss_qr", name=name),
        method=SS_METHOD,
        server_key="",
        user_key=u.get("ss_key") or "",
        port=u.get("ss_port"),
    )
    return render_template("client_proto.html", **d)


@app.route("/clients/ss/<name>/qr.png")
@login_required
def clients_ss_qr(name):
    users = load_users()
    u = users.get(name)
    if not u or not u.get("ss_enabled"):
        return ("", 404)
    png = qr_png(ss_uri(name, u, load_config()))
    return (png, 200, {"Content-Type": "image/png", "Cache-Control": "no-store"})


@app.route("/clients/hysteria/<name>")
@login_required
def clients_hysteria(name):
    users = load_users()
    u = users.get(name)
    if not u or not u.get("hy_enabled"):
        flash("Hysteria2 برای این کاربر فعال نیست.")
        return redirect(url_for("clients_page"))
    cfg = load_config()
    uri = hy_uri(name, u, cfg)
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d.update(
        page="clients",
        page_title="Hysteria2 — %s" % name,
        page_subtitle="کانفیگ اتصال Hysteria2 این کاربر",
        proto_name="Hysteria2",
        uri=uri,
        qr_url=url_for("clients_hysteria_qr", name=name),
        method="",
        server_key="",
        user_key="",
        port=cfg.get("hy_port"),
    )
    return render_template("client_proto.html", **d)


@app.route("/clients/hysteria/<name>/qr.png")
@login_required
def clients_hysteria_qr(name):
    users = load_users()
    u = users.get(name)
    if not u or not u.get("hy_enabled"):
        return ("", 404)
    png = qr_png(hy_uri(name, u, load_config()))
    return (png, 200, {"Content-Type": "image/png", "Cache-Control": "no-store"})


@app.route("/api/status")
@login_required
def api_status():
    d = dashboard_payload()
    return jsonify(
        {
            "online": d["online"],
            "online_count": d["online_count"],
            "total": d["total"],
            "sessions": [
                {
                    "user": s.get("user"),
                    "proto": s.get("proto"),
                    "vip": s.get("vip"),
                    "remote": s.get("remote"),
                    "uptime": s.get("uptime"),
                    "bytes_h": s.get("bytes_h"),
                }
                for s in d["sessions"]
            ],
            "cpu": d["stats"]["cpu"],
            "mem_pct": d["stats"]["mem_pct"],
            "load1": d["stats"]["load1"],
            "net_rx_h": d["net_rx_h"],
            "net_tx_h": d["net_tx_h"],
            "net_down_h": d["net_down_h"],
            "net_up_h": d["net_up_h"],
            "now_fa": d["now_fa"],
        }
    )


@app.route("/users/add", methods=["POST"])
@login_required
@csrf_required
def users_add():
    name = (request.form.get("name") or "").strip()
    password = (request.form.get("password") or "").strip()
    expires = (request.form.get("expires") or "").strip()
    quota = (request.form.get("quota_gb") or "0").strip() or "0"
    ss_enabled = request.form.get("ss_enabled") == "1"
    hy_enabled = request.form.get("hy_enabled") == "1"
    if not USER_RE.match(name):
        flash("نام کاربری فقط حروف انگلیسی و عدد، ۲ تا ۳۲ نویسه.")
        return redirect(url_for("users_page"))
    if not safe_secret(password, 12, 128):
        flash("رمز VPN باید ۱۲ تا ۶۴ نویسه و فقط شامل نویسه‌های امن انگلیسی باشد.")
        return redirect(url_for("users_page"))
    if expires:
        try:
            date.fromisoformat(expires)
        except ValueError:
            flash("تاریخ انقضا نامعتبر است.")
            return redirect(url_for("users_page"))
    try:
        q = float(quota)
        if not math.isfinite(q) or q < 0:
            raise ValueError()
    except ValueError:
        flash("حجم باید عدد باشد (۰ = نامحدود).")
        return redirect(url_for("users_page"))
    with _lock:
        users = load_users()
        if name in users:
            flash("این کاربر از قبل وجود دارد.")
            return redirect(url_for("users_page"))
        users[name] = {
            "password": password,
            "expires": expires,
            "quota_gb": q,
            "used_bytes": 0,
            "created": today_iso(),
            "enabled": True,
            "ss_enabled": ss_enabled,
            "hy_enabled": hy_enabled,
            "ss_key": new_ss_key() if ss_enabled else "",
            "ss_port": allocate_ss_port() if ss_enabled else None,
        }
        save_users(users)
        write_secrets(users)
        write_xray_ss_config(users)
        write_hysteria_config(users)
    proto_note = []
    if ss_enabled:
        proto_note.append("Shadowsocks")
    if hy_enabled:
        proto_note.append("Hysteria2")
    label = " + ".join(["IKEv2"] + proto_note)
    flash("کاربر %s اضافه شد (%s)." % (name, label))
    return redirect(url_for("users_page"))


@app.route("/users/update", methods=["POST"])
@login_required
@csrf_required
def users_update():
    name = (request.form.get("name") or "").strip()
    password = (request.form.get("password") or "").strip()
    expires = (request.form.get("expires") or "").strip()
    quota = (request.form.get("quota_gb") or "").strip()
    reset = request.form.get("reset_traffic") == "1"
    ss_enabled = request.form.get("ss_enabled") == "1"
    hy_enabled = request.form.get("hy_enabled") == "1"
    if not USER_RE.match(name):
        flash("نام کاربری نامعتبر است.")
        return redirect(url_for("users_page"))
    with _lock:
        users = load_users()
        if name not in users:
            flash("کاربر پیدا نشد.")
            return redirect(url_for("users_page"))
        if password:
            if not safe_secret(password, 12, 128):
                flash("رمز عبور نامعتبر است.")
                return redirect(url_for("users_page"))
            users[name]["password"] = password
        if expires:
            try:
                date.fromisoformat(expires)
            except ValueError:
                flash("تاریخ انقضا نامعتبر است.")
                return redirect(url_for("users_page"))
        users[name]["expires"] = expires
        if quota != "":
            try:
                q = float(quota)
                if not math.isfinite(q) or q < 0:
                    raise ValueError()
                users[name]["quota_gb"] = q
            except ValueError:
                flash("حجم نامعتبر است.")
                return redirect(url_for("users_page"))
        if reset:
            users[name]["used_bytes"] = 0
        users[name]["ss_enabled"] = ss_enabled
        users[name]["hy_enabled"] = hy_enabled
        if ss_enabled and not users[name].get("ss_key"):
            users[name]["ss_key"] = new_ss_key()
        if ss_enabled and not users[name].get("ss_port"):
            users[name]["ss_port"] = allocate_ss_port()
        save_users(users)
        write_secrets(users)
        write_xray_ss_config(users)
        write_hysteria_config(users)
    flash("تنظیمات کاربر %s ذخیره شد." % name)
    return redirect(url_for("users_page"))


@app.route("/users/delete", methods=["POST"])
@login_required
@csrf_required
def users_delete():
    name = (request.form.get("name") or "").strip()
    if not USER_RE.match(name):
        flash("نام کاربری نامعتبر است.")
        return redirect(url_for("users_page"))
    with _lock:
        users = load_users()
        if name not in users:
            flash("کاربر پیدا نشد.")
            return redirect(url_for("users_page"))
        users.pop(name)
        save_users(users)
        write_secrets(users)
        write_xray_ss_config(users)
        write_hysteria_config(users)
    flash("کاربر %s حذف شد." % name)
    return redirect(url_for("users_page"))


@app.route("/sessions/cleanup", methods=["POST"])
@login_required
@csrf_required
def sessions_cleanup():
    terminated = cleanup_excess_sessions()
    if terminated:
        flash("%s نشست قدیمی برای بسته‌شدن علامت‌گذاری شد." % fa(len(terminated)))
    else:
        flash("نشست اضافه‌ای پیدا نشد.")
    return redirect(url_for("sessions_page"))


@app.route("/sessions/delete", methods=["POST"])
@login_required
@csrf_required
def sessions_delete():
    session_id = (request.form.get("id") or "").strip()
    if not session_id.isdigit():
        flash("شناسهٔ نشست نامعتبر است.")
        return redirect(url_for("sessions_page"))
    selected = next(
        (
            item
            for item in parse_sessions()
            if item.get("proto") == "IKEv2" and str(item.get("id")) == session_id
        ),
        None,
    )
    if not selected:
        flash("نشست پیدا نشد یا قبلاً بسته شده است.")
        return redirect(url_for("sessions_page"))
    terminate_ike_session(selected)
    flash("نشست %s برای بسته‌شدن علامت‌گذاری شد." % fa(session_id))
    return redirect(url_for("sessions_page"))


@app.route("/settings/psk", methods=["POST"])
@login_required
@csrf_required
def settings_psk():
    psk = (request.form.get("psk") or "").strip()
    if not safe_secret(psk, 16, 128):
        flash("کلید مشترک باید ۱۶ تا ۱۲۸ نویسه و فقط شامل نویسه‌های امن انگلیسی باشد.")
        return redirect(url_for("settings"))
    with _lock:
        cfg = load_config()
        cfg["psk"] = psk
        save_config(cfg)
        write_secrets(load_users(), psk=psk)
    flash("کلید مشترک (PSK) عوض شد. کلاینت‌های L2TP باید PSK جدید بزنند.")
    return redirect(url_for("settings"))


@app.route("/settings/dns", methods=["POST"])
@login_required
@csrf_required
def settings_dns():
    raw = (request.form.get("dns") or "").strip()
    parts = [p.strip() for p in re.split(r"[, ]+", raw) if p.strip()]
    if not parts or len(parts) > 4:
        flash("یک تا چهار DNS وارد کنید.")
        return redirect(url_for("settings"))
    try:
        parts = [str(ipaddress.ip_address(p)) for p in parts]
    except ValueError:
        flash("DNS باید یک آدرس IPv4 یا IPv6 معتبر باشد.")
        return redirect(url_for("settings"))
    cfg = load_config()
    cfg["dns"] = parts
    save_config(cfg)
    if PPP_OPTS.exists():
        text = PPP_OPTS.read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if not ln.startswith("ms-dns ")]
        for d in parts[:2]:
            lines.append("ms-dns " + d)
        PPP_OPTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if IPSEC_CONF.exists() and parts:
        conf = IPSEC_CONF.read_text(encoding="utf-8", errors="replace")
        conf = re.sub(r"rightdns=.*", "rightdns=" + ",".join(parts[:2]), conf)
        IPSEC_CONF.write_text(conf, encoding="utf-8")
        run(["ipsec", "reload"])
    flash("DNS ذخیره شد. اتصال‌های بعدی با DNS جدید می‌آیند.")
    return redirect(url_for("settings"))


@app.route("/settings/admin", methods=["POST"])
@login_required
@csrf_required
def settings_admin():
    pw = (request.form.get("password") or "").strip()
    if len(pw) < 12 or len(pw) > 128:
        flash("رمز پنل باید ۱۲ تا ۱۲۸ نویسه باشد.")
        return redirect(url_for("settings"))
    data = load_admin()
    data["password"] = generate_password_hash(pw)
    save_admin(data)
    flash("رمز ورود پنل عوض شد.")
    return redirect(url_for("settings"))


@app.route("/settings/sessions", methods=["POST"])
@login_required
@csrf_required
def settings_sessions():
    raw = (request.form.get("max_sessions_per_user") or "").strip()
    try:
        limit = int(raw)
        if not 1 <= limit <= 10:
            raise ValueError()
    except ValueError:
        flash("تعداد نشست هم‌زمان باید بین ۱ تا ۱۰ باشد.")
        return redirect(url_for("settings"))
    with _lock:
        cfg = load_config()
        cfg["max_sessions_per_user"] = limit
        save_config(cfg)
        terminated = cleanup_excess_sessions()
    if terminated:
        flash("محدودیت ذخیره شد و %s نشست قدیمی بسته شد." % fa(len(terminated)))
    else:
        flash("محدودیت نشست‌های هم‌زمان ذخیره شد.")
    return redirect(url_for("settings"))


def collector_loop():
    while True:
        try:
            sample_traffic()
        except Exception:
            pass
        time.sleep(20)


def start_background():
    if getattr(app, "_collector", False):
        return
    app._collector = True
    t = threading.Thread(target=collector_loop, daemon=True)
    t.start()


if ADMIN_FILE.exists():
    load_admin()
start_background()

if __name__ == "__main__":
    load_admin()
    app.run(host="127.0.0.1", port=8765)
