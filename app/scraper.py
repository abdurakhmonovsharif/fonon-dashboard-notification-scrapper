import asyncio
import json
import os
import sys
from queue import Queue
import threading
import requests
from telebot import TeleBot
from playwright.async_api import async_playwright
import time

# === CONFIG ===
TELEGRAM_TOKEN = "7963750798:AAEn_A95gPEO-xubb-TYgSRIslx_cLFI5cM"
TELEGRAM_CHAT_ID = 1966138199  # /start orqali aniqlang
PHONE_NUMBER = "931434413"
DASHBOARD_URL = "https://dashboard.fonon.uz"
STATE_FILE = "state.json"
API_URL = "https://api.fonon.uz/api/v1/orders/all?page=0&size=10"
# ==============

code_queue: "Queue[str]" = Queue()
tb = TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")

# --- Helpers ---
def format_phone(phone: str) -> str:
    digits = "".join(filter(str.isdigit, phone))
    if digits.startswith("998") and len(digits) == 12:
        return f"{digits[3:5]} {digits[5:8]}-{digits[8:10]}-{digits[10:12]}"
    elif len(digits) == 9:
        return f"{digits[0:2]} {digits[2:5]}-{digits[5:7]}-{digits[7:9]}"
    return phone

def format_number(num: int, style: str = "comma") -> str:
    if style == "comma":
        return "{:,}".format(num)
    elif style == "space":
        return "{:,.0f}".format(num).replace(",", " ")
    elif style == "mln":
        return f"{num / 1_000_000:.1f} mln"
    else:
        raise ValueError("Noto‘g‘ri style! Faqat: 'comma', 'space', 'mln'")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# --- Telegram handlers ---
@tb.message_handler(commands=['start'])
def start(msg):
    tb.send_message(msg.chat.id, "Salom! SMS kodni shu botga yuboring.")

@tb.message_handler(commands=['change_order'])
def change_order(msg):
    if msg.chat.id != TELEGRAM_CHAT_ID:
        tb.send_message(msg.chat.id, "❌ Sizga ruxsat yo‘q.")
        return
    
    parts = msg.text.strip().split()
    if len(parts) < 2:
        tb.send_message(msg.chat.id, "ℹ️ Foydalanish: /change_order <order_id>")
        return
    
    try:
        new_id = int(parts[1])
        state = load_state()
        state["last_order_id"] = new_id
        save_state(state)
        tb.send_message(msg.chat.id, f"✅ last_order_id {new_id} ga o‘zgartirildi.")
    except ValueError:
        tb.send_message(msg.chat.id, "❌ Order ID son bo‘lishi kerak.")

@tb.message_handler(commands=['restart'])
def restart_bot(msg):
    if msg.chat.id != TELEGRAM_CHAT_ID:
        tb.send_message(msg.chat.id, "❌ Sizga ruxsat yo‘q.")
        return
    tb.send_message(msg.chat.id, "🔄 Bot qayta ishga tushmoqda...")
    os.execv(sys.executable, ['python'] + sys.argv)

@tb.message_handler(func=lambda m: True)
def handle(msg):
    if msg.chat.id != TELEGRAM_CHAT_ID:
        tb.send_message(msg.chat.id, "❌ Sizga ruxsat yo‘q.")
        return
    code = msg.text.strip()
    code_queue.put(code)
    tb.send_message(msg.chat.id, f"✅ Kod qabul qilindi: {code}")

def telegram_thread():
    while True:
        try:
            tb.infinity_polling(timeout=30, long_polling_timeout=10, restart_on_change=True)
        except Exception as e:
            print("⚠️ Telegram polling xato berdi, 5s dan keyin qayta urinish:", e)
            time.sleep(5)

def telegram_notify(text: str):
    for attempt in range(3):
        try:
            tb.send_message(TELEGRAM_CHAT_ID, text)
            return
        except Exception as e:
            print(f"Telegram xato (urinish {attempt+1}/3):", e)
            time.sleep(2)
    print("❌ Telegramga yuborilmadi (3 urinishdan keyin).")

