# AI Marketing Agency — dastlabki poydevor

Ushbu loyiha AMA arxitekturasining boshlang‘ich prototipidir. Unda Telegram Mini App `initData` tekshiruvi, qisqa muddatli sessiya, loyiha a’zoligi va brand profillari uchun API, Telegram webhook buyruqlari, Mini App oynasi hamda bazada saqlanadigan kontent va inson tasdig‘i mavjud.

**Hali tayyor emas:** AI bilan kampaniya yaratish, navbat/worker, media saqlash, kalendar, nashr, real xarajat cheklovlari va hisobotlar. Kontent qoralamalari va inson tasdiqlari bazada saqlanadi. Nashr qilish hali ulanmagan. Ma’lumotlar bazasi migratsiyalari va ishlab chiqarishga mo‘ljallangan qo‘shimcha xavfsizlik sozlamalari hali yo‘q.

## Mahalliy ishga tushirish

Python 3.12 bilan:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export OWNER_TELEGRAM_ID='<telegram-raqamli-user-id>'
export SESSION_SECRET='<kamida-32-belgili-tasodifiy-maxfiy-qiymat>'
# BOT_TOKEN muhitda mavjud bo‘lishi yoki TELEGRAM_BOT_TOKEN berilishi kerak.
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Standart ma’lumotlar bazasi lokal SQLite (`marketing.db`). Birinchi muvaffaqiyatli egaga tegishli Telegram Mini App autentifikatsiyasida Tamaddun, UC chi va UyTor loyihalari yaratiladi. `GET /health/ready` bazaga ulanishni tekshiradi, API hujjatlari `/docs` da. Telegram Mini App orqali yuborilgan `initData` autentifikatsiya qilinadi; oddiy Telegram ID login uchun yetarli emas.

Webhook uchun qo‘shimcha `TELEGRAM_WEBHOOK_PATH` va `TELEGRAM_WEBHOOK_SECRET` zarur. Telegramda webhook alohida ro‘yxatdan o‘tkazilishi va HTTPS manzil kerak; loyiha o‘zi webhook ro‘yxatdan o‘tkazmaydi. `/start`, `/projects`, `/help` faqat sozlangan egaga shaxsiy chatda javob beradi. Birinchi kirishdan oldin `/projects` bo‘sh bo‘lishi mumkin.

PostgreSQL uchun `DATABASE_URL` ni server tomonida o‘rnating. Mavjud Supabase URL va anon kalit PostgreSQL ulanish satrining o‘rnini bosmaydi. `SESSION_SECRET`, token va database sirlarini Gitga yoki chatga yozmang.

```sh
python -m pytest -q
```

## Keyingi ishlar

Doimiy DB migratsiyalari; AI provider va haqiqiy xarajat chegaralarini ulash; durable queue va rejalashtirish; keyin aniq versiyaga inson tasdig‘i va tasdiqlangan Telegram kanaliga nashr. Botga kanal huquqlari va batafsil loyiha brieflari kerak. Har loyiha uchun $30 oylik byudjet afzalligi saqlanadi, lekin hali xarajat cheklovi sifatida ishlamaydi. Hosting tanlanmasdan yoki zarur ulanishlar tasdiqlanmasdan production deploy bajarilmagan.
