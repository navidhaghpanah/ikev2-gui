#!/usr/bin/env python3
# IKEv2 GUI — پنل مدیریت
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
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
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 12

_cpu_prev = None
_lock = threading.Lock()


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
        },
    )
    return cfg


def save_config(cfg):
    save_json(CONFIG_FILE, cfg)


def load_admin():
    data = load_json(ADMIN_FILE, {})
    if data.get("secret"):
        app.secret_key = data["secret"]
    app.config["SESSION_COOKIE_SECURE"] = bool(load_config().get("https", True))
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
        else:
            users[name]["password"] = pw
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
    q = float(u.get("quota_gb") or 0)
    if q > 0 and float(u.get("used_bytes") or 0) >= q * (1024 ** 3):
        return "اتمام حجم"
    return ""


def write_secrets(users, psk=None, public_ip=None, domain=None):
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
        lines.append('%s : EAP "%s"' % (name, pw))
        chap.append('%s  l2tpd  "%s"  *' % (name, pw))
    IPSEC_SECRETS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(IPSEC_SECRETS, 0o600)
    CHAP_SECRETS.write_text("\n".join(chap) + "\n", encoding="utf-8")
    os.chmod(CHAP_SECRETS, 0o600)
    run(["ipsec", "rereadsecrets"])


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


def sample_traffic():
    users = load_users()
    snap = load_json(SNAP_FILE, {})
    sessions = parse_sessions()
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
    if changed:
        save_users(users)
    save_json(SNAP_FILE, new_snap)
    blocked_now = False
    for name, u in users.items():
        if user_blocked(u) and u.get("enabled", True):
            # keep enabled flag, blocked by date/quota
            blocked_now = True
    if blocked_now or changed:
        write_secrets(users)
    return users, sessions


def host_stats():
    global _cpu_prev
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
        "psk": cfg.get("psk") or "",
        "dns": ",".join(cfg.get("dns") or []),
        "stats": hs,
        "cpu_fa": fa(hs["cpu"]),
        "mem_fa": fa(hs["mem_pct"]),
        "mem_used_h": human(hs["mem_used"]),
        "mem_total_h": human(hs["mem_total"]),
        "disk_fa": fa(hs["disk_pct"]),
        "load_fa": fa("%.2f" % hs["load1"]),
        "uptime_h": fmt_uptime(hs["uptime"]),
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
        admin = load_admin()
        user = (request.form.get("user") or "").strip()
        pw = request.form.get("password") or ""
        if user == admin.get("user") and admin.get("password") and check_password_hash(admin["password"], pw):
            session["ok"] = True
            session.permanent = True
            return redirect(url_for("index"))
        err = "نام کاربری یا رمز عبور اشتباه است."
    cfg = load_config()
    return render_template("login.html", err=err, host=cfg.get("domain") or "")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d["page"] = "dash"
    return render_template("index.html", **d)


@app.route("/settings")
@login_required
def settings():
    d = dashboard_payload()
    d["admin_user"] = load_admin().get("user") or ""
    d["page"] = "settings"
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
        return redirect(url_for("index"))
    if not (CLIENTS_DIR / "windows" / "Install-IKEv2.ps1").is_file():
        flash("فایل کلاینت ویندوز روی سرور نیست.")
        return redirect(url_for("index"))
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
        return redirect(url_for("index"))
    path = CLIENTS_DIR / "ios" / "IKEv2.mobileconfig"
    if not path.is_file():
        flash("فایل پروفایل iOS روی سرور نیست.")
        return redirect(url_for("index"))
    data = load_client_template("ios/IKEv2.mobileconfig", domain).encode("utf-8")
    return send_file(
        io.BytesIO(data),
        mimetype="application/x-apple-aspen-config",
        as_attachment=True,
        download_name="IKEv2.mobileconfig",
    )


@app.route("/api/status")
@login_required
def api_status():
    d = dashboard_payload()
    d.pop("psk", None)
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
            "now_fa": d["now_fa"],
        }
    )