# --- Login va token olish ---
async def playwright_login():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(ignore_https_errors=True)
    page = await context.new_page()

    await page.goto(DASHBOARD_URL)
    await page.fill('input[name="phone"]', PHONE_NUMBER)
    await page.click('button[type="submit"]')
    telegram_notify("📲 Kod yuborildi, botga kiriting.")

    loop = asyncio.get_event_loop()
    code = await loop.run_in_executor(None, code_queue.get)
    await page.fill('input[name="otp"]', code)
    await page.click('button[type="submit"]')

    await page.wait_for_selector("div.MuiToolbar-root", timeout=30000)

    access_token = await page.evaluate("() => localStorage.getItem('accessToken')")
    refresh_token = await page.evaluate("() => localStorage.getItem('refreshToken')")

    if not access_token:
        raise Exception("❌ accessToken topilmadi!")

    telegram_notify("✅ Login muvaffaqiyatli, token olindi.")
    await browser.close()
    return {"token": access_token, "refresh": refresh_token}

def is_token_valid(token: str) -> bool:
    try:
        resp = requests.get(API_URL, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return resp.status_code != 401
    except Exception as e:
        print("Token tekshirishda xato:", e)
        return False

# --- Order ishlovchi ---
async def handle_order(order, token):
    order_id = order.get("id", "???")
    total_price = order.get("totalPrice", "Noma’lum")
    delivery_type = order.get("deliveryType", "Noma’lum")
    phone = order.get("owner", {}).get("phoneNumber", "❌ Noma’lum")
    items = order.get("orderItems", [])

    url = f"https://dashboard.fonon.uz/dashboard/order/{order_id}"

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(
        ignore_https_errors=True,
        storage_state={"origins": [{
            "origin": "https://dashboard.fonon.uz",
            "localStorage": [
                {"name": "accessToken", "value": token}
            ]
        }]}
    )
    page = await context.new_page()
    await page.set_viewport_size({"width": 1300, "height": 800})
    await page.goto(url)
    await asyncio.sleep(5)

    await page.evaluate("document.body.style.zoom='80%'")
    await asyncio.sleep(1)

    screenshot_path = f"order_{order_id}.png"
    await page.screenshot(path=screenshot_path, full_page=False)

    caption = (
        f"📦 Buyurtma #{order_id}\n\n"
        f"💰 Narxi: {format_number(total_price,'comma')} so'm\n"
        f"🚚 Yetkazib berish: {delivery_type}\n"
        f"👤 Telefon: {format_phone(phone)}\n\n"
        f"📋 Mahsulotlar:\n"
    )

    for idx, item in enumerate(items, start=1):
        product = item.get("productItem", {}).get("product", {})
        product_name = product.get("nameUz", "Mahsulot")
        product_artikul = product.get("artikul", "Artikulsiz")
        product_seria = item.get("productItem", {}).get("serialNumber", "❌")

        caption += (
            f"\n🔹 {idx}. {product_name}\n"
            f"   🆔 Artikuli: {product_artikul}\n"
            f"   🏷️ Seriya: {product_seria}\n"
        )

    try:
        with open(screenshot_path, "rb") as img:
            tb.send_photo(TELEGRAM_CHAT_ID, img, caption=caption)
    finally:
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)

    await browser.close()

# --- Monitor ---
async def monitor():
    state = load_state()

    while True:
        if not state.get("token") or not is_token_valid(state["token"]):
            tokens = await playwright_login()
            state["token"] = tokens["token"]
            state["refreshToken"] = tokens["refresh"]
            save_state(state)

        try:
            headers = {"Authorization": f"Bearer {state['token']}"}
            resp = requests.get(API_URL, headers=headers, timeout=15)
        except Exception as e:
            print("API so‘rovda xato:", e)
            await asyncio.sleep(10)
            continue

        if resp.status_code == 401:
            tokens = await playwright_login()
            state["token"] = tokens["token"]
            state["refreshToken"] = tokens["refresh"]
            save_state(state)
            continue

        data = resp.json()
        orders = data.get("content", [])

        if orders:
            latest_id = orders[0]["id"]
            last_id = state.get("last_order_id", 0)

            new_orders = [o for o in orders if o["id"] > last_id]
            for order in reversed(new_orders):
                await handle_order(order, state["token"])

            if latest_id > last_id:
                state["last_order_id"] = latest_id
                save_state(state)

        await asyncio.sleep(60)

# --- Main ---
def main():
    t = threading.Thread(target=telegram_thread, daemon=True)
    t.start()
    telegram_notify("🤖 Bot ishga tushdi.")
    asyncio.run(monitor())

if __name__ == "__main__":
    main()
