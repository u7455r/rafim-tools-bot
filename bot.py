import os
import sqlite3
import tempfile
import shutil
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone

import fitz
from PIL import Image
from docx import Document as DocxDocument
from flask import Flask

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    MenuButtonCommands,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8298133943"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "rafimhossen")

DB_FILE = "rafim_pdf_pro.db"

FREE_CREDITS = 10
DAILY_BONUS = 2
REFERRAL_BONUS = 5

WEEKLY_PRICE = 50
MONTHLY_PRICE = 150


# =========================================================
# FLASK HEALTH SERVER - FOR RENDER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Rafim PDF Pro Bot is running!"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            credits INTEGER DEFAULT 10,
            premium_until TEXT,
            referred_by INTEGER,
            referral_paid INTEGER DEFAULT 0,
            last_bonus TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            credits INTEGER NOT NULL,
            max_uses INTEGER NOT NULL,
            used_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            redeemed_at TEXT,
            UNIQUE(user_id, code)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tool TEXT,
            cost INTEGER,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS premium_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            plan TEXT NOT NULL,
            amount INTEGER NOT NULL,
            transaction_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            expires_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# USER FUNCTIONS
# =========================================================

def create_user(user, referred_by=None):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    )

    exists = cur.fetchone()

    if not exists:

        cur.execute("""
            INSERT INTO users
            (user_id, username, first_name, credits, referred_by)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            FREE_CREDITS,
            referred_by
        ))

        conn.commit()

    else:

        cur.execute("""
            UPDATE users
            SET username=?, first_name=?
            WHERE user_id=?
        """, (
            user.username or "",
            user.first_name or "",
            user.id
        ))

        conn.commit()

    conn.close()


def get_user(user_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, username, first_name, credits,
               premium_until, referred_by, referral_paid, last_bonus
        FROM users
        WHERE user_id=?
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    return row


def add_credits(user_id, amount):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET credits = credits + ?
        WHERE user_id=?
    """, (amount, user_id))

    conn.commit()
    conn.close()


