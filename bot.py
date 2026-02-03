import json
import asyncio
from pathlib import Path
from typing import Optional
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
MEAL_LABELS = {
    "z": "Завтрак",
    "o": "Обед",
    "u": "Ужин",
    "p": "Перекус",
}

def build_totals_default():
    return {
        "cal": 0,
        "p": 0,
        "f": 0,
        "c": 0,
        "meals": {meal_key: {"cal": 0, "p": 0, "f": 0, "c": 0} for meal_key in MEAL_LABELS},
    }

USER_TOTALS_DEFAULT = build_totals_default()
user_totals_lock = asyncio.Lock()

# ================== ЗАГРУЗКА БАЗЫ ==================
with open("products.json", "r", encoding="utf-8") as f:
    products_by_cat = json.load(f)

def load_user_totals():
    if not USER_DATA_FILE.exists():
        return {}
    try:
        with USER_DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    totals = {}
    for user_id, stats in data.items():
        meals_data = stats.get("meals", {})
        totals[user_id] = build_totals_default()
        totals[user_id]["cal"] = float(stats.get("cal", stats.get("calories", 0)))
        totals[user_id]["p"] = float(stats.get("p", stats.get("protein", 0)))
        totals[user_id]["f"] = float(stats.get("f", stats.get("fat", 0)))
        totals[user_id]["c"] = float(stats.get("c", stats.get("carbs", 0)))
        for meal_key in MEAL_LABELS:
            meal_stats = meals_data.get(meal_key, {})
            totals[user_id]["meals"][meal_key] = {
                "cal": float(meal_stats.get("cal", 0)),
                "p": float(meal_stats.get("p", 0)),
                "f": float(meal_stats.get("f", 0)),
                "c": float(meal_stats.get("c", 0)),
            }
    return totals

def save_user_totals(totals: dict):
    data = {
        str(user_id): {
            "cal": stats["cal"],
            "p": stats["p"],
            "f": stats["f"],
            "c": stats["c"],
            "meals": stats["meals"],
        }
        for user_id, stats in totals.items()
    }
    USER_DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")

user_totals = load_user_totals()

async def ensure_user_totals(user_id: int):
    async with user_totals_lock:
        key = str(user_id)
        if key not in user_totals:
            user_totals[key] = build_totals_default()
            save_user_totals(user_totals)

async def get_user_totals(user_id: int) -> dict:
    async with user_totals_lock:
        return user_totals.get(str(user_id), build_totals_default()).copy()

async def add_user_totals(user_id: int, delta: dict, meal_key: Optional[str] = None):
    async with user_totals_lock:
        key = str(user_id)
        current = user_totals.setdefault(key, build_totals_default())
        current["cal"] += delta.get("cal", 0)
        current["p"] += delta.get("p", 0)
        current["f"] += delta.get("f", 0)
        current["c"] += delta.get("c", 0)
        if meal_key in MEAL_LABELS:
            meal_stats = current["meals"].setdefault(meal_key, {"cal": 0, "p": 0, "f": 0, "c": 0})
            meal_stats["cal"] += delta.get("cal", 0)
            meal_stats["p"] += delta.get("p", 0)
            meal_stats["f"] += delta.get("f", 0)
            meal_stats["c"] += delta.get("c", 0)
        save_user_totals(user_totals)

# ================== УТИЛИТЫ ==================
def reset_state(context):
    context.user_data.pop("category", None)
    context.user_data.pop("product", None)
    context.user_data.pop("grams", None)
    context.user_data.pop("search", None)

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
    keyboard.append([InlineKeyboardButton("🔍 Поиск продукта", callback_data="search")])
    keyboard.append([InlineKeyboardButton("📊 Итог за день", callback_data="day")])

    markup = InlineKeyboardMarkup(keyboard)

    if hasattr(target, "message"):
        await target.message.reply_text("Главное меню:", reply_markup=markup)
    else:
        await target.edit_message_text("Главное меню:", reply_markup=markup)

# ================== /start ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user_totals(update.effective_user.id)
    reset_state(context)
    await show_main_menu(update)

