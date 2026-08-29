# Multi-VPN Panel

پنل مدیریت فارسی برای VPN روی **Ubuntu 22.04 / 24.04**: IKEv2 (گواهی Let’s Encrypt + EAP-MSCHAPv2)، به‌همراه پشتیبانی اختیاری از **Shadowsocks (2022)** و **Hysteria2** با مدیریت متمرکز کاربر.

## امکانات

- پنل مدیریتی فارسی و واکنش‌گرا با صفحات مستقل داشبورد، کاربران، نشست‌ها، کلاینت‌ها و تنظیمات
- یک هویت (نام‌کاربری/رمز) مشترک برای IKEv2، Shadowsocks و Hysteria2 — هرکدام اختیاری، به‌ازای هر کاربر
- کاربر جدید با **تاریخ انقضا** و **حجم (گیگابایت)** مشترک بین همه پروتکل‌ها
- محدودیت تعداد دستگاه هم‌زمان به‌ازای هر کاربر (پیش‌فرض ۱)، روی هر سه پروتکل اعمال می‌شود
- نمایش افراد آنلاین، نشست‌ها، ترافیک
- قطع دستی نشست و پاک‌سازی خودکار نشست‌های قدیمی با سقف قابل‌تنظیم برای هر کاربر
- کد QR و لینک اتصال اختصاصی برای Shadowsocks/Hysteria2 هر کاربر
- پردازنده، RAM، بار سیستم
- سرعت لحظه‌ای و مجموع دانلود/آپلود سرور، مشابه پارامترهای nload
- تغییر PSK از پنل
- DNS تونل
- اسکریپت نصب تعاملی: دامنه، SSL، یوزر پنل، PSK

## پروتکل‌های اضافه (Shadowsocks / Hysteria2)

این دو پروتکل با دو سرویس مجزا اجرا می‌شوند — یک نمونه‌ی مستقل `xray-core` (`panel-shadowsocks.service`، هر کاربر با پورت اختصاصی خودش) و `hysteria` (`panel-hysteria.service`، احراز هویت چندکاربره‌ی native با همان رمز IKEv2). فعلاً نصب این دو باینری و سرویس‌ها بخشی از `install.sh` نیست و باید جدا فراهم شوند؛ خود پنل (`panel/app.py`) کانفیگ‌شان را بر اساس `users.json` می‌سازد و روی تغییر کاربران به‌روزشان می‌کند.

## نصب

دامنه را از قبل به IP سرور اشاره بده، پورت‌های **TCP 80/443** و **UDP 500/4500/1701** باز باشند.

```bash
git clone https://github.com/navidhaghpanah/multivpn-panel.git
cd multivpn-panel
sudo bash install.sh
```

نصب می‌پرسد:

| سؤال | توضیح |
|---|---|
| Domain | مثلا `vpn.example.com` |
| IP | معمولا خودکار پر می‌شود |
| Email | برای Let’s Encrypt — می‌تواند خالی باشد |
| PSK | کلید L2TP، حداقل ۸ نویسه |
| User/Pass پنل | ورود به GUI |
| اولین کاربر VPN | اختیاری |

نصب غیرتعاملی:

```bash
sudo DOMAIN=vpn.example.com \
  PUBLIC_IP=1.2.3.4 \
  PSK=YourLongPskHere \
  PANEL_USER=admin \
  PANEL_PASS='ChangeMe' \
  VPN_USER=user1 \
  VPN_PASS='ChangeMe' \
  NONINTERACTIVE=1 \
  bash install.sh
```

بعد از نصب: `https://دامنه`

## اتصال کلاینت

بعد از نصب، از داشبورد پنل دانلود کنید (ویندوز zip / آیفون mobileconfig) یا از `/opt/ikev2-l2tp-gui/clients/out/`. قالب‌ها در پوشه [`clients/`](clients/README.md) هستند.

**ویندوز**

- `Install-IKEv2.bat` را با Run as administrator اجرا کنید
- Settings → Network → VPN → IKEv2 → Connect
- یوزر و پس همان کاربر پنل
- اگر RasMan خطای ۱۰۶۲ داد، `Check-Windows.bat` را اجرا کنید؛ استک خراب ویندوز با این اسکریپت تعمیر نمی‌شود

**IKEv2 (آیفون — پیشنهادی)**

- فایل `IKEv2.mobileconfig` را روی گوشی باز کنید → Settings → Profile Downloaded → Install
- یا دستی: نوع IKEv2، Server و Remote ID همان دامنه، Local ID خالی، Certificate: None
- یوزر و پس از پنل

**اندروید**

- اپ strongSwan VPN Client، نوع **IKEv2 EAP (Username/Password)**
- روی سامسونگ داخلی: **IKEv2/IPSec MSCHAPv2** — نه PSK و نه RSA

## مسیر فایل‌ها

| مسیر | نقش |
|---|---|
| `/opt/ikev2-l2tp-gui` | کد پنل |
| `/etc/ikev2-l2tp-gui` | config و ادمین |
| `/var/lib/ikev2-l2tp-gui` | کاربران و ترافیک |
| `/etc/ipsec.conf` `/etc/ipsec.secrets` | strongSwan |

حذف پنل: `sudo bash uninstall.sh`

## مجوز

MIT