def remove_credits(user_id, amount):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET credits = credits - ?
        WHERE user_id=? AND credits >= ?
    """, (amount, user_id, amount))

    changed = cur.rowcount

    conn.commit()
    conn.close()

    return changed > 0


def is_premium(user_id):

    user = get_user(user_id)

    if not user:
        return False

    premium_until = user[4]

    if not premium_until:
        return False

    try:
        expiry = datetime.fromisoformat(premium_until)

        return expiry > datetime.now(timezone.utc).replace(tzinfo=None)

    except Exception:
        return False


def premium_expiry(user_id):

    user = get_user(user_id)

    if not user or not user[4]:
        return None

    try:
        return datetime.fromisoformat(user[4])
    except Exception:
        return None


# =========================================================
# HISTORY
# =========================================================

def save_history(user_id, tool, cost):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO history
        (user_id, tool, cost, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        tool,
        cost,
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()


# =========================================================
# MAIN REPLY KEYBOARD
# =========================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        [
            ["📕 PDF Tools", "🖼️ Image Tools"],
            ["💎 Premium", "👤 My Account"],
            ["🎁 Daily Bonus", "👥 Refer & Earn"],
            ["🎟️ Redeem Code", "📜 History"],
            ["🆘 Support"]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    referred_by = None

    if context.args:

        arg = context.args[0]

        if arg.startswith("ref_"):

            try:
                ref_id = int(arg.replace("ref_", ""))

                if ref_id != user.id:
                    referred_by = ref_id

            except:
                pass

    create_user(user, referred_by)

    conn = db()
    cur = conn.cursor()

    if referred_by:

        cur.execute("""
            SELECT user_id
            FROM users
            WHERE user_id=? AND referred_by IS NULL
        """, (user.id,))

        if cur.fetchone():

            cur.execute("""
                UPDATE users
                SET referred_by=?
                WHERE user_id=?
            """, (referred_by, user.id))

            conn.commit()

    conn.close()

    text = (
        "✨ <b>WELCOME TO RAFIM PDF PRO</b> ✨\n\n"
        "🚀 Your all-in-one PDF & Image Assistant\n\n"
        "📕 PDF Tools\n"
        "🖼️ Image Tools\n"
        "💎 Premium\n"
        "🎁 Daily Bonus\n"
        "👥 Refer & Earn\n"
        "🎟️ Redeem Codes\n\n"
        "👇 নিচের Menu থেকে একটি option নির্বাচন করুন।"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# MENU COMMAND
# =========================================================

async def menu_command(update, context):

    await update.message.reply_text(
        "📋 <b>RAFIM PDF PRO MENU</b>\n\n"
        "👇 আপনার প্রয়োজনীয় option নির্বাচন করুন:",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# PDF MENU
# =========================================================

async def pdf_menu(update, context):

    keyboard = [
        [
            InlineKeyboardButton("📕 PDF → Word", callback_data="pdf_pdf_to_word"),
            InlineKeyboardButton("📄 PDF → TXT", callback_data="pdf_pdf_to_txt")
        ],
        [
            InlineKeyboardButton("🖼️ PDF → JPG", callback_data="pdf_pdf_to_jpg"),
            InlineKeyboardButton("🖼️ PDF → PNG", callback_data="pdf_pdf_to_png")
        ],
        [
            InlineKeyboardButton("📦 Compress PDF", callback_data="pdf_compress"),
            InlineKeyboardButton("🔗 Merge PDF", callback_data="pdf_merge")
        ],
        [
            InlineKeyboardButton("✂️ Split PDF", callback_data="pdf_split"),
            InlineKeyboardButton("📑 Extract Pages", callback_data="pdf_extract")
        ],
        [
            InlineKeyboardButton("📦 PDF → XPS", callback_data="pdf_xps"),
            InlineKeyboardButton("🔐 Protect PDF", callback_data="pdf_protect")
        ],
        [
            InlineKeyboardButton("🔓 Unlock PDF", callback_data="pdf_unlock"),
            InlineKeyboardButton("🖼️ JPG/PNG → PDF", callback_data="pdf_img_to_pdf")
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="main_menu")
        ]
    ]

    text = (
        "📕 <b>PDF TOOLS</b>\n\n"
        "⚡ Fast • Simple • Secure\n\n"
        "👇 একটি PDF Tool নির্বাচন করুন:"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================================================
# IMAGE MENU
# =========================================================

async def image_menu(update, context):

    keyboard = [
        [
            InlineKeyboardButton("🗜️ Compress Image", callback_data="img_compress"),
            InlineKeyboardButton("🔄 Convert PNG", callback_data="img_png")
        ],
        [
            InlineKeyboardButton("📐 Resize Image", callback_data="img_resize")
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="main_menu")
        ]
    ]

    text = (
        "🖼️ <b>IMAGE TOOLS</b>\n\n"
        "✨ JPG / PNG Image Utilities\n\n"
        "👇 একটি Tool নির্বাচন করুন:"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================================================
# PREMIUM MENU
# =========================================================

async def premium_menu(update, context):

    keyboard = [
        [
            InlineKeyboardButton(
                f"💎 Weekly — ৳{WEEKLY_PRICE}",
                callback_data="premium_weekly"
            )
        ],
        [
            InlineKeyboardButton(
                f"👑 Monthly — ৳{MONTHLY_PRICE}",
                callback_data="premium_monthly"
            )
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="main_menu")
        ]
    ]

    text = (
        "💎 <b>RAFIM PDF PRO PREMIUM</b>\n\n"
        "🚀 Premium সুবিধা:\n\n"
        "⚡ Premium access\n"
        "📕 Advanced PDF tools\n"
        "🖼️ Advanced Image tools\n"
        "🔥 Priority processing\n"
        "💎 Premium status\n\n"
        f"🗓️ Weekly: ৳{WEEKLY_PRICE}\n"
        f"📅 Monthly: ৳{MONTHLY_PRICE}\n\n"
        "👇 আপনার Premium Plan নির্বাচন করুন:"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================================================
# PREMIUM PLAN
# =========================================================

async def premium_plan(update, context):

    query = update.callback_query

    await query.answer()

    if query.data == "premium_weekly":

        plan = "Weekly"
        amount = WEEKLY_PRICE

    else:

        plan = "Monthly"
        amount = MONTHLY_PRICE

    context.user_data["premium_plan"] = plan
    context.user_data["premium_amount"] = amount
    context.user_data["waiting_transaction"] = True

    await query.edit_message_text(
        "💎 <b>PREMIUM PURCHASE</b>\n\n"
        f"📦 Plan: <b>{plan}</b>\n"
        f"💰 Amount: <b>৳{amount}</b>\n\n"
        "📱 Payment করার পর আপনার Transaction ID পাঠান।\n\n"
        "🧾 উদাহরণ:\n"
        "<code>TXN123456789</code>\n\n"
        "✍️ এখন Transaction ID লিখুন:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="premium"
                )
            ]
        ])
    )


# =========================================================
# PREMIUM TRANSACTION
# =========================================================

async def handle_premium_transaction(update, context):

    if not context.user_data.get("waiting_transaction"):
        return False

    txn_id = update.message.text.strip()

    if len(txn_id) < 3:

        await update.message.reply_text(
            "⚠️ সঠিক Transaction ID পাঠান।"
        )

        return True

    plan = context.user_data.get("premium_plan")
    amount = context.user_data.get("premium_amount")

    if not plan or not amount:

        context.user_data.clear()

        await update.message.reply_text(
            "⚠️ Premium session expired.\n"
            "আবার 💎 Premium থেকে শুরু করুন।"
        )

        return True

    user = update.effective_user

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO premium_requests
        (
            user_id,
            username,
            plan,
            amount,
            transaction_id,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    """, (
        user.id,
        user.username or "",
        plan,
        amount,
        txn_id,
        datetime.utcnow().isoformat()
    ))

    request_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data.clear()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ APPROVE",
                callback_data=f"approve_premium_{request_id}"
            ),
            InlineKeyboardButton(
                "❌ REJECT",
                callback_data=f"reject_premium_{request_id}"
            )
        ]
    ])

    admin_text = (
        "🔔 <b>NEW PREMIUM REQUEST</b>\n\n"
        f"👤 User: @{user.username or 'No Username'}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"💎 Plan: <b>{plan}</b>\n"
        f"💰 Amount: ৳{amount}\n"
        f"🧾 Transaction ID:\n"
        f"<code>{txn_id}</code>\n\n"
        f"📌 Request ID: <code>{request_id}</code>\n"
        "⏳ Status: <b>PENDING</b>"
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_text,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await update.message.reply_text(
        "📩 <b>REQUEST SENT!</b>\n\n"
        "আপনার Premium request Admin-এর কাছে পাঠানো হয়েছে।\n\n"
        "⏳ Payment verification শেষ হলে "
        "আপনাকে automatic notification দেওয়া হবে।",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

    return True


# =========================================================
# PREMIUM ADMIN APPROVE / REJECT
# =========================================================

async def premium_admin_callback(update, context):

    query = update.callback_query

    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "⛔ শুধু Admin এই action করতে পারবেন।",
            show_alert=True
        )

        return

    await query.answer()

    data = query.data

    if data.startswith("approve_premium_"):

        request_id = int(
            data.replace("approve_premium_", "")
        )

        conn = db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                user_id,
                plan,
                amount,
                transaction_id,
                status
            FROM premium_requests
            WHERE id=?
        """, (request_id,))

        row = cur.fetchone()

        if not row:

            conn.close()

            await query.answer(
                "Request পাওয়া যায়নি!",
                show_alert=True
            )

            return

        user_id, plan, amount, txn_id, status = row

        if status != "pending":

            conn.close()

            await query.answer(
                f"Already {status}",
                show_alert=True
            )

            return

        days = 7 if plan == "Weekly" else 30

        expiry = datetime.utcnow() + timedelta(days=days)

        cur.execute("""
            UPDATE premium_requests
            SET
                status='approved',
                expires_at=?
            WHERE id=?
        """, (
            expiry.isoformat(),
            request_id
        ))

        cur.execute("""
            UPDATE users
            SET premium_until=?
            WHERE user_id=?
        """, (
            expiry.isoformat(),
            user_id
        ))

        conn.commit()
        conn.close()

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 <b>PREMIUM ACTIVATED!</b> 🎉\n\n"
                "💎 আপনার Premium successfully activate হয়েছে।\n\n"
                f"📦 Plan: <b>{plan}</b>\n"
                f"💰 Paid: ৳{amount}\n"
                f"📅 Valid Until: "
                f"<b>{expiry.strftime('%d-%m-%Y')}</b>\n\n"
                "🚀 এখন Premium ব্যবহার করতে পারবেন।"
            ),
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        await query.edit_message_text(
            query.message.text +
            "\n\n✅ <b>APPROVED</b>\n"
            f"📅 Expiry: {expiry.strftime('%d-%m-%Y')}",
            parse_mode="HTML"
        )

    elif data.startswith("reject_premium_"):

        request_id = int(
            data.replace("reject_premium_", "")
        )

        conn = db()
        cur = conn.cursor()

        cur.execute("""
            SELECT user_id, status
            FROM premium_requests
            WHERE id=?
        """, (request_id,))

        row = cur.fetchone()

        if not row:

            conn.close()

            await query.answer(
                "Request পাওয়া যায়নি!",
                show_alert=True
            )

            return

        user_id, status = row

        if status != "pending":

            conn.close()

            await query.answer(
                f"Already {status}",
                show_alert=True
            )

            return

        cur.execute("""
            UPDATE premium_requests
            SET status='rejected'
            WHERE id=?
        """, (request_id,))

        conn.commit()
        conn.close()

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>PREMIUM REQUEST REJECTED</b>\n\n"
                "আপনার payment verification approve করা হয়নি।\n\n"
                "🆘 Support: @rafimhossen"
            ),
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        await query.edit_message_text(
            query.message.text +
            "\n\n❌ <b>REJECTED</b>",
            parse_mode="HTML"
        )


# =========================================================
# ACCOUNT
# =========================================================

async def account(update, context):

    user = get_user(update.effective_user.id)

    if not user:
        create_user(update.effective_user)
        user = get_user(update.effective_user.id)

    credits = user[3]
    premium = is_premium(update.effective_user.id)

    if premium:

        expiry = premium_expiry(update.effective_user.id)

        premium_text = (
            "💎 Premium: <b>ACTIVE</b>\n"
            f"📅 Until: <b>{expiry.strftime('%d-%m-%Y')}</b>"
        )

    else:

        premium_text = "💎 Premium: <b>NOT ACTIVE</b>"

    await update.message.reply_text(
        "👤 <b>MY ACCOUNT</b>\n\n"
        f"🆔 User ID: <code>{user[0]}</code>\n"
        f"👤 Username: @{user[1] or 'None'}\n"
        f"💰 Credits: <b>{credits}</b>\n\n"
        f"{premium_text}",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# DAILY BONUS
# =========================================================

async def daily_bonus(update, context):

    user_id = update.effective_user.id

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT last_bonus FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    today = datetime.utcnow().strftime("%Y-%m-%d")

    if row and row[0] == today:

        conn.close()

        await update.message.reply_text(
            "⏰ <b>DAILY BONUS ALREADY CLAIMED</b>\n\n"
            "আগামীকাল আবার আসুন। 🎁",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        return

    cur.execute("""
        UPDATE users
        SET credits = credits + ?,
            last_bonus = ?
        WHERE user_id=?
    """, (
        DAILY_BONUS,
        today,
        user_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎁 <b>DAILY BONUS CLAIMED!</b>\n\n"
        f"💎 +{DAILY_BONUS} Credits যোগ হয়েছে।\n\n"
        "🔥 আগামীকাল আবার Bonus নিতে আসুন!",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# REFERRAL
# =========================================================

async def refer(update, context):

    user_id = update.effective_user.id

    me = await context.bot.get_me()

    link = f"https://t.me/{me.username}?start=ref_{user_id}"

    await update.message.reply_text(
        "👥 <b>REFER & EARN</b>\n\n"
        "বন্ধুকে আপনার invite link দিয়ে Join করান।\n\n"
        f"🎁 Referral Bonus: <b>+{REFERRAL_BONUS} Credits</b>\n\n"
        "🔗 আপনার Personal Link:\n"
        f"<code>{link}</code>\n\n"
        "📢 Linkটি বন্ধুদের সাথে Share করুন।",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# REDEEM CODE
# =========================================================

async def redeem_start(update, context):

    context.user_data["waiting_redeem"] = True

    await update.message.reply_text(
        "🎟️ <b>REDEEM CODE</b>\n\n"
        "আপনার Redeem Code পাঠান 👇\n\n"
        "উদাহরণ:\n"
        "<code>RAFIM20</code>",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


async def process_redeem(update, context):

    if not context.user_data.get("waiting_redeem"):
        return False

    code = update.message.text.strip().upper()

    context.user_data["waiting_redeem"] = False

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT credits, max_uses, used_count, active
        FROM redeem_codes
        WHERE code=?
    """, (code,))

    row = cur.fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "❌ <b>INVALID CODE</b>\n\n"
            "এই Redeem Code পাওয়া যায়নি।",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        return True

    reward, max_uses, used_count, active = row

    if not active:

        conn.close()

        await update.message.reply_text(
            "⛔ এই Redeem Code বন্ধ করা হয়েছে।",
            reply_markup=main_keyboard()
        )

        return True

    if used_count >= max_uses:

        conn.close()

        await update.message.reply_text(
            "⚠️ এই Redeem Code-এর ব্যবহার সীমা শেষ।",
            reply_markup=main_keyboard()
        )

        return True

    cur.execute("""
        SELECT id
        FROM redemptions
        WHERE user_id=? AND code=?
    """, (
        update.effective_user.id,
        code
    ))

    if cur.fetchone():

        conn.close()

        await update.message.reply_text(
            "⚠️ <b>ALREADY REDEEMED</b>\n\n"
            "আপনি এই Code আগে ব্যবহার করেছেন।",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        return True

    cur.execute("""
        INSERT INTO redemptions
        (user_id, code, redeemed_at)
        VALUES (?, ?, ?)
    """, (
        update.effective_user.id,
        code,
        datetime.utcnow().isoformat()
    ))

    cur.execute("""
        UPDATE redeem_codes
        SET used_count = used_count + 1
        WHERE code=?
    """, (code,))

    cur.execute("""
        UPDATE users
        SET credits = credits + ?
        WHERE user_id=?
    """, (
        reward,
        update.effective_user.id
    ))

    conn.commit()
    conn.close()

    user = get_user(update.effective_user.id)

    await update.message.reply_text(
        "🎉 <b>REDEEM SUCCESSFUL!</b>\n\n"
        f"🎟️ Code: <code>{code}</code>\n"
        f"💎 Reward: <b>+{reward} Credits</b>\n"
        f"💰 Current Balance: <b>{user[3]}</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

    return True


# =========================================================
# HISTORY
# =========================================================

async def history(update, context):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT tool, cost, created_at
        FROM history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (update.effective_user.id,))

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "📜 <b>HISTORY</b>\n\n"
            "এখনও কোনো tool ব্যবহার করা হয়নি।",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        return

    text = "📜 <b>RECENT HISTORY</b>\n\n"

    for tool, cost, created in rows:

        text += (
            f"🔹 {tool}\n"
            f"💎 Cost: {cost}\n"
            f"🕒 {created[:16]}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# =========================================================
# SUPPORT
# =========================================================

async def support(update, context):

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🆘 Contact Support",
                url=f"https://t.me/{SUPPORT_USERNAME}"
            )
        ]
    ])

    await update.message.reply_text(
        "🆘 <b>RAFIM PDF PRO SUPPORT</b>\n\n"
        "কোনো সমস্যা হলে আমাদের Support-এ যোগাযোগ করুন।\n\n"
        f"👤 @{SUPPORT_USERNAME}",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN REDEEM COMMANDS
# =========================================================

async def create_code(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 3:

        await update.message.reply_text(
            "ব্যবহার:\n"
            "/createcode CODE CREDITS MAX_USES\n\n"
            "উদাহরণ:\n"
            "/createcode RAFIM20 20 100"
        )

        return

    code = context.args[0].upper()

    try:
        credits = int(context.args[1])
        max_uses = int(context.args[2])
    except:

        await update.message.reply_text(
            "❌ Credits এবং Max Uses সংখ্যা হতে হবে।"
        )

        return

    conn = db()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO redeem_codes
            (code, credits, max_uses, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            code,
            credits,
            max_uses,
            datetime.utcnow().isoformat()
        ))

        conn.commit()

    except sqlite3.IntegrityError:

        conn.close()

        await update.message.reply_text(
            "⚠️ এই Code আগে থেকেই আছে।"
        )

        return

    conn.close()

    await update.message.reply_text(
        "✅ <b>REDEEM CODE CREATED</b>\n\n"
        f"🎟️ Code: <code>{code}</code>\n"
        f"💎 Credits: {credits}\n"
        f"👥 Max Uses: {max_uses}",
        parse_mode="HTML"
    )


async def codes(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT code, credits, max_uses, used_count, active
        FROM redeem_codes
        ORDER BY rowid DESC
    """)

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "🎟️ কোনো Redeem Code নেই।"
        )

        return

    text = "🎟️ <b>REDEEM CODES</b>\n\n"

    for code, credits, max_uses, used, active in rows:

        status = "🟢 Active" if active else "🔴 Disabled"

        text += (
            f"🔑 <code>{code}</code>\n"
            f"💎 Reward: {credits}\n"
            f"👥 Used: {used}/{max_uses}\n"
            f"{status}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


async def disable_code(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 1:

        await update.message.reply_text(
            "/disablecode CODE"
        )

        return

    code = context.args[0].upper()

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE redeem_codes
        SET active=0
        WHERE code=?
    """, (code,))

    changed = cur.rowcount

    conn.commit()
    conn.close()

    if changed:

        await update.message.reply_text(
            f"⛔ Code <code>{code}</code> disabled.",
            parse_mode="HTML"
        )

    else:

        await update.message.reply_text(
            "❌ Code পাওয়া যায়নি।"
        )


# =========================================================
# ADMIN CREDIT COMMANDS
# =========================================================

async def add_credits_admin(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "/addcredits USER_ID AMOUNT"
        )
        return

    try:

        user_id = int(context.args[0])
        amount = int(context.args[1])

    except:

        await update.message.reply_text(
            "❌ ভুল সংখ্যা।"
        )

        return

    add_credits(user_id, amount)

    await update.message.reply_text(
        f"✅ {amount} Credits added to {user_id}"
    )


# =========================================================
# ADMIN PREMIUM COMMAND
# =========================================================

async def add_premium(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "/addpremium USER_ID DAYS"
        )

        return

    try:

        user_id = int(context.args[0])
        days = int(context.args[1])

    except:

        await update.message.reply_text(
            "❌ ভুল সংখ্যা।"
        )

        return

    expiry = datetime.utcnow() + timedelta(days=days)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET premium_until=?
        WHERE user_id=?
    """, (
        expiry.isoformat(),
        user_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Premium added.\n"
        f"👤 User: {user_id}\n"
        f"📅 Days: {days}"
    )


# =========================================================
# ADMIN STATS
# =========================================================

async def stats(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE premium_until IS NOT NULL
    """)

    premium = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM premium_requests")
    requests = cur.fetchone()[0]

    conn.close()

    await update.message.reply_text(
        "📊 <b>RAFIM PDF PRO STATS</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"💎 Premium Users: <b>{premium}</b>\n"
        f"📩 Premium Requests: <b>{requests}</b>",
        parse_mode="HTML"
    )


