# Scorpion Download Manager (`Scorpion IDM`) 🦂⚡

تطبيق سطح مكتب أصلي واحترافي لنظام Windows (`PyQt6` + بيئة `Python 3.14` الموقّعة رسمياً) لتسريع وتقسيم وإدارة التحميلات والفيديوهات وملفات التورنت على غرار **Internet Download Manager (IDM)**.

- 🌐 **الإضافة الرسمية على متجر Microsoft Edge:** [Scorpion IDM Integration Module — Microsoft Edge Add-ons](https://microsoftedge.microsoft.com/addons/detail/hgcdbjpjlfgnejhceobphikeebmhmgcj)
- 🔒 **سياسة الخصوصية:** [PRIVACY.md](https://github.com/Mahmoud-847/scorpion-idm/blob/main/PRIVACY.md)
- 🎬 **دليل تنزيل الفيديو وحدود الدعم:** [VIDEO_DOWNLOADS.md](VIDEO_DOWNLOADS.md)

---

## المميزات الأساسية
- **تقسيم الملفات والتحقق الصارم من السلامة:** تقسيم التحميل عبر `HTTP Range` مع التحقق الصارم من `Content-Range` و`Content-Length` وفحص تغيّر المورد عبر `ETag` / `Last-Modified` وتفعيل التحقق الكامل من شهادات TLS.
- **الإيقاف والاستكمال الآمن (Crash-Safe Pause & Resume):** حفظ تقدم كل جزء على القرص لحظياً مع حفظ الحالة ذرياً عبر نسخة احتياطية `.bak` وإمكانية تحديث الروابط المؤقتة المنتهية (*Refresh Download Address*).
- **التقاط الفيديوهات والصوتيات بضغطة واحدة:** شريط عائم أعلى مشغلات الفيديو لاختيار الجودة الفعلية المتاحة (`1080p` / `720p` / صوت `M4A`) مع فحص سلامة المسارات عبر `ffprobe` ودعم النقل المحلي الآمن من جلسة المتصفح (مثل فروع `Telegram Web`) ومصادقة الجسر المحلي برمز جلسة آمن.
- **دعم التورنت والروابط المغناطيسية (`BitTorrent` / `Magnet`):** معاينة شجرة الملفات واختيار الملفات المطلوبة قبل بدء التنزيل عبر محرك `aria2c` المدمج مع نقل مخرجات التورنت بشكل موثوق وإرجاع الحالة عند أي خطأ.
- **تكامل كامل مع Windows:** بطاقات تنزيل جانبية أنيقة (*Corner Toast Cards*)، مؤشر تقدم حي على أيقونة شريط المهام (*Taskbar Progress*)، ثيم داكن وفاتح، وواجهة ثنائية اللغة (العربية / الإنجليزية).
- **نموذج التوزيع والتحقق من السلامة:** يعمل التطبيق على مشغّل `Python Software Foundation (pythonw.exe)` الموقّع رقمياً دون تعديل، بينما تبقى ملفات السكربت `.py` ومثبّت `Inno Setup` بدون توقيع رقمي مستقل ويتم التحقق من حزم التحديث التلقائي ومصادرها عبر بصمات `SHA-256` في `release/update.json`.

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
ينتج البناء ملف التثبيت `release/Scorpion-Setup-<version>.exe` وحزمة التحديث `release/Scorpion-Update-Payload.zip` وملف `release/update.json` المتضمّن بصمات `SHA-256` لحزمة التحديث والمصادر المجمّعة.

### 4. النشر التلقائي إلى GitHub
```powershell
py -3.14 auto_publish.py
```
