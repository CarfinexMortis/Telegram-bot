import json
import asyncio
from pathlib import Path
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = "8060994884:AAEjYeBOg8RiLZ66-W3uEemsVW60ACiJA2M"
USER_DATA_FILE = Path("users_data.json")
user_totals_lock = asyncio.Lock()

# ================== ДАТА ==================
def today():
    return date.today().isoformat()

# ================== ШАБЛОН ДНЯ ==================
DAY_TEMPLATE = {
    "total": {"cal": 0, "p": 0, "f": 0, "c": 0},
    "meals": {
        "z": {"cal": 0, "p": 0, "f": 0, "c": 0},
        "o": {"cal": 0, "p": 0, "f": 0, "c": 0},
        "u": {"cal": 0, "p": 0, "f": 0, "c": 0},
        "p": {"cal": 0, "p": 0, "f": 0, "c": 0},
    }
}

# ================== ЗАГРУЗКА ПРОДУКТОВ ==================
with open("products.json", "r", encoding="utf-8") as f:
    products_by_cat = json.load(f)

# ================== ДАННЫЕ ==================
def load_users():
    if not USER_DATA_FILE.exists():
        return {}
    try:
        return json.loads(USER_DATA_FILE.read_text(encoding="utf-8"))
    except:
        return {}

def save_users(data: dict):
    USER_DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8"
    )

user_data = load_users()

# ================== USER / DAY ==================
async def ensure_user_day(user_id: int):
    async with user_totals_lock:
        uid = str(user_id)
        d = today()

        user_data.setdefault(uid, {})
        user_data[uid].setdefault(d, json.loads(json.dumps(DAY_TEMPLATE)))

        save_users(user_data)

async def add_user_food(user_id: int, meal: str, delta: dict):
    async with user_totals_lock:
        uid = str(user_id)
        d = today()
        day = user_data[uid][d]

        for k in delta:
            day["total"][k] += delta[k]
            day["meals"][meal][k] += delta[k]

        save_users(user_data)

async def get_user_day(user_id: int, d: str | None = None):
    async with user_totals_lock:
        uid = str(user_id)
        return user_data.get(uid, {}).get(d or today())

# ================== УТИЛИТЫ ==================
def reset_state(context):
    context.user_data.clear()

def parse_grams(text: str) -> float:
    t = text.lower().replace(" ", "").replace(",", ".")
    if t.endswith("кг"):
        return float(t[:-2]) * 1000
    if t.endswith("г"):
        return float(t[:-1])
    return float(t)