# =========================================================
# PDF PROCESSING
# =========================================================

TOOL_COST = {
    "PDF → Word": 2,
    "PDF → TXT": 1,
    "PDF → JPG": 2,
    "PDF → PNG": 2,
    "Compress PDF": 2,
    "Merge PDF": 3,
    "Split PDF": 3,
    "Extract Pages": 2,
    "PDF → XPS": 3,
    "Protect PDF": 2,
    "Unlock PDF": 2,
    "JPG/PNG → PDF": 1,
    "Compress Image": 1,
    "Convert PNG": 1,
    "Resize Image": 1,
}


def get_cost(tool):

    return TOOL_COST.get(tool, 1)


def clean_name(name):

    return "".join(
        c if c.isalnum() or c in "._-" else "_"
        for c in name
    )


async def progress_message(message, text):

    return await message.reply_text(
        text,
        parse_mode="HTML"
    )


async def pdf_callback(update, context):

    query = update.callback_query

    await query.answer()

    if query.data == "pdf_merge":

        context.user_data["waiting_pdf"] = "Merge PDF"
        context.user_data["merge_files"] = []

        await query.edit_message_text(
            "🔗 <b>MERGE PDF</b>\n\n"
            "📤 প্রথম PDF পাঠান।\n"
            "এরপর আরও PDF পাঠাতে পারবেন।\n\n"
            "সব পাঠানো হলে:\n"
            "<code>/done</code>",
            parse_mode="HTML"
        )

        return

    tool_map = {

        "pdf_pdf_to_word": "PDF → Word",
        "pdf_pdf_to_txt": "PDF → TXT",
        "pdf_pdf_to_jpg": "PDF → JPG",
        "pdf_pdf_to_png": "PDF → PNG",
        "pdf_compress": "Compress PDF",
        "pdf_split": "Split PDF",
        "pdf_extract": "Extract Pages",
        "pdf_xps": "PDF → XPS",
        "pdf_protect": "Protect PDF",
        "pdf_unlock": "Unlock PDF",
        "pdf_img_to_pdf": "JPG/PNG → PDF",

    }

    tool = tool_map.get(query.data)

    if not tool:
        return

    context.user_data["waiting_pdf"] = tool

    await query.edit_message_text(
        f"📕 <b>{tool}</b>\n\n"
        "📤 এখন আপনার PDF file পাঠান।\n\n"
        f"💎 Cost: <b>{get_cost(tool)} Credits</b>",
        parse_mode="HTML"
    )


