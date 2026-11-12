# Scorpion Download Manager (`Scorpion IDM`) 🦂⚡

تطبيق سطح مكتب أصلي واحترافي لنظام Windows (`PyQt6` + بيئة `Python 3.14` الموقّعة رسمياً) لتسريع وتقسيم وإدارة التحميلات والفيديوهات وملفات التورنت على غرار **Internet Download Manager (IDM)**.

- 🌐 **الإضافة الرسمية على متجر Microsoft Edge:** [Scorpion IDM Integration Module — Microsoft Edge Add-ons](https://microsoftedge.microsoft.com/addons/detail/hgcdbjpjlfgnejhceobphikeebmhmgcj)
- 🔒 **سياسة الخصوصية:** [PRIVACY.md](https://github.com/Mahmoud-847/scorpion-idm/blob/main/PRIVACY.md)
- 🎬 **دليل تنزيل الفيديو وحدود الدعم:** [VIDEO_DOWNLOADS.md](VIDEO_DOWNLOADS.md)

---

## المميزات الأساسية
- **تقسيم الملفات الديناميكي (Dynamic File Segmentation):** تقسيم التحميل حتى 32 قناة متوازية عبر `HTTP Range` مع سرقة العمل الديناميكية (*Dynamic Work Stealing*) لتعظيم السرعة حتى آخر بايت.
- **الإيقاف والاستكمال الآمن (Crash-Safe Pause & Resume):** حفظ تقدم كل جزء على القرص لحظياً مع إمكانية تحديث الروابط المؤقتة المنتهية (*Refresh Download Address*).
- **التقاط الفيديوهات والصوتيات بضغطة واحدة:** شريط عائم أعلى مشغلات الفيديو لاختيار الجودة الفعلية المتاحة (`1080p` / `720p` / صوت `M4A`) مع فحص سلامة المسارات عبر `ffprobe` ودعم النقل المحلي الآمن من جلسة المتصفح (مثل فروع `Telegram Web`).
- **دعم التورنت والروابط المغناطيسية (`BitTorrent` / `Magnet`):** معاينة شجرة الملفات واختيار الملفات المطلوبة قبل بدء التنزيل عبر محرك `aria2c` المدمج.
- **تكامل كامل مع Windows:** بطاقات تنزيل جانبية أنيقة (*Corner Toast Cards*)، مؤشر تقدم حي على أيقونة شريط المهام (*Taskbar Progress*)، ثيم داكن وفاتح، وواجهة ثنائية اللغة (العربية / الإنجليزية).
- **توزيع موثوق وتحديث تلقائي آمن:** حزمة تثبيت `Inno Setup 6` مبنية على مشغّل `Python Software Foundation` الموقّع رقمياً دون إنذارات كاذبة من برامج الحماية، مع نظام تحديث مباشر يتحقق من بصمة `SHA-256`.

---

## ربط المتصفح (Browser Integration)
- **Microsoft Edge (تثبيت رسمي بضغطة واحدة):** متاحة مباشرةً على المتجر الرسمي عبر الرابط:
  https://microsoftedge.microsoft.com/addons/detail/hgcdbjpjlfgnejhceobphikeebmhmgcj
  *(تنبيه: إذا كانت لديك نسخة يدوية قديمة مثبتة عبر `Load unpacked` في `edge://extensions`، احذفها أولاً لعدم تكرار الإضافة).*
- **Google Chrome & Brave:** افتح **«ربط المتصفح»** من داخل البرنامج؛ سيقوم المعالج بتجهيز المسار الدائم ونسخه تلقائياً مع شرح مصوّر من 3 خطوات واكتشاف فوري للتفعيل.

---

## التشغيل والاختبار والبناء (للمطورين)

### 1. تشغيل التطبيق مباشرة من المصدر
```powershell
py -3.14 native_app/scorpion_qt.py
```

### 2. تشغيل الاختبارات الآلية (Python + إضافة المتصفح)
```powershell
py -3.14 -m unittest discover -s tests -p "test_*.py" -v
node --test tests/browser-transfer.test.cjs tests/content-panel.test.cjs tests/popup.test.cjs
```

### 3. بناء ملف التثبيت الرسمي وحزمة التحديث
```powershell
.\fetch_tools.ps1
.\build_installer.ps1
```
ينتج البناء ملف التثبيت `release/Scorpion-Setup-<version>.exe` وحزمة التحديث `release/Scorpion-Update-Payload.zip` وملف `release/update.json` الموقّع ببصمة `SHA-256`.

### 4. النشر التلقائي إلى GitHub
```powershell
py -3.14 auto_publish.py
```