# ================== КАТЕГОРИЯ ==================
async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    cat = q.data.split("|")[1]
    context.user_data["category"] = cat

    keyboard = [
        [InlineKeyboardButton(p, callback_data=f"prod|{p}")]
        for p in products_by_cat[cat]
    ]
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back")])

    await q.edit_message_text(
        f"Категория: {cat}\nВыберите продукт:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================== ПРОДУКТ ==================
async def product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    product = q.data.split("|")[1]
    context.user_data["product"] = product

    if "category" not in context.user_data:
        for cat, items in products_by_cat.items():
            if product in items:
                context.user_data["category"] = cat
                break

    await q.edit_message_text(
        f"Продукт: {product}\nВведите массу (г или кг):"
    )

# ================== ПОИСК ==================
async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["search"] = True
    await q.edit_message_text("Введите название продукта для поиска:")

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

    grams = context.user_data["grams"]
    product = context.user_data["product"]
    cat = context.user_data["category"]
    user_id = q.from_user.id
    meal_key = q.data.split("|")[1]

    data = products_by_cat[cat][product]

    cal = data["calories"] * grams / 100
    p = data["protein"] * grams / 100
    f = data["fat"] * grams / 100
    c = data["carbs"] * grams / 100

    await add_user_totals(user_id, {"cal": cal, "p": p, "f": f, "c": c}, meal_key)

    await q.edit_message_text(
        f"✅ Добавлено:\n"
        f"{product} — {grams} г\n\n"
        f"Ккал: {cal:.1f}\n"
        f"БЖУ: {p:.1f}/{f:.1f}/{c:.1f}"
    )

    reset_state(context)
    await show_main_menu(q)

# ================== ИТОГ ЗА ДЕНЬ ==================
async def day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    day = await get_user_totals(q.from_user.id)

    if not day or day["cal"] == 0:
        await q.edit_message_text("❌ За сегодня ещё ничего не добавлено.")
        await show_main_menu(q)
        return

    meals_lines = []
    for meal_key, label in MEAL_LABELS.items():
        meal = day.get("meals", {}).get(meal_key, {"cal": 0, "p": 0, "f": 0, "c": 0})
        meals_lines.append(
            f"{label}: {meal['cal']:.1f} ккал "
            f"(Б/Ж/У {meal['p']:.1f}/{meal['f']:.1f}/{meal['c']:.1f})"
        )

    await q.edit_message_text(
        "📊 Итог за день:\n\n"
        f"Калории: {day['cal']:.1f}\n"
        f"Белки: {day['p']:.1f} г\n"
        f"Жиры: {day['f']:.1f} г\n"
        f"Углеводы: {day['c']:.1f} г\n\n"
        "По приёмам пищи:\n"
        + "\n".join(meals_lines)
    )

    await show_main_menu(q)

# ================== ТЕКСТ ==================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ---- ПОИСК ----
    if context.user_data.get("search"):
        context.user_data["search"] = False
        matches = []

        for items in products_by_cat.values():
            for p in items:
                if text.lower() in p.lower():
                    matches.append(p)

        if not matches:
            await update.message.reply_text("❌ Продукт не найден.")
            await show_main_menu(update)
            return

        keyboard = [[InlineKeyboardButton(p, callback_data=f"prod|{p}")] for p in matches]
        keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back")])

        await update.message.reply_text(
            "Найдено:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ---- ГРАММЫ ----
    if "product" in context.user_data:
        try:
            grams = parse_grams(text)
            if grams <= 0:
                raise ValueError
        except:
            await update.message.reply_text("❌ Неверный формат. Пример: 150 или 0.2кг")
            return

        context.user_data["grams"] = grams

        keyboard = [
            [InlineKeyboardButton("Завтрак", callback_data="meal|z")],
            [InlineKeyboardButton("Обед", callback_data="meal|o")],
            [InlineKeyboardButton("Ужин", callback_data="meal|u")],
            [InlineKeyboardButton("Перекус", callback_data="meal|p")]
        ]

        await update.message.reply_text(
            "Выберите приём пищи:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    await update.message.reply_text("Выберите действие в меню.")

# ================== ЗАПУСК ==================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(category_handler, pattern="^cat\\|"))
app.add_handler(CallbackQueryHandler(product_handler, pattern="^prod\\|"))
app.add_handler(CallbackQueryHandler(search_handler, pattern="^search$"))
app.add_handler(CallbackQueryHandler(back_handler, pattern="^back$"))
app.add_handler(CallbackQueryHandler(day_handler, pattern="^day$"))
app.add_handler(CallbackQueryHandler(meal_handler, pattern="^meal\\|"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

print("✅ Бот запущен")
app.run_polling()