# =========================================================
# DOCUMENT HANDLER
# =========================================================

async def document_handler(update, context):

    document = update.message.document

    if not document:
        return

    waiting = context.user_data.get("waiting_pdf")

    if not waiting:
        return

    user_id = update.effective_user.id

    tool = waiting
    cost = get_cost(tool)

    if not is_premium(user_id):

        user = get_user(user_id)

        if not user or user[3] < cost:

            await update.message.reply_text(
                "⚠️ <b>INSUFFICIENT CREDITS</b>\n\n"
                f"💎 Required: {cost}\n"
                f"💰 Your Balance: {user[3] if user else 0}\n\n"
                "🎁 Daily Bonus নিন অথবা 💎 Premium নিন।",
                parse_mode="HTML",
                reply_markup=main_keyboard()
            )

            return

        remove_credits(user_id, cost)

    file = await document.get_file()

    temp_dir = Path(
        tempfile.mkdtemp(prefix="rafim_")
    )

    input_path = temp_dir / clean_name(
        document.file_name or "input.pdf"
    )

    await file.download_to_drive(input_path)

    output_files = []

    status = await update.message.reply_text(
        "⚡ <b>PROCESSING...</b>\n\n"
        "🔵 10%\n"
        "⏳ Preparing file...",
        parse_mode="HTML"
    )

    try:

        await status.edit_text(
            "⚡ <b>PROCESSING...</b>\n\n"
            "🟢 30%\n"
            "🔄 Processing...",
            parse_mode="HTML"
        )

        if tool == "PDF → TXT":

            doc = fitz.open(input_path)

            text = ""

            for page in doc:
                text += page.get_text() + "\n"

            output = temp_dir / "converted.txt"

            output.write_text(
                text,
                encoding="utf-8"
            )

            output_files.append(output)

            doc.close()

        elif tool in ["PDF → JPG", "PDF → PNG"]:

            doc = fitz.open(input_path)

            ext = "jpg" if tool.endswith("JPG") else "png"

            for i, page in enumerate(doc):

                pix = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    alpha=False
                )

                output = temp_dir / f"page_{i+1}.{ext}"

                if ext == "jpg":
                    pix.save(str(output))
                else:
                    pix.save(str(output))

                output_files.append(output)

            doc.close()

        elif tool == "PDF → Word":

            doc = fitz.open(input_path)

            word = DocxDocument()

            for page in doc:

                text = page.get_text()

                if text.strip():

                    word.add_paragraph(text)

            output = temp_dir / "converted.docx"

            word.save(output)

            output_files.append(output)

            doc.close()

        elif tool == "Compress PDF":

            output = temp_dir / "compressed.pdf"

            subprocess.run([
                "gs",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                "-dPDFSETTINGS=/ebook",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                f"-sOutputFile={output}",
                str(input_path)
            ], check=True)

            output_files.append(output)

        elif tool == "PDF → XPS":

            output = temp_dir / "converted.xps"

            subprocess.run([
                "gs",
                "-sDEVICE=xpswrite",
                "-dNOPAUSE",
                "-dBATCH",
                "-dQUIET",
                f"-sOutputFile={output}",
                str(input_path)
            ], check=True)

            output_files.append(output)

        elif tool == "Split PDF":

            doc = fitz.open(input_path)

            for i in range(len(doc)):

                new_doc = fitz.open()

                new_doc.insert_pdf(
                    doc,
                    from_page=i,
                    to_page=i
                )

                output = temp_dir / f"page_{i+1}.pdf"

                new_doc.save(output)

                new_doc.close()

                output_files.append(output)

            doc.close()

        elif tool == "Extract Pages":

            doc = fitz.open(input_path)

            pages = context.user_data.get(
                "extract_pages",
                [0]
            )

            new_doc = fitz.open()

            for page_number in pages:

                if 0 <= page_number < len(doc):

                    new_doc.insert_pdf(
                        doc,
                        from_page=page_number,
                        to_page=page_number
                    )

            output = temp_dir / "extracted_pages.pdf"

            new_doc.save(output)

            new_doc.close()
            doc.close()

            output_files.append(output)

        elif tool == "Protect PDF":

            password = context.user_data.get(
                "pdf_password",
                "123456"
            )

            doc = fitz.open(input_path)

            output = temp_dir / "protected.pdf"

            doc.save(
                output,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw=password,
                user_pw=password
            )

            doc.close()

            output_files.append(output)

        elif tool == "Unlock PDF":

            password = context.user_data.get(
                "pdf_password"
            )

            if not password:

                context.user_data["unlock_path"] = str(
                    input_path
                )

                await status.edit_text(
                    "🔓 <b>UNLOCK PDF</b>\n\n"
                    "🔐 PDF password পাঠান:",
                    parse_mode="HTML"
                )

                return

            doc = fitz.open(
                input_path,
                password=password
            )

            output = temp_dir / "unlocked.pdf"

            doc.save(output)

            doc.close()

            output_files.append(output)

        else:

            await status.edit_text(
                "⚠️ এই Tool-এর processing অংশটি পরে configure করতে হবে।",
                parse_mode="HTML"
            )

            return

        await status.edit_text(
            "⚡ <b>PROCESSING...</b>\n\n"
            "🟢 90%\n"
            "📦 Preparing result...",
            parse_mode="HTML"
        )

        for output in output_files:

            with open(output, "rb") as f:

                await update.message.reply_document(
                    document=f,
                    caption=(
                        f"✅ <b>{tool}</b> Complete!\n\n"
                        "🚀 Rafim PDF Pro"
                    ),
                    parse_mode="HTML"
                )

        await status.edit_text(
            "🎉 <b>100% COMPLETE!</b>\n\n"
            f"✅ {tool} সফলভাবে সম্পন্ন হয়েছে।",
            parse_mode="HTML"
        )

        save_history(
            user_id,
            tool,
            0 if is_premium(user_id) else cost
        )

    except Exception as e:

        await status.edit_text(
            "❌ <b>PROCESSING FAILED</b>\n\n"
            "ফাইলটি process করা যায়নি।\n"
            "ফাইলটি আবার চেষ্টা করুন অথবা Support-এ যোগাযোগ করুন।",
            parse_mode="HTML"
        )

    finally:

        context.user_data.pop("waiting_pdf", None)

        try:
            shutil.rmtree(temp_dir)
        except:
            pass


