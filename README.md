# پایش ساب VLESS + Reality با GitHub Actions

این پوشه آمادهٔ آپلود به یک مخزن GitHub است. هر ۶ ساعت، GitHub Actions لینک‌های فایل `config/source.txt` را با Xray بررسی می‌کند و دو فایل خروجی می‌سازد:

- `dist/active.txt` — لینک‌های خام، یک لینک در هر خط
- `dist/active.base64.txt` — همان ساب به‌شکل Base64

## محدودیت منبع

فایل `config/source.txt` شامل ۸۴ لینک کامل VLESS + Reality از snapshot عمومی هم‌زمان با صفحهٔ IPSpeed است. صفحهٔ IPSpeed لینک‌ها را کوتاه می‌کند و در بررسی ما export/API ماشین‌خوانِ قابل‌اتکایی پیدا نشد؛ بنابراین این workflow **فهرست تازهٔ IPSpeed را خودش scrape نمی‌کند**. برای افزودن نودهای جدید، لینک کامل را به `config/source.txt` اضافه و push کنید. نودها از صفحهٔ IPSpeed اصلی نیستند یا فعال‌اند، مگر اینکه خودتان آن‌ها را وارد و Actions با موفقیت بررسی کند.

## روش بررسی

1. Xray URI و JSON تنظیمات را اعتبارسنجی می‌کند.
2. Xray برای هر نود یک SOCKS محلی موقت باز می‌کند.
3. یک درخواست HTTPS کم‌حجم از داخل پروکسی به یک endpoint عمومی فرستاده می‌شود؛ اگر اولی در دسترس نباشد، یک endpoint دوم امتحان می‌شود.
4. هم‌زمان حداکثر ۴ نود آزمایش می‌شوند. از GitHub Actions فقط در حد اتصال و درخواست سبک استفاده می‌شود.
5. بعد از **دو بار ناموفقِ پیاپی**، نودی که قبلاً موفق بوده از خروجی فعال کنار گذاشته می‌شود. یک fail منفرد را موقت تلقی می‌کنیم. نود جدید تا وقتی حداقل یک بار تست واقعی را پاس نکند وارد ساب فعال نمی‌شود.
6. اگر هیچ نودی فعال نماند، فایل ساب قبلی بازنویسی نمی‌شود تا یک خروجی خالی منتشر نشود.

این تست از IP خروجی runnerهای GitHub انجام می‌شود، نه از اینترنت یا کشور شما؛ بعضی سرورها ممکن است IPهای دیتاسنتری را مسدود کنند. نتیجه، تضمین سرعت یا دسترس‌پذیری برای شما نیست.

## راه‌اندازی دستی

### ساخت مخزن جدید

1. GitHub را باز کنید و یک مخزن جدید بسازید؛ مثلاً `ipspeed-vless-monitor`.
2. این پوشه را در رایانه‌تان unzip کنید، سپس در ترمینال داخل آن اجرا کنید:

```bash
git init -b main
git add .
git commit -m "Add VLESS Reality health monitor"
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin main
```

`USERNAME` و `REPOSITORY` را با مشخصات مخزن خودتان جایگزین کنید. اگر مخزن را قبلاً ساخته‌اید، کلونش کنید و محتوای این پوشه را داخل آن کپی کنید.

### اجازهٔ commit به workflow

در مخزن GitHub بروید به:

**Settings → Actions → General → Workflow permissions**

گزینهٔ **Read and write permissions** را فعال کنید. Workflow از `GITHUB_TOKEN` خودکار GitHub استفاده می‌کند؛ لازم نیست Personal Access Token بسازید یا داخل فایل‌ها قرار دهید.

بعد از push، از **Actions → Check VLESS Reality nodes → Run workflow** اجرای اول را دستی شروع کنید. بعد از اولین اجرای موفق، فایل‌های `dist/` ساخته می‌شوند. اجرای زمان‌بندی‌شده با cron برابر `0 */6 * * *` است (نیمه‌شب، ۶، ۱۲ و ۱۸ UTC) و GitHub ممکن است چند دقیقه تأخیر داشته باشد.

## نشانی ساب

اگر می‌خواهید کلاینت بدون توکن به subscription URL دسترسی داشته باشد، مخزن باید **public** باشد؛ در این صورت لینک‌ها و شناسه‌های عمومی VPN هم برای همه قابل‌مشاهده و قابل‌کپی می‌شوند. اگر مخزن **public** باشد و branch اصلی `main` نام داشته باشد، پس از ساخته‌شدن خروجی می‌توانید در کلاینت از این نشانی استفاده کنید:

```text
https://raw.githubusercontent.com/USERNAME/REPOSITORY/main/dist/active.base64.txt
```

برای نشانی بالا `USERNAME` و `REPOSITORY` را عوض کنید. فایل خام هم از مسیر `dist/active.txt` در دسترس است. مخزن private معمولاً برای اپ‌های کلاینت بدون احراز هویت قابل‌خواندن نیست.

## نگهداری و امنیت

- فهرست نودها عمومی و متعلق به اشخاص ثالث است؛ آن را امن/بی‌لاگ فرض نکنید و برای داده‌های حساس استفاده نکنید.
- فایل `state/probe-state.json` فقط شمارندهٔ خطای هر لینک را با SHA-256 نگه می‌دارد، نه خود لینک را.
- نسخهٔ Xray در workflow روی `v26.3.27` pin شده و ZIP آن با SHA-256 پیش از اجرا بررسی می‌شود. برای ارتقا، نسخه و checksum را با مقادیر asset رسمی XTLS/Xray-core عوض کنید.
- منبع اولیه از snapshot عمومی [xray-config-toolkit](https://raw.githubusercontent.com/wuqb2i4f/xray-config-toolkit/main/output/base64/mix-security-re) تکمیل شده بود؛ این پروژه منبع رسمی IPSpeed نیست.

## اعتبارسنجی محلی بدون اتصال به سرورها

پس از نصب Xray می‌توانید فقط ساختار کانفیگ‌ها را تست کنید؛ این دستور به نودها وصل نمی‌شود:

```bash
python3 scripts/check_configs.py --xray /path/to/xray --validate-only
```
