# کلاینت IKEv2

قالب‌ها `__DOMAIN__` دارند. نصب‌کننده و پنل دامنه را جایگزین می‌کنند.

## ویندوز

فایل‌ها: `windows/Install-IKEv2.bat` + `Install-IKEv2.ps1`

1. `Install-IKEv2.bat` را با Run as administrator اجرا کنید.
2. Settings → Network → VPN → **IKEv2** → Connect
3. یوزر و پس همان کاربر پنل

اگر سرویس RasMan بالا نیاید (خطای ۱۰۶۲)، `Check-Windows.bat` را اجرا کنید. استک VPN ویندوز خراب با این اسکریپت تعمیر نمی‌شود.

## آیفون / آیپد

فایل: `ios/IKEv2.mobileconfig`

1. فایل را به گوشی بفرستید (AirDrop / تلگرام / Files).
2. روی فایل بزنید → **Profile Downloaded**
3. Settings → Profile Downloaded (یا General → VPN & Device Management) → Install
4. Settings → VPN → **IKEv2** → Connect
5. یوزر و پس همان کاربر پنل

هشدار Not Signed برای پروفایل شخصی عادی است.

## اندروید

اپ **strongSwan VPN Client** (Play Store):

- Type: **IKEv2 EAP (Username/Password)**
- Server و IKEv2 Server identity: همان دامنه
- CA certificate: select automatically / از سرور
- یوزر و پس همان کاربر پنل

روی سامسونگ VPN داخلی: Type = **IKEv2/IPSec MSCHAPv2** — نه PSK و نه RSA.