@app.route("/users/add", methods=["POST"])
@login_required
def users_add():
    name = (request.form.get("name") or "").strip()
    password = (request.form.get("password") or "").strip()
    expires = (request.form.get("expires") or "").strip()
    quota = (request.form.get("quota_gb") or "0").strip() or "0"
    if not USER_RE.match(name):
        flash("نام کاربری فقط حروف انگلیسی و عدد، ۲ تا ۳۲ نویسه.")
        return redirect(url_for("index"))
    if len(password) < 4 or len(password) > 64 or '"' in password:
        flash("رمز عبور ۴ تا ۶۴ نویسه باشد و گیومه نداشته باشد.")
        return redirect(url_for("index"))
    if expires:
        try:
            date.fromisoformat(expires)
        except ValueError:
            flash("تاریخ انقضا نامعتبر است.")
            return redirect(url_for("index"))
    try:
        q = float(quota)
        if q < 0:
            raise ValueError()
    except ValueError:
        flash("حجم باید عدد باشد (۰ = نامحدود).")
        return redirect(url_for("index"))
    with _lock:
        users = load_users()
        if name in users:
            flash("این کاربر از قبل وجود دارد.")
            return redirect(url_for("index"))
        users[name] = {
            "password": password,
            "expires": expires,
            "quota_gb": q,
            "used_bytes": 0,
            "created": today_iso(),
            "enabled": True,
        }
        save_users(users)
        write_secrets(users)
    flash("کاربر %s اضافه شد (IKEv2)." % name)
    return redirect(url_for("index"))


@app.route("/users/update", methods=["POST"])
@login_required
def users_update():
    name = (request.form.get("name") or "").strip()
    password = (request.form.get("password") or "").strip()
    expires = (request.form.get("expires") or "").strip()
    quota = (request.form.get("quota_gb") or "").strip()
    reset = request.form.get("reset_traffic") == "1"
    if not USER_RE.match(name):
        flash("نام کاربری نامعتبر است.")
        return redirect(url_for("index"))
    with _lock:
        users = load_users()
        if name not in users:
            flash("کاربر پیدا نشد.")
            return redirect(url_for("index"))
        if password:
            if len(password) < 4 or '"' in password:
                flash("رمز عبور نامعتبر است.")
                return redirect(url_for("index"))
            users[name]["password"] = password
        if expires:
            try:
                date.fromisoformat(expires)
            except ValueError:
                flash("تاریخ انقضا نامعتبر است.")
                return redirect(url_for("index"))
        users[name]["expires"] = expires
        if quota != "":
            try:
                q = float(quota)
                if q < 0:
                    raise ValueError()
                users[name]["quota_gb"] = q
            except ValueError:
                flash("حجم نامعتبر است.")
                return redirect(url_for("index"))
        if reset:
            users[name]["used_bytes"] = 0
        save_users(users)
        write_secrets(users)
    flash("تنظیمات کاربر %s ذخیره شد." % name)
    return redirect(url_for("index"))


@app.route("/users/delete", methods=["POST"])
@login_required
def users_delete():
    name = (request.form.get("name") or "").strip()
    if not USER_RE.match(name):
        flash("نام کاربری نامعتبر است.")
        return redirect(url_for("index"))
    with _lock:
        users = load_users()
        if name not in users:
            flash("کاربر پیدا نشد.")
            return redirect(url_for("index"))
        users.pop(name)
        save_users(users)
        write_secrets(users)
    flash("کاربر %s حذف شد." % name)
    return redirect(url_for("index"))


@app.route("/settings/psk", methods=["POST"])
@login_required
def settings_psk():
    psk = (request.form.get("psk") or "").strip()
    if len(psk) < 8 or '"' in psk or " " in psk:
        flash("کلید مشترک حداقل ۸ نویسه، بدون فاصله و گیومه.")
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
def settings_dns():
    raw = (request.form.get("dns") or "").strip()
    parts = [p.strip() for p in re.split(r"[, ]+", raw) if p.strip()]
    if not parts or len(parts) > 4:
        flash("یک تا چهار DNS وارد کنید.")
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
def settings_admin():
    pw = (request.form.get("password") or "").strip()
    if len(pw) < 4:
        flash("رمز پنل خیلی کوتاه است.")
        return redirect(url_for("settings"))
    data = load_admin()
    data["password"] = generate_password_hash(pw)
    save_admin(data)
    flash("رمز ورود پنل عوض شد.")
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
