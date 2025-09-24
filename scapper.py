import asyncio
import threading
from queue import Queue

from telebot import TeleBot
from playwright.async_api import async_playwright, Page

# === CONFIG ===
TELEGRAM_TOKEN = "7963750798:AAEIWqBSeivdxywA-Z--721SK5bvxZtA7Po"
TELEGRAM_CHAT_ID = 1966138199      # /start qilib aniqlang
PHONE_NUMBER = "931434413"        # login raqamingiz
DASHBOARD_URL = "https://dashboard.fonon.uz"
# =================

code_queue: "Queue[str]" = Queue()
tb = TeleBot(TELEGRAM_TOKEN, parse_mode=None)


# --- Telegram Bot ---
@tb.message_handler(commands=['start'])
def start(msg):
    tb.send_message(msg.chat.id, "Salom! SMS kodni shu botga yuboring.")

@tb.message_handler(func=lambda m: True)
def handle(msg):
    if msg.chat.id != TELEGRAM_CHAT_ID:
        tb.send_message(msg.chat.id, "Sizga ruxsat yo‘q.")
        return
    code = msg.text.strip()
    tb.send_message(msg.chat.id, f"Kod qabul qilindi: {code}")
    code_queue.put(code)

def telegram_thread():
    tb.infinity_polling()


def telegram_notify(text: str):
    try:
        tb.send_message(TELEGRAM_CHAT_ID, text)
    except Exception as e:
        print("Telegram error:", e)


# --- Login & Monitor ---
async def monitor_list(page: Page):
    """ul ichidagi yangi elementlarni kuzatib turadi va yangilarni Telegramga yuboradi"""
    seen_texts = set()
    while True:
        try:
            # Barcha itemlarni olish
            items = await page.query_selector_all("ul.MuiList-root.css-1uzmcsd li, div.MuiButtonBase-root.MuiListItemButton-root")
            for it in items:
                try:
                    text = await it.inner_text()
                    if text not in seen_texts:
                        seen_texts.add(text)
                        telegram_notify(f"📦 Yangi buyurtma:\n{text}")
                except:
                    continue
        except Exception as e:
            print("Listni o‘qishda xato:", e)

        await asyncio.sleep(5)  # har 5 soniyada tekshirish
async def login_and_monitor():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)  # serverda headless=True qiling
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto(DASHBOARD_URL)

    # Telefon raqam kiritish
    await page.fill('input[name="phone"]', PHONE_NUMBER)
    await page.click('button[type="submit"]')
    telegram_notify("📲 Kod yuborildi, botga kiriting.")

    # Kod kutish
    loop = asyncio.get_event_loop()
    code = await loop.run_in_executor(None, code_queue.get)
    await page.fill('input[name="otp"]', code)
    await page.click('button[type="submit"]')

    # Login + Drawer ochish
    try:
        # Toolbar ichidagi badge tugmani kutish
        await page.wait_for_selector(
            "div.MuiToolbar-root button.MuiIconButton-root:has(.MuiBadge-root)",
            timeout=20000
        )
        telegram_notify("✅ Login muvaffaqiyatli!")

        # Drawer tugmasini bosish
        await page.click("div.MuiToolbar-root button.MuiIconButton-root:has(.MuiBadge-root)")
        await asyncio.sleep(2)  # animatsiya tugashini kutish

        # Drawer ichidagi listni kutish
        await page.wait_for_selector("ul.MuiList-root.css-1uzmcsd", timeout=10000)
        telegram_notify("📂 Drawer ochildi, kuzatish boshlandi.")

    except Exception as e:
        telegram_notify(f"⚠️ Login yoki drawer ochishda xato: {e}")
        return

    # Listni kuzatish
    seen_texts = set()
    while True:
        try:
            # Drawer ichidagi barcha buyurtma matnlarini olish
            items = await page.query_selector_all("ul.MuiList-root.css-1uzmcsd div.MuiBox-root.css-dlleo3")
            for it in items:
                try:
                    text = await it.inner_text()
                    if text not in seen_texts:
                        seen_texts.add(text)
                        telegram_notify(f"📦 Yangi buyurtma:\n{text}")
                except:
                    continue
        except Exception as e:
            print("Listni o‘qishda xato:", e)

        await asyncio.sleep(5)  
        # har 5 soniyada tekshirish
def main():
    t = threading.Thread(target=telegram_thread, daemon=True)
    t.start()
    telegram_notify("Bot ishga tushdi.")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(login_and_monitor())


if __name__ == "__main__":
    main()
