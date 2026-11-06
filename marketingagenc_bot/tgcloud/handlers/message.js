// handlers/message.js — Telegram serverless message handler (AMA v1.0)
import { api } from 'sdk';

const MINI_APP_URL = 'https://marketing-agency-five-gamma.vercel.app/';

export default async function (message, ctx) {
  const text = (message.text || '').trim();
  const chatId = message.chat.id;

  const command = text.split(/\s+/)[0].split('@')[0].toLowerCase();

  const miniAppKeyboard = {
    inline_keyboard: [
      [
        {
          text: "🚀 Mini Appni ochish (Dashboard)",
          web_app: { url: MINI_APP_URL },
        },
      ],
    ],
  };

  if (command === '/start') {
    await api.sendMessage({
      chat_id: chatId,
      text: "Assalomu alaykum! AI Marketing Agency (AMA v1.0) boshqaruv botiga xush kelibsiz.\n\n" +
            "Ushbu bot orqali O‘qi, Yordamchi AI va Tamaddun loyihalari bo‘yicha AI agentlar jamoasini boshqarishingiz mumkin.\n\n" +
            "Quyidagi tugma orqali to‘liq ish stoli (Mini App)ni oching:\n\n" +
            "Komandalar:\n" +
            "/projects — Loyihalar ro‘yxati\n" +
            "/new_campaign — Yangi kampaniya boshlash\n" +
            "/approvals — Tasdiqlashlar\n" +
            "/help — Yordam",
      reply_markup: miniAppKeyboard,
    });
  } else if (command === '/projects') {
    await api.sendMessage({
      chat_id: chatId,
      text: "📁 Loyihalaringiz (AMA v1.0):\n\n" +
            "1. 📚 O‘qi — Ta'lim platformasi va onlayn kurslar\n" +
            "2. 🤖 Yordamchi AI — Bizneslar uchun sun'iy intellekt xizmati\n" +
            "3. 📝 Tamaddun — Talabalar uchun ilmiy maqola xizmati\n\n" +
            "Har bir loyihaning brifi, postlari va kampaniyalari alohida boshqariladi.",
      reply_markup: miniAppKeyboard,
    });
  } else if (command === '/new_campaign') {
    await api.sendMessage({
      chat_id: chatId,
      text: "🎯 Yangi kampaniya rejalashtirish:\n\n" +
            "Mini App'ga kiring, loyihani tanlang va 'AI Jamoaga topshiriq' bo‘limida maqsadingizni yozing. " +
            "Orchestrator, Kopirayter va QA Reviewer darhol 3 ta post va strategiyani tayyorlab beradi.",
      reply_markup: miniAppKeyboard,
    });
  } else if (command === '/approvals') {
    await api.sendMessage({
      chat_id: chatId,
      text: "✅ Tasdiqlashlar (Human-in-the-loop):\n\n" +
            "AI yaratgan barcha postlar inson tasdig‘idan o‘tishi shart. " +
            "Kutilayotgan postlarni ko‘rish va tasdiqlash uchun Mini App'ni oching.",
      reply_markup: miniAppKeyboard,
    });
  } else if (command === '/help') {
    await api.sendMessage({
      chat_id: chatId,
      text: "ℹ️ AMA v1.0 Bot yo‘riqnomasi:\n\n" +
            "/start — Botni ishga tushirish\n" +
            "/projects — 3 ta asosiy loyihani ko‘rish\n" +
            "/new_campaign — AI bilan yangi marketing kampaniyasi\n" +
            "/approvals — Kutayotgan tasdiqlashlar\n" +
            "/help — Ushbu yordam xabari\n\n" +
            "Ish stoli: Telegram Mini App orqali barcha loyihalarni qulay boshqaring.",
      reply_markup: miniAppKeyboard,
    });
  } else {
    await api.sendMessage({
      chat_id: chatId,
      text: "Noma’lum buyruq. Barcha buyruqlar ro‘yxati uchun /help ni yuboring.",
      reply_markup: miniAppKeyboard,
    });
  }
}