# =========================================================
# IMAGE HANDLER
# =========================================================

async def photo_handler(update, context):

    tool = context.user_data.get("waiting_image")

    if not tool:
        return

    user_id = update.effective_user.id

    cost = get_cost(tool)

    if not is_premium(user_id):

        user = get_user(user_id)

        if not user or user[3] < cost:

            await update.message.reply_text(
                "⚠️ Credits কম।",
                reply_markup=main_keyboard()
            )

            return

        remove_credits(user_id, cost)

    photo = update.message.photo[-1]

    file = await photo.get_file()

    temp_dir = Path(
        tempfile.mkdtemp(prefix="rafim_img_")
    )

    input_path = temp_dir / "input.jpg"

    await file.download_to_drive(input_path)

    try:

        img = Image.open(input_path)

        if tool == "Compress Image":

            output = temp_dir / "compressed.jpg"

            img.save(
                output,
                "JPEG",
                quality=55,
                optimize=True
            )

        elif tool == "Convert PNG":

            output = temp_dir / "converted.png"

            img.convert("RGBA").save(output)

        elif tool == "Resize Image":

            width = 1000

            ratio = width / img.width

            height = int(img.height * ratio)

            resized = img.resize(
                (width, height)
            )

            output = temp_dir / "resized.jpg"

            resized.save(
                output,
                "JPEG",
                quality=85
            )

        else:

            output = input_path

        with open(output, "rb") as f:

            await update.message.reply_document(
                document=f,
                caption=(
                    f"✅ <b>{tool}</b> Complete!\n\n"
                    "🚀 Rafim PDF Pro"
                ),
                parse_mode="HTML"
            )

        save_history(
            user_id,
            tool,
            0 if is_premium(user_id) else cost
        )

    except Exception:

        await update.message.reply_text(
            "❌ Image processing failed."
        )

    finally:

        context.user_data.pop("waiting_image", None)

        try:
            shutil.rmtree(temp_dir)
        except:
            pass


