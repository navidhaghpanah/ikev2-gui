# IKEv2 & L2TP GUI

پنل مدیریت فارسی برای VPN روی **Ubuntu 22.04 / 24.04**: IKEv2 (گواهی Let’s Encrypt + EAP-MSCHAPv2) و L2TP/IPsec (PSK) روی یک سرور.

## امکانات

- داشبورد فارسی RTL
- کاربر جدید با **تاریخ انقضا** و **حجم (گیگابایت)**
- نمایش افراد آنلاین، نشست‌ها، ترافیک
- پردازنده، RAM، بار سیستم
- تغییر PSK از پنل
- DNS تونل
- اسکریپت نصب تعاملی: دامنه، SSL، یوزر پنل، PSK

## نصب

دامنه را از قبل به IP سرور اشاره بده، پورت‌های **TCP 80/443** و **UDP 500/4500/1701** باز باشند.

```bash
git clone https://github.com/navidhaghpanah/ikev2-l2tp-gui.git
cd ikev2-l2tp-gui
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

**IKEv2 (آیفون — پیشنهادی)**

- نوع: IKEv2
- Server و Remote ID: همان دامنه
- Local ID خالی، Certificate: None
- یوزر و پس از پنل

**L2TP**

- نوع: L2TP
- Server: دامنه
- Secret: همان PSK
- Send All Traffic روشن

روی iOS جدید L2TP اغلب وصل می‌شود ولی اینترنت نمی‌دهد؛ IKEv2 را استفاده کنید.

## مسیر فایل‌ها

| مسیر | نقش |
|---|---|
| `/opt/ikev2-l2tp-gui` | کد پنل |
| `/etc/ikev2-l2tp-gui` | config و ادمین |
| `/var/lib/ikev2-l2tp-gui` | کاربران و ترافیک |
| `/etc/ipsec.conf` `/etc/ipsec.secrets` | strongSwan |
| `/etc/xl2tpd` `/etc/ppp` | L2TP |

حذف پنل: `sudo bash uninstall.sh`

## مجوز

MIT — Navid Haghpanah
