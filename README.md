# Multi-VPN Panel

پنل مدیریت فارسی برای VPN روی **Ubuntu 22.04 / 24.04**: IKEv2 (گواهی Let’s Encrypt + EAP-MSCHAPv2)، به‌همراه پشتیبانی اختیاری از **VLESS + TLS**، **Shadowsocks (2022)** و **Hysteria2** با مدیریت متمرکز کاربر.

## امکانات

- پنل مدیریتی فارسی و واکنش‌گرا با صفحات مستقل داشبورد، کاربران، نشست‌ها، کلاینت‌ها و تنظیمات
- یک هویت (نام‌کاربری/رمز) مشترک برای IKEv2، VLESS، Shadowsocks و Hysteria2 — هرکدام اختیاری، به‌ازای هر کاربر
- کاربر جدید با **تاریخ انقضا** و **حجم (گیگابایت)** مشترک بین همه پروتکل‌ها
- محدودیت تعداد دستگاه هم‌زمان به‌ازای هر کاربر (پیش‌فرض ۱)، روی همه‌ی پروتکل‌ها اعمال می‌شود
- نمایش افراد آنلاین، نشست‌ها، ترافیک
- قطع دستی نشست و پاک‌سازی خودکار نشست‌های قدیمی با سقف قابل‌تنظیم برای هر کاربر
- کد QR و لینک اتصال اختصاصی برای VLESS/Shadowsocks/Hysteria2 هر کاربر، به‌علاوه لینک اشتراک (subscription) قابل‌به‌روزرسانی
- پردازنده، RAM، بار سیستم
- سرعت لحظه‌ای و مجموع دانلود/آپلود سرور، مشابه پارامترهای nload
- تغییر PSK از پنل
- DNS تونل
- اسکریپت نصب تعاملی: دامنه، SSL، یوزر پنل، PSK

## پروتکل‌های اضافه (VLESS / Shadowsocks / Hysteria2)

علاوه بر IKEv2، سه پروتکل زیر هم پشتیبانی می‌شوند. هر سه با همان کاربرِ پنل مدیریت می‌شوند و تاریخ انقضا، حجم و محدودیت دستگاه بین‌شان مشترک است.

| پروتکل | سرویس | پورت پیش‌فرض | احراز هویت |
|---|---|---|---|
| VLESS + TLS | `panel-shadowsocks.service` (xray-core) | TCP `8443` | UUID اختصاصی هر کاربر |
| Shadowsocks 2022 | `panel-shadowsocks.service` (xray-core) | TCP/UDP از `8388` به بالا، یکی برای هر کاربر | کلید اختصاصی هر کاربر (`2022-blake3-aes-128-gcm`) |
| Hysteria2 | `panel-hysteria.service` | UDP `443` | نام‌کاربری/رمز، همان رمز IKEv2 |

نکته‌ها:

- **VLESS و Shadowsocks هر دو داخل یک نمونه‌ی `xray-core` اجرا می‌شوند** — یعنی سرویس `panel-shadowsocks` هر دو را با هم سرو می‌کند. VLESS یک پورت مشترک برای همه‌ی کاربران دارد (هر کلاینت با UUID خودش شناخته می‌شود)، ولی Shadowsocks-2022 به‌خاطر ساختار handshake برای هر کاربر یک پورت جدا می‌گیرد.
- VLESS و Hysteria2 از همان گواهی Let’s Encrypt دامنه استفاده می‌کنند؛ تا وقتی گواهی صادر نشده باشد این دو بالا نمی‌آیند.
- Hysteria2 روی UDP کار می‌کند، پس با nginx که TCP 443 را گرفته تداخلی ندارد. مبهم‌سازی (obfuscation) از نوع `salamander` فعال است.
- کانفیگ هر سه را خود پنل (`panel/app.py`) از روی `users.json` می‌سازد و با هر تغییر کاربر به‌روز می‌کند — فایل‌ها را دستی ویرایش نکنید، بازنویسی می‌شوند.
- از نسخه‌ی فعلی به بعد، `install.sh` باینری‌های `xray-core` و `hysteria` و یونیت‌های systemd هر دو را خودش نصب می‌کند. سرویس‌ها `ConditionPathExists` دارند، یعنی تا وقتی پنل کانفیگ‌شان را ننوشته باشد بی‌سروصدا اجرا نمی‌شوند.

## نصب

دامنه را از قبل به IP سرور اشاره بده و این پورت‌ها باز باشند:

| پورت | برای |
|---|---|
| TCP 80/443 | پنل، Let’s Encrypt |
| UDP 500/4500/1701 | IKEv2 / L2TP |
| TCP 8443 | VLESS + TLS |
| UDP 443 | Hysteria2 |
| TCP/UDP 8388 به بالا | Shadowsocks (یک پورت برای هر کاربر) |

اگر `ufw` فعال باشد، `install.sh` پورت‌های سه پروتکل اضافه را خودش باز می‌کند.

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
| `/opt/panel-xray` `/etc/panel-xray/config.json` | باینری و کانفیگ VLESS + Shadowsocks |
| `/opt/panel-hysteria` `/etc/panel-hysteria/config.yaml` | باینری و کانفیگ Hysteria2 |

حذف پنل: `sudo bash uninstall.sh`

## مجوز

MIT
