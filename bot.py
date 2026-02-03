import json
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

# ================== ЗАГРУЗКА БАЗЫ ==================
with open("products.json", "r", encoding="utf-8") as f:
    products_by_cat = json.load(f)

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
    context.user_data.setdefault("day_total", {"cal": 0, "p": 0, "f": 0, "c": 0})
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

    data = products_by_cat[cat][product]

    cal = data["calories"] * grams / 100
    p = data["protein"] * grams / 100
    f = data["fat"] * grams / 100
    c = data["carbs"] * grams / 100

    day = context.user_data.setdefault("day_total", {"cal": 0, "p": 0, "f": 0, "c": 0})
    day["cal"] += cal
    day["p"] += p
    day["f"] += f
    day["c"] += c

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

    day = context.user_data.get("day_total")

    if not day or day["cal"] == 0:
        await q.edit_message_text("❌ За сегодня ещё ничего не добавлено.")
        await show_main_menu(q)
        return

    await q.edit_message_text(
        f"📊 Итог за день:\n\n"
        f"Калории: {day['cal']:.1f}\n"
        f"Белки: {day['p']:.1f} г\n"
        f"Жиры: {day['f']:.1f} г\n"
        f"Углеводы: {day['c']:.1f} г"
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