# =========================================================
# IMAGE CALLBACK
# =========================================================

async def image_callback(update, context):

    query = update.callback_query

    await query.answer()

    mapping = {
        "img_compress": "Compress Image",
        "img_png": "Convert PNG",
        "img_resize": "Resize Image"
    }

    tool = mapping.get(query.data)

    if not tool:
        return

    context.user_data["waiting_image"] = tool

    await query.edit_message_text(
        f"🖼️ <b>{tool}</b>\n\n"
        "📤 এখন আপনার image পাঠান।\n\n"
        f"💎 Cost: {get_cost(tool)} Credits",
        parse_mode="HTML"
    )


# =========================================================
# MAIN CALLBACK
# =========================================================

async def callback_handler(update, context):

    query = update.callback_query

    data = query.data

    if data == "main_menu":

        await query.answer()

        await query.edit_message_text(
            "📋 <b>MAIN MENU</b>\n\n"
            "👇 নিচের Reply Keyboard ব্যবহার করুন।",
            parse_mode="HTML"
        )

    elif data == "pdf_menu":

        await pdf_menu(update, context)

    elif data == "image_menu":

        await image_menu(update, context)

    elif data == "premium":

        await query.answer()

        await premium_menu(update, context)

    elif data.startswith("pdf_"):

        await pdf_callback(update, context)

    elif data.startswith("img_"):

        await image_callback(update, context)

    elif data in [
        "premium_weekly",
        "premium_monthly"
    ]:

        await premium_plan(update, context)

    elif data.startswith("approve_premium_") or \
            data.startswith("reject_premium_"):

        await premium_admin_callback(update, context)


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(update, context):

    text = update.message.text.strip()

    # Premium transaction first
    if await handle_premium_transaction(update, context):
        return

    # Redeem code
    if await process_redeem(update, context):
        return

    if text == "📕 PDF Tools":

        await pdf_menu(update, context)
        return

    if text == "🖼️ Image Tools":

        await image_menu(update, context)
        return

    if text == "💎 Premium":

        await premium_menu(update, context)
        return

    if text == "👤 My Account":

        await account(update, context)
        return

    if text == "🎁 Daily Bonus":

        await daily_bonus(update, context)
        return

    if text == "👥 Refer & Earn":

        await refer(update, context)
        return

    if text == "🎟️ Redeem Code":

        await redeem_start(update, context)
        return

    if text == "📜 History":

        await history(update, context)
        return

    if text == "🆘 Support":

        await support(update, context)
        return


