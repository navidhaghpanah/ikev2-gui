#!/usr/bin/env python3
"""Telegram admin bot for the multi-VPN panel.

Reuses panel/app.py's user-management functions directly so behavior stays
identical to the web panel (same validation, same config writers). Admin-only:
every update is checked against config.json's telegram_admin_ids before any
command runs.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as panel  # noqa: E402

API_BASE = ""
# Per-chat in-progress "add user" flow. Lost on restart — acceptable for an
# admin operational tool; the admin just restarts the flow with /add.
FLOWS = {}


def api_call(method, **params):
    url = "%s/%s" % (API_BASE, method)
    data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send(chat_id, text, reply_markup=None, message_id=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    try:
        if message_id:
            params["message_id"] = message_id
            return api_call("editMessageText", **params)
        return api_call("sendMessage", **params)
    except urllib.error.HTTPError:
        params.pop("message_id", None)
        return api_call("sendMessage", **params)
    except (urllib.error.URLError, OSError):
        return None


def answer_callback(callback_id, text=""):
    try:
        api_call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except (urllib.error.URLError, OSError):
        pass


def is_admin(user_id):
    ids = panel.load_config().get("telegram_admin_ids") or []
    return int(user_id) in {int(i) for i in ids}


def kb(rows):
    return {"inline_keyboard": rows}


def status_emoji(u):
    block = panel.user_blocked(u)
    if block:
        return "🔴"
    return "🟢"


def main_menu():
    return kb(
        [
            [{"text": "👥 کاربران", "callback_data": "users:0"}],
            [{"text": "➕ افزودن کاربر", "callback_data": "add:start"}],
            [{"text": "📊 وضعیت سرور", "callback_data": "status"}],
        ]
    )


def fmt_status():
    hs = panel.host_stats()
    sessions = panel.parse_sessions()
    online = len({s["user"] for s in sessions if s.get("user")})
    users = panel.load_users()
    return (
        "📊 <b>وضعیت سرور</b>\n"
        "کاربران: %d (آنلاین: %d)\n"
        "CPU: %.1f%%  |  RAM: %.1f%%  |  دیسک: %.1f%%\n"
        "Load: %.2f"
        % (
            len(users),
            online,
            hs["cpu"],
            hs["mem_pct"],
            hs["disk_pct"],
            hs["load1"],
        )
    )


def users_page(page=0, per_page=8):
    users = panel.load_users()
    names = sorted(users.keys())
    total = len(names)
    start = page * per_page
    chunk = names[start : start + per_page]
    rows = []
    for name in chunk:
        u = users[name]
        rows.append([{"text": "%s %s" % (status_emoji(u), name), "callback_data": "user:%s" % name}])
    nav = []
    if page > 0:
        nav.append({"text": "◀ قبلی", "callback_data": "users:%d" % (page - 1)})
    if start + per_page < total:
        nav.append({"text": "بعدی ▶", "callback_data": "users:%d" % (page + 1)})
    if nav:
        rows.append(nav)
    rows.append([{"text": "🔙 منو", "callback_data": "menu"}])
    text = "👥 <b>کاربران</b> (%d نفر)" % total
    return text, kb(rows)


def fmt_user_detail(name, u):
    block = panel.user_blocked(u)
    status = ("مسدود: " + block) if block else "فعال"
    q = float(u.get("quota_gb") or 0)
    used = float(u.get("used_bytes") or 0)
    quota_h = "نامحدود" if q <= 0 else "%.1f GB" % q
    lines = [
        "👤 <b>%s</b>" % name,
        "وضعیت: %s" % status,
        "انقضا: %s" % (u.get("expires") or "نامحدود"),
        "مصرف: %s از %s" % (panel.human(used), quota_h),
        "Shadowsocks: %s" % ("فعال (پورت %s)" % u.get("ss_port") if u.get("ss_enabled") else "غیرفعال"),
        "Hysteria2: %s" % ("فعال" if u.get("hy_enabled") else "غیرفعال"),
    ]
    return "\n".join(lines)


def user_detail_kb(name, u):
    ss_label = "🔴 خاموش‌کردن SS" if u.get("ss_enabled") else "🟢 روشن‌کردن SS"
    hy_label = "🔴 خاموش‌کردن Hysteria2" if u.get("hy_enabled") else "🟢 روشن‌کردن Hysteria2"
    en_label = "⛔ غیرفعال‌کردن" if u.get("enabled", True) else "✅ فعال‌کردن"
    return kb(
        [
            [{"text": "🔄 صفرکردن مصرف", "callback_data": "reset:%s" % name}],
            [{"text": ss_label, "callback_data": "toggle:%s:ss" % name}],
            [{"text": hy_label, "callback_data": "toggle:%s:hy" % name}],
            [{"text": en_label, "callback_data": "toggle:%s:enabled" % name}],
            [{"text": "❌ حذف کاربر", "callback_data": "del:%s:ask" % name}],
            [{"text": "🔙 لیست کاربران", "callback_data": "users:0"}],
        ]
    )


def apply_user_change(name, users):
    with panel._lock:
        panel.save_users(users)
        panel.write_secrets(users)
        panel.write_xray_ss_config(users)
        panel.write_hysteria_config(users)


def handle_users(chat_id, message_id, page):
    text, markup = users_page(page)
    send(chat_id, text, markup, message_id)


def handle_user_detail(chat_id, message_id, name):
    users = panel.load_users()
    u = users.get(name)
    if not u:
        send(chat_id, "کاربر پیدا نشد.", main_menu(), message_id)
        return
    send(chat_id, fmt_user_detail(name, u), user_detail_kb(name, u), message_id)


def handle_toggle(chat_id, message_id, name, field):
    users = panel.load_users()
    u = users.get(name)
    if not u:
        send(chat_id, "کاربر پیدا نشد.", main_menu(), message_id)
        return
    if field == "ss":
        u["ss_enabled"] = not u.get("ss_enabled")
        if u["ss_enabled"] and not u.get("ss_key"):
            u["ss_key"] = panel.new_ss_key()
        if u["ss_enabled"] and not u.get("ss_port"):
            u["ss_port"] = panel.allocate_ss_port()
    elif field == "hy":
        u["hy_enabled"] = not u.get("hy_enabled")
    elif field == "enabled":
        u["enabled"] = not u.get("enabled", True)
    apply_user_change(name, users)
    send(chat_id, fmt_user_detail(name, u), user_detail_kb(name, u), message_id)


def handle_reset(chat_id, message_id, name):
    users = panel.load_users()
    u = users.get(name)
    if not u:
        send(chat_id, "کاربر پیدا نشد.", main_menu(), message_id)
        return
    u["used_bytes"] = 0
    apply_user_change(name, users)
    send(chat_id, "مصرف %s صفر شد.\n\n" % name + fmt_user_detail(name, u), user_detail_kb(name, u), message_id)


def handle_delete_ask(chat_id, message_id, name):
    send(
        chat_id,
        "❗ حذف کاربر <b>%s</b> برگشت‌ناپذیر است. مطمئنید؟" % name,
        kb(
            [
                [{"text": "بله، حذف شود", "callback_data": "del:%s:confirm" % name}],
                [{"text": "انصراف", "callback_data": "user:%s" % name}],
            ]
        ),
        message_id,
    )


def handle_delete_confirm(chat_id, message_id, name):
    with panel._lock:
        users = panel.load_users()
        if name in users:
            users.pop(name)
            panel.save_users(users)
            panel.write_secrets(users)
            panel.write_xray_ss_config(users)
            panel.write_hysteria_config(users)
    text, markup = users_page(0)
    send(chat_id, "کاربر %s حذف شد.\n\n%s" % (name, text), markup, message_id)


def start_add_flow(chat_id, message_id):
    FLOWS[chat_id] = {"step": "name", "data": {}}
    send(chat_id, "نام کاربری جدید را بفرستید (فقط حروف/عدد انگلیسی، ۲ تا ۳۲ نویسه):", None, message_id)


def continue_add_flow(chat_id, text):
    flow = FLOWS.get(chat_id)
    if not flow:
        return False
    step = flow["step"]
    data = flow["data"]
    if step == "name":
        name = text.strip()
        if not panel.USER_RE.match(name):
            send(chat_id, "نام نامعتبر است، دوباره بفرستید.")
            return True
        if name in panel.load_users():
            send(chat_id, "این کاربر از قبل وجود دارد. نام دیگری بفرستید.")
            return True
        data["name"] = name
        flow["step"] = "password"
        send(chat_id, "رمز عبور را بفرستید (۱۲ تا ۱۲۸ نویسه) یا فقط - بفرستید تا خودکار ساخته شود:")
        return True
    if step == "password":
        pw = text.strip()
        if pw == "-":
            import secrets as _secrets

            pw = _secrets.token_urlsafe(12)[:16]
        if not panel.safe_secret(pw, 12, 128):
            send(chat_id, "رمز نامعتبر است (۱۲ تا ۱۲۸ نویسه، فقط کاراکترهای امن انگلیسی). دوباره بفرستید یا - بزنید:")
            return True
        data["password"] = pw
        flow["step"] = "quota"
        send(chat_id, "سهمیه به گیگابایت را بفرستید (۰ یعنی نامحدود):")
        return True
    if step == "quota":
        try:
            q = float(text.strip())
            if q < 0:
                raise ValueError()
        except ValueError:
            send(chat_id, "عدد نامعتبر است. سهمیه به گیگابایت را بفرستید (۰ یعنی نامحدود):")
            return True
        data["quota_gb"] = q
        flow["step"] = "protocols"
        send(
            chat_id,
            "پروتکل‌های اضافه روی این کاربر فعال بشه؟",
            kb(
                [
                    [{"text": "فقط IKEv2", "callback_data": "addproto:none"}],
                    [{"text": "+ Shadowsocks", "callback_data": "addproto:ss"}],
                    [{"text": "+ Hysteria2", "callback_data": "addproto:hy"}],
                    [{"text": "+ هر دو", "callback_data": "addproto:both"}],
                ]
            ),
        )
        return True
    return True


def finish_add_flow(chat_id, message_id, proto_choice):
    flow = FLOWS.pop(chat_id, None)
    if not flow:
        return
    data = flow["data"]
    name = data["name"]
    ss_enabled = proto_choice in ("ss", "both")
    hy_enabled = proto_choice in ("hy", "both")
    with panel._lock:
        users = panel.load_users()
        if name in users:
            send(chat_id, "این کاربر همین حین توسط جای دیگه‌ای ساخته شد.", main_menu(), message_id)
            return
        users[name] = {
            "password": data["password"],
            "expires": "",
            "quota_gb": data["quota_gb"],
            "used_bytes": 0,
            "created": panel.today_iso(),
            "enabled": True,
            "ss_enabled": ss_enabled,
            "hy_enabled": hy_enabled,
            "ss_key": panel.new_ss_key() if ss_enabled else "",
            "ss_port": panel.allocate_ss_port() if ss_enabled else None,
        }
        panel.save_users(users)
        panel.write_secrets(users)
        panel.write_xray_ss_config(users)
        panel.write_hysteria_config(users)
    send(
        chat_id,
        "✅ کاربر ساخته شد.\n\nنام: <code>%s</code>\nرمز: <code>%s</code>\n\n%s"
        % (name, data["password"], fmt_user_detail(name, users[name])),
        user_detail_kb(name, users[name]),
        message_id,
    )


def process_message(msg):
    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id")
    if not is_admin(user_id):
        return
    text = (msg.get("text") or "").strip()
    if chat_id in FLOWS and text and not text.startswith("/"):
        continue_add_flow(chat_id, text)
        return
    if text in ("/start", "/help"):
        send(chat_id, "🤖 پنل مدیریت VPN — از منو استفاده کنید.", main_menu())
    elif text == "/users":
        t, m = users_page(0)
        send(chat_id, t, m)
    elif text == "/add":
        start_add_flow(chat_id, None)
    elif text == "/status":
        send(chat_id, fmt_status(), main_menu())


def process_callback(cq):
    chat_id = cq["message"]["chat"]["id"]
    message_id = cq["message"]["message_id"]
    user_id = cq.get("from", {}).get("id")
    data = cq.get("data") or ""
    answer_callback(cq["id"])
    if not is_admin(user_id):
        return
    try:
        if data == "menu":
            send(chat_id, "🤖 پنل مدیریت VPN", main_menu(), message_id)
        elif data == "status":
            send(chat_id, fmt_status(), main_menu(), message_id)
        elif data.startswith("users:"):
            handle_users(chat_id, message_id, int(data.split(":", 1)[1]))
        elif data.startswith("user:"):
            handle_user_detail(chat_id, message_id, data.split(":", 1)[1])
        elif data.startswith("toggle:"):
            _, name, field = data.split(":", 2)
            handle_toggle(chat_id, message_id, name, field)
        elif data.startswith("reset:"):
            handle_reset(chat_id, message_id, data.split(":", 1)[1])
        elif data.startswith("del:"):
            _, name, action = data.split(":", 2)
            if action == "ask":
                handle_delete_ask(chat_id, message_id, name)
            elif action == "confirm":
                handle_delete_confirm(chat_id, message_id, name)
        elif data == "add:start":
            start_add_flow(chat_id, message_id)
        elif data.startswith("addproto:"):
            finish_add_flow(chat_id, message_id, data.split(":", 1)[1])
    except Exception as e:
        send(chat_id, "خطا: %s" % e, main_menu())


def process_update(update):
    if "message" in update:
        process_message(update["message"])
    elif "callback_query" in update:
        process_callback(update["callback_query"])


def main():
    global API_BASE
    cfg = panel.load_config()
    token = cfg.get("telegram_bot_token") or ""
    if not token:
        print("no telegram_bot_token configured, exiting")
        return
    API_BASE = "https://api.telegram.org/bot%s" % token
    offset = 0
    while True:
        try:
            resp = api_call("getUpdates", offset=offset, timeout=30)
        except (urllib.error.URLError, OSError):
            time.sleep(3)
            continue
        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            try:
                process_update(update)
            except Exception as e:
                print("update error:", e)


if __name__ == "__main__":
    main()
