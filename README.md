# ساب VLESS + Reality و پایش خودکار

این ریپو از فایل‌های موجود در ریشه استفاده می‌کند:

- `source.txt` — فهرست اولیهٔ ۸۴ لینک
- `check_configs.py` — اسکریپت بررسی
- `.github/workflows/health-check.yml` — GitHub Action زمان‌بندی‌شده

در هر اجرا، Xray لینک‌ها را از نظر ساختار و اتصال HTTPS از داخل پروکسی آزمایش می‌کند. حداکثر چهار نود هم‌زمان بررسی می‌شوند. نودی که قبلاً سالم بوده، پس از دو شکست پیاپی از خروجی فعال کنار گذاشته می‌شود؛ یک شکست گذرا کافی نیست. نود جدید تا وقتی تست واقعی را پاس نکند وارد ساب نمی‌شود.

خروجی‌های موفق در این مسیرها ساخته می‌شوند:

- `dist/active.txt` — لینک‌های خام
- `dist/active.base64.txt` — خروجی Base64

## مهم: منبع فهرست

این Action خود صفحهٔ IPSpeed را scrape نمی‌کند؛ صفحه لینک‌ها را کوتاه می‌کند و export/API قابل‌اتکایی پیدا نشد. برای افزودن کانفیگ کامل، آن را به `source.txt` اضافه و push کنید. نودهای فعلی از snapshot عمومی هم‌زمان گرفته شده‌اند و سلامتشان تا زمان اجرای Action تضمین نیست.

## فعال‌کردن

1. مطمئن شوید فایل workflow دقیقاً در مسیر `.github/workflows/health-check.yml` باشد؛ فایل `health-check.yml` در ریشه به‌تنهایی Action نیست.
2. Push کنید و در GitHub به **Settings → Actions → General → Workflow permissions** بروید؛ **Read and write permissions** را انتخاب و Save کنید.
3. در **Actions → Check VLESS Reality nodes → Run workflow** اجرای اول را دستی شروع کنید.
4. بعد از اجرای موفق، Action هر ۶ ساعت با زمان‌بندی `0 */6 * * *` (UTC) اجرا می‌شود. GitHub ممکن است چند دقیقه تأخیر داشته باشد.

در یک ریپوی Public، بعد از ساخته‌شدن فایل Base64، نشانی ساب این قالب است:

```text
https://raw.githubusercontent.com/USERNAME/REPOSITORY/main/dist/active.base64.txt
```

ریپوی Public باعث می‌شود کانفیگ‌ها و شناسه‌هایشان هم برای همه قابل‌دیدن باشند. سرورهای رایگان عمومی را برای داده‌های حساس استفاده نکنید.