# =========================================================
# MENU BUTTON / TELEGRAM COMMANDS
# =========================================================

async def setup_bot(application):

    commands = [

        BotCommand(
            "start",
            "🚀 Start Bot"
        ),

        BotCommand(
            "menu",
            "📋 Main Menu"
        ),

        BotCommand(
            "premium",
            "💎 Premium"
        ),

        BotCommand(
            "account",
            "👤 My Account"
        ),

        BotCommand(
            "bonus",
            "🎁 Daily Bonus"
        ),

        BotCommand(
            "refer",
            "👥 Refer & Earn"
        ),

        BotCommand(
            "redeem",
            "🎟️ Redeem Code"
        ),

        BotCommand(
            "history",
            "📜 History"
        ),

        BotCommand(
            "support",
            "🆘 Support"
        )
    ]

    await application.bot.set_my_commands(commands)

    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonCommands()
    )


async def premium_command(update, context):
    await premium_menu(update, context)


async def account_command(update, context):
    await account(update, context)


async def bonus_command(update, context):
    await daily_bonus(update, context)


async def refer_command(update, context):
    await refer(update, context)


async def redeem_command(update, context):
    await redeem_start(update, context)


async def history_command(update, context):
    await history(update, context)


async def support_command(update, context):
    await support(update, context)