async def show_main_menu(target):
    keyboard = [
        [InlineKeyboardButton(cat.title(), callback_data=f"cat|{cat}")]
        for cat in products_by_cat
    ]
    keyboard += [
        [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton("📊 Итог за день", callback_data="day")],
        [InlineKeyboardButton("📅 История", callback_data="history")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if hasattr(target, "message"):
        await target.message.reply_text("Главное меню:", reply_markup=markup)
    else:
        await target.edit_message_text("Главное меню:", reply_markup=markup)

# ================== START ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user_day(update.effective_user.id)
    reset_state(context)
    await show_main_menu(update)

# ================== КАТЕГОРИЯ ==================
async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    cat = q.data.split("|")[1]
    context.user_data["category"] = cat

    keyboard = [[InlineKeyboardButton(p, callback_data=f"prod|{p}")]
                for p in products_by_cat[cat]]
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back")])

    await q.edit_message_text(
        f"Категория: {cat}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================== ПРОДУКТ ==================
async def product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    product = q.data.split("|")[1]
    context.user_data["product"] = product

    for cat, items in products_by_cat.items():
        if product in items:
            context.user_data["category"] = cat
            break

    await q.edit_message_text(f"{product}\nВведите массу (г или кг):")

# ================== ПОИСК ==================
async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["search"] = True
    await q.edit_message_text("Введите название продукта:")

# ================== НАЗАД ==================
async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    reset_state(context)
    await show_main_menu(q)

# ================== ПРИЁМ ПИЩИ ==================
async def meal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    meal = q.data.split("|")[1]
    grams = context.user_data["grams"]
    product = context.user_data["product"]
    cat = context.user_data["category"]

    data = products_by_cat[cat][product]

    delta = {
        "cal": data["calories"] * grams / 100,
        "p": data["protein"] * grams / 100,
        "f": data["fat"] * grams / 100,
        "c": data["carbs"] * grams / 100
    }

    await add_user_food(q.from_user.id, meal, delta)

    await q.edit_message_text(
        f"✅ Добавлено:\n{product} — {grams} г\n"
        f"{delta['cal']:.1f} ккал\n"
        f"БЖУ {delta['p']:.1f}/{delta['f']:.1f}/{delta['c']:.1f}"
    )

    reset_state(context)
    await show_main_menu(q)

# ================== ИТОГ ЗА ДЕНЬ ==================
async def day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    day = await get_user_day(q.from_user.id)
    if not day:
        await q.edit_message_text("❌ За сегодня данных нет.")
        await show_main_menu(q)
        return

    meals = {"z": "🍳 Завтрак", "o": "🍲 Обед", "u": "🌙 Ужин", "p": "🍎 Перекус"}

    text = (
        f"📊 Итог за {today()}:\n\n"
        f"🔥 {day['total']['cal']:.1f} ккал\n"
        f"БЖУ {day['total']['p']:.1f}/"
        f"{day['total']['f']:.1f}/"
        f"{day['total']['c']:.1f}\n\n"
    )

    for k, name in meals.items():
        m = day["meals"][k]
        if m["cal"] > 0:
            text += f"{name}: {m['cal']:.1f} ккал\n"

    await q.edit_message_text(text)
    await show_main_menu(q)

# ================== ИСТОРИЯ ==================
async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = str(q.from_user.id)
    days = user_data.get(uid, {})

    if not days:
        await q.edit_message_text("История пуста.")
        await show_main_menu(q)
        return

    keyboard = [[InlineKeyboardButton(d, callback_data=f"hist|{d}")]
                for d in sorted(days.keys(), reverse=True)[:14]]
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back")])

    await q.edit_message_text(
        "Выберите дату:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def history_day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    d = q.data.split("|")[1]
    day = await get_user_day(q.from_user.id, d)

    meals = {"z": "🍳 Завтрак", "o": "🍲 Обед", "u": "🌙 Ужин", "p": "🍎 Перекус"}

    text = f"📅 {d}\n\n🔥 {day['total']['cal']:.1f} ккал\n\n"
    for k, name in meals.items():
        m = day["meals"][k]
        if m["cal"] > 0:
            text += f"{name}: {m['cal']:.1f} ккал\n"

    await q.edit_message_text(text)

# ================== ТЕКСТ ==================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if context.user_data.get("search"):
        context.user_data["search"] = False
        matches = [p for items in products_by_cat.values() for p in items if text.lower() in p.lower()]
        if not matches:
            await update.message.reply_text("❌ Не найдено.")
            await show_main_menu(update)
            return

        keyboard = [[InlineKeyboardButton(p, callback_data=f"prod|{p}")] for p in matches]
        keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back")])
        await update.message.reply_text("Найдено:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if "product" in context.user_data:
        try:
            grams = parse_grams(text)
            if grams <= 0:
                raise ValueError
        except:
            await update.message.reply_text("❌ Пример: 150 или 0.2кг")
            return

        context.user_data["grams"] = grams
        keyboard = [
            [InlineKeyboardButton("Завтрак", callback_data="meal|z")],
            [InlineKeyboardButton("Обед", callback_data="meal|o")],
            [InlineKeyboardButton("Ужин", callback_data="meal|u")],
            [InlineKeyboardButton("Перекус", callback_data="meal|p")]
        ]
        await update.message.reply_text("Приём пищи:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    await show_main_menu(update)

# ================== ЗАПУСК ==================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(category_handler, pattern="^cat\\|"))
app.add_handler(CallbackQueryHandler(product_handler, pattern="^prod\\|"))
app.add_handler(CallbackQueryHandler(search_handler, pattern="^search$"))
app.add_handler(CallbackQueryHandler(back_handler, pattern="^back$"))
app.add_handler(CallbackQueryHandler(day_handler, pattern="^day$"))
app.add_handler(CallbackQueryHandler(history_handler, pattern="^history$"))
app.add_handler(CallbackQueryHandler(history_day_handler, pattern="^hist\\|"))
app.add_handler(CallbackQueryHandler(meal_handler, pattern="^meal\\|"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

print("✅ Бот запущен")
app.run_polling()
