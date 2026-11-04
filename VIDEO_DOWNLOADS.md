# إصلاح تنزيل الفيديو

اختيار الفيديو أصبح حسب المؤشر أو موضع التركيز أثناء التمرير، سواء كان الفيديو يعمل أو متوقفًا. عند وجود عدة فيديوهات، الإشارة لأحدها تختاره، والتمرير إلى غيره ينقل العلامة فوقه. إذا لم يكن المؤشر فوق مشغّل، يُفضّل الفيديو الأقرب لمركز الجزء الظاهر من الصفحة. لا يبدأ التنزيل إلا بالضغط على الزر.

قائمة الجودة والمصدر والمدة تتبع الفيديو المحدد معًا. الخيارات القديمة تتوقف عن العمل إذا تغيّر الفيديو. الروابط العامة أو المتعارضة لا تُستخدم لتخمين مقطع آخر؛ عند تعذّر تحديد المصدر بدقة، افتح منشور الفيديو نفسه. هذه التغييرات فُحصت باختبارات تفاعل محلية، ولم تُختبر داخل جلسة المستخدم في المتصفح.

أُصلح انتقال وضع الفحص بدون واجهة من الناشر إلى البرنامج المثبت. الناشر يفحص الآن جاهزية الواجهة وظهورها على ويندوز قبل إكمال النشر. شريط التحميل ثابت حتى إغلاقه، وله مقبض سحب مستقل؛ الإغلاق يمنع عودته مع أحداث المشغّل في الصفحة نفسها.

فُحصت محاولتا تليجرام في سجل التحميلات. الملف المحفوظ كان فيديو مدته ثلاث ثوانٍ، ومع ذلك صُنّف كتحميل مكتمل. رابط المشغّل كان مرتبطًا بجلسة تليجرام داخل المتصفح، ويمكن للاستخراج العام أن يلتقط رسوم الموقع بدل الفيديو المطلوب.

الإصدار الجديد يفحص مدة الفيديو ومساراته قبل إعلان اكتماله، ويرفض أجزاء البث المنفردة. تنزيل فيديو تليجرام يتم عبر جلسة المتصفح؛ افتح الفيديو وشغّله، ثم اضغط زر التنزيل فوقه واترك التبويب مفتوحًا حتى النهاية.

بعد تحديث البرنامج، أعد تحميل الإضافة من صفحة إضافات المتصفح، ثم أعد تحميل صفحة الفيديو. لا يمكن ضمان تنزيل كل فيديو من كل موقع؛ المحتوى المحمي، والبث المباشر، والروابط المنتهية، وصلاحيات الحساب تختلف حسب المصدر.

الملفات المرتبطة بجلسة المتصفح تحتاج بدء المحاولة مجددًا من المشغّل بعد الإيقاف أو إغلاق التبويب. لا يُدعم تحويل الصوت منفردًا عبر هذا المسار حاليًا.

فُحصت النسخة باختبارات تنزيل محلية فعلية وفحوص سلامة الملفات. لم تكتمل تجربة الفيديو الخاص داخل حساب تليجرام، لأن المستخدم أوقف التحكم في المتصفح.

اقتراحات التطوير التالية:

- استكمال تنزيلات المتصفح بعد إعادة فتح التبويب وربطها برسالة الفيديو الأصلية.
- تحديث مستخرجات المواقع منفصلًا عن تحديث التطبيق.
- زر تشخيص يجمع سبب الفشل وحالة الأدوات، مع إزالة بيانات الجلسة والروابط الحساسة.
- اختبار دوري للتنزيل على مواقع متنوعة، ومنع نشر إصدار يفشل في اختبارات السلامة.
- عرض مدة الفيديو المتوقعة والحجم والجودة قبل بدء التنزيل.

Technical details:

- Native application: Python 3.14 + PyQt6. Extractors: yt-dlp with FFmpeg/FFprobe and a JavaScript runtime.
- Browser extension: Chromium Manifest V3.
- Telegram: a MAIN-world reader accesses the page service worker; the isolated content script forwards bounded chunks through the extension worker to the authenticated loopback bridge.
- Range responses are checked for exact offsets, size consistency, and complete bodies. Browser transfer chunks are ordered and retry-safe. Final media is validated before publication, without overwriting existing files.
- Streaming downloads stop when a fragment is unavailable. Direct and extracted video paths both verify output before completion.
- Telegram transfers currently support progressive/stream routes exposed by an HTTP video source. Blob/MediaSource playback should use the site's own download flow.

Validation:

```powershell
py -3.14 -m unittest discover -s tests -p test_media_transfer.py -v
npm ci --prefix tests --ignore-scripts --no-audit --no-fund
node --test tests/browser-transfer.test.cjs
node --test tests/content-panel.test.cjs
```

Build and publish:

```powershell
.\build_installer.ps1
py -3.14 auto_publish.py
py -3.14 auto_publish.py --once --no-bump
```

The publisher validates the sources, builds the installer and matching update/extension archives, updates the local installation, and pushes to the configured repository. The single-run command uses the version already declared in the application and exits with a nonzero status if validation, build, or publication fails.

Primary references: [Telegram progressive service worker](https://github.com/Ajaxy/telegram-tt/blob/master/src/serviceWorker/progressive.ts), [Chrome webRequest](https://developer.chrome.com/docs/extensions/reference/api/webRequest), [yt-dlp](https://github.com/yt-dlp/yt-dlp).