# =========================================================
# MERGE PDF
# =========================================================

async def merge_file_handler(update, context):

    waiting = context.user_data.get("waiting_pdf")

    if waiting != "Merge PDF":
        return

    document = update.message.document

    if not document:
        return

    temp_dir = context.user_data.get("merge_dir")

    if not temp_dir:

        temp_dir = tempfile.mkdtemp(
            prefix="rafim_merge_"
        )

        context.user_data["merge_dir"] = temp_dir

    file = await document.get_file()

    path = Path(temp_dir) / clean_name(
        document.file_name or "file.pdf"
    )

    await file.download_to_drive(path)

    files = context.user_data.setdefault(
        "merge_files",
        []
    )

    files.append(str(path))

    await update.message.reply_text(
        f"📎 PDF #{len(files)} added.\n\n"
        "➕ আরও PDF পাঠান অথবা\n"
        "✅ সব শেষ হলে /done লিখুন।"
    )


async def done_command(update, context):

    files = context.user_data.get(
        "merge_files",
        []
    )

    if len(files) < 2:

        await update.message.reply_text(
            "⚠️ Merge করতে কমপক্ষে 2টি PDF লাগবে।"
        )

        return

    user_id = update.effective_user.id
    cost = get_cost("Merge PDF")

    if not is_premium(user_id):

        user = get_user(user_id)

        if not user or user[3] < cost:

            await update.message.reply_text(
                "⚠️ Credits কম।"
            )

            return

        remove_credits(user_id, cost)

    temp_dir = context.user_data["merge_dir"]

    output = Path(temp_dir) / "merged.pdf"

    try:

        result = fitz.open()

        for file in files:

            doc = fitz.open(file)

            result.insert_pdf(doc)

            doc.close()

        result.save(output)

        result.close()

        with open(output, "rb") as f:

            await update.message.reply_document(
                document=f,
                caption=(
                    "🎉 <b>MERGE COMPLETE!</b>\n\n"
                    f"📚 Files: {len(files)}\n"
                    "🚀 Rafim PDF Pro"
                ),
                parse_mode="HTML"
            )

        save_history(
            user_id,
            "Merge PDF",
            0 if is_premium(user_id) else cost
        )

    except Exception:

        await update.message.reply_text(
            "❌ Merge failed."
        )

    finally:

        context.user_data.pop("waiting_pdf", None)
        context.user_data.pop("merge_files", None)
        context.user_data.pop("merge_dir", None)

        try:
            shutil.rmtree(temp_dir)
        except:
            pass


# =========================================================
# APPLICATION
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    init_db()

    threading.Thread(
        target=run_web,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(setup_bot)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("menu", menu_command)
    )

    application.add_handler(
        CommandHandler("premium", premium_command)
    )

    application.add_handler(
        CommandHandler("account", account_command)
    )

    application.add_handler(
        CommandHandler("bonus", bonus_command)
    )

    application.add_handler(
        CommandHandler("refer", refer_command)
    )

    application.add_handler(
        CommandHandler("redeem", redeem_command)
    )

    application.add_handler(
        CommandHandler("history", history_command)
    )

    application.add_handler(
        CommandHandler("support", support_command)
    )

    application.add_handler(
        CommandHandler("done", done_command)
    )

    # Admin commands
    application.add_handler(
        CommandHandler("createcode", create_code)
    )

    application.add_handler(
        CommandHandler("codes", codes)
    )

    application.add_handler(
        CommandHandler("disablecode", disable_code)
    )

    application.add_handler(
        CommandHandler("addcredits", add_credits_admin)
    )

    application.add_handler(
        CommandHandler("addpremium", add_premium)
    )

    application.add_handler(
        CommandHandler("stats", stats)
    )

    # Premium admin approval
    application.add_handler(
        CallbackQueryHandler(
            premium_admin_callback,
            pattern=r"^(approve|reject)_premium_[0-9]+$"
        )
    )

    # Main callback
    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # Merge PDF
    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            merge_file_handler
        ),
        group=1
    )

    # Normal documents
    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler
        ),
        group=2
    )

    # Photos
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler
        )
    )

    # Text
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    print("Rafim PDF Pro is running...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
