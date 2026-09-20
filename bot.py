import os
import io
import re
import json
import time
import uuid
import sqlite3
import asyncio
import threading
import tempfile
from datetime import datetime, date, timedelta

import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageEnhance
from docx import Document as WordDocument
from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "8298133943"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "rafimhossen")

DB_FILE = os.getenv("DB_FILE", "rafim_pdf_pro.db")

FREE_CREDITS = int(os.getenv("FREE_CREDITS", "10"))
DAILY_BONUS = int(os.getenv("DAILY_BONUS", "3"))

FREE_FILE_LIMIT_MB = 20
PREMIUM_FILE_LIMIT_MB = 100

WEEKLY_PRICE = 50
MONTHLY_PRICE = 150


# =========================================================
# FLASK HEALTH SERVER FOR RENDER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Rafim PDF Pro is running!"


@app.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            credits INTEGER DEFAULT 10,
            premium INTEGER DEFAULT 0,
            premium_until TEXT,
            joined_at TEXT,
            last_bonus TEXT,
            referral_code TEXT,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            language TEXT DEFAULT 'en',
            banned INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            streak INTEGER DEFAULT 0,
            last_streak TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            credits INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT 1,
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
            status TEXT,
            cost INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS premium_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            plan TEXT,
            amount INTEGER,
            txn_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS credit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            language TEXT DEFAULT 'en',
            notifications INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_levels (
            user_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            target TEXT,
            status TEXT DEFAULT 'waiting',
            message_id INTEGER,
            total INTEGER DEFAULT 0,
            sent INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            created_at TEXT,
            finished_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# USER FUNCTIONS
# =========================================================

def get_user(user_id):
    conn = db()

    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    return row


def ensure_user(user):
    if not user:
        return

    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""

    if not get_user(user_id):

        referral_code = f"RAFIM{user_id}"

        conn = db()

        conn.execute("""
            INSERT INTO users
            (
                user_id,
                username,
                first_name,
                credits,
                joined_at,
                referral_code
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            username,
            first_name,
            FREE_CREDITS,
            datetime.now().isoformat(),
            referral_code
        ))

        conn.execute("""
            INSERT OR IGNORE INTO user_settings
            (
                user_id,
                language,
                notifications
            )
            VALUES (?, 'en', 1)
        """, (user_id,))

        conn.commit()
        conn.close()

    else:

        conn = db()

        conn.execute("""
            UPDATE users
            SET username=?,
                first_name=?
            WHERE user_id=?
        """, (
            username,
            first_name,
            user_id
        ))

        conn.commit()
        conn.close()


def is_banned(user_id):

    row = get_user(user_id)

    return bool(
        row and row["banned"]
    )


def is_premium(user_id):

    row = get_user(user_id)

    if not row:
        return False

    if not row["premium"]:
        return False

    until = row["premium_until"]

    if not until:
        return True

    try:
        return (
            datetime.fromisoformat(until)
            > datetime.now()
        )
    except Exception:
        return False


def add_credits(
    user_id,
    amount,
    reason="Admin"
):

    conn = db()

    conn.execute("""
        UPDATE users
        SET credits=credits+?
        WHERE user_id=?
    """, (
        amount,
        user_id
    ))

    conn.execute("""
        INSERT INTO credit_history
        (
            user_id,
            amount,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        amount,
        reason,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def remove_credits(
    user_id,
    amount,
    reason="Tool"
):

    conn = db()

    conn.execute("""
        UPDATE users
        SET credits=MAX(0, credits-?)
        WHERE user_id=?
    """, (
        amount,
        user_id
    ))

    conn.execute("""
        INSERT INTO credit_history
        (
            user_id,
            amount,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        -amount,
        reason,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def add_xp(user_id, amount=1):

    row = get_user(user_id)

    if not row:
        return

    xp = row["xp"] + amount

    level = max(
        1,
        xp // 50 + 1
    )

    conn = db()

    conn.execute("""
        UPDATE users
        SET xp=?,
            level=?
        WHERE user_id=?
    """, (
        xp,
        level,
        user_id
    ))

    conn.execute("""
        INSERT OR REPLACE INTO user_levels
        (
            user_id,
            xp,
            level
        )
        VALUES (?, ?, ?)
    """, (
        user_id,
        xp,
        level
    ))

    conn.commit()
    conn.close()


def update_streak(user_id):

    row = get_user(user_id)

    if not row:
        return 1

    today = date.today().isoformat()

    if row["last_streak"] == today:
        return row["streak"]

    yesterday = (
        date.today()
        - timedelta(days=1)
    ).isoformat()

    if row["last_streak"] == yesterday:
        streak = row["streak"] + 1
    else:
        streak = 1

    conn = db()

    conn.execute("""
        UPDATE users
        SET streak=?,
            last_streak=?
        WHERE user_id=?
    """, (
        streak,
        today,
        user_id
    ))

    conn.commit()
    conn.close()

    add_xp(
        user_id,
        5
    )

    return streak


def log_history(
    user_id,
    tool,
    status,
    cost=0
):

    conn = db()

    conn.execute("""
        INSERT INTO history
        (
            user_id,
            tool,
            status,
            cost,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        tool,
        status,
        cost,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


# =========================================================
# KEYBOARD
# =========================================================

MAIN_KEYBOARD = [
    ["📕 PDF Tools", "🖼️ Image Tools"],
    ["💎 Premium", "👤 My Account"],
    ["🎁 Daily Bonus", "👥 Refer & Earn"],
    ["🎟️ Redeem Code", "📜 History"],
    ["🆘 Support", "⚙️ Settings"],
]

MAIN_MARKUP = ReplyKeyboardMarkup(
    MAIN_KEYBOARD,
    resize_keyboard=True
)


# =========================================================
# TOOL COST
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

    "Rotate PDF": 2,
    "PDF Page Size": 2,
    "Add Page Numbers": 2,
    "Add Watermark": 2,
    "Remove Metadata": 1,
    "PDF Info": 1,

    "Compress Image": 1,
    "Convert PNG": 1,
    "Resize Image": 1,
    "JPG ↔ PNG": 1,
    "Custom Resize": 1,
    "Image → WebP": 1,
    "Multiple Images → PDF": 2,
}


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    ensure_user(user)

    if is_banned(user.id):

        await update.message.reply_text(
            "🚫 Your account is currently blocked."
        )

        return

    args = context.args

    if args:

        ref = args[0]

        if ref.startswith("RAFIM"):

            try:

                ref_id = int(
                    ref.replace(
                        "RAFIM",
                        ""
                    )
                )

                if ref_id != user.id:

                    row = get_user(user.id)

                    if (
                        row
                        and row["referred_by"] is None
                    ):

                        ref_user = get_user(
                            ref_id
                        )

                        if ref_user:

                            conn = db()

                            conn.execute("""
                                UPDATE users
                                SET referred_by=?
                                WHERE user_id=?
                            """, (
                                ref_id,
                                user.id
                            ))

                            conn.execute("""
                                UPDATE users
                                SET referral_count=
                                    referral_count+1
                                WHERE user_id=?
                            """, (
                                ref_id,
                            ))

                            conn.commit()
                            conn.close()

                            add_credits(
                                ref_id,
                                2,
                                "Referral Bonus"
                            )

            except Exception:
                pass

    await update.message.reply_text(
        "👋 Welcome to *Rafim PDF Pro*!\n\n"
        "📄 PDF tools\n"
        "🖼️ Image tools\n"
        "💎 Premium\n"
        "🎁 Daily bonus\n"
        "👥 Referral system\n"
        "🎟️ Redeem codes\n"
        "📜 History\n\n"
        "Choose an option below.",
        parse_mode="Markdown",
        reply_markup=MAIN_MARKUP
    )


async def menu(
    update,
    context
):

    await start(
        update,
        context
    )


# =========================================================
# PDF MENU
# =========================================================

async def pdf_menu(
    update,
    context
):

    keyboard = [

        [
            InlineKeyboardButton(
                "📄 PDF → Word",
                callback_data="pdf_word"
            ),
            InlineKeyboardButton(
                "📝 PDF → TXT",
                callback_data="pdf_txt"
            )
        ],

        [
            InlineKeyboardButton(
                "🖼️ PDF → JPG",
                callback_data="pdf_jpg"
            ),
            InlineKeyboardButton(
                "🖼️ PDF → PNG",
                callback_data="pdf_png"
            )
        ],

        [
            InlineKeyboardButton(
                "🗜️ Compress PDF",
                callback_data="pdf_compress"
            ),
            InlineKeyboardButton(
                "🔗 Merge PDF",
                callback_data="pdf_merge"
            )
        ],

        [
            InlineKeyboardButton(
                "✂️ Split PDF",
                callback_data="pdf_split"
            ),
            InlineKeyboardButton(
                "📑 Extract Pages",
                callback_data="pdf_extract"
            )
        ],

        [
            InlineKeyboardButton(
                "📦 PDF → XPS",
                callback_data="pdf_xps"
            ),
            InlineKeyboardButton(
                "🔐 Protect PDF",
                callback_data="pdf_protect"
            )
        ],

        [
            InlineKeyboardButton(
                "🔓 Unlock PDF",
                callback_data="pdf_unlock"
            ),
            InlineKeyboardButton(
                "📸 Images → PDF",
                callback_data="pdf_from_images"
            )
        ],

        [
            InlineKeyboardButton(
                "🔄 Rotate PDF",
                callback_data="pdf_rotate"
            ),
            InlineKeyboardButton(
                "📐 Page Size",
                callback_data="pdf_pagesize"
            )
        ],

        [
            InlineKeyboardButton(
                "🔢 Page Numbers",
                callback_data="pdf_numbers"
            ),
            InlineKeyboardButton(
                "💧 Watermark",
                callback_data="pdf_watermark"
            )
        ],

        [
            InlineKeyboardButton(
                "🧹 Remove Metadata",
                callback_data="pdf_metadata"
            ),
            InlineKeyboardButton(
                "ℹ️ PDF Info",
                callback_data="pdf_info"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="main_menu"
            )
        ]
    ]

    await update.message.reply_text(
        "📕 *PDF Tools*\n\n"
        "Choose a tool:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# IMAGE MENU
# =========================================================

async def image_menu(
    update,
    context
):

    keyboard = [

        [
            InlineKeyboardButton(
                "🗜️ Compress Image",
                callback_data="img_compress"
            ),
            InlineKeyboardButton(
                "PNG",
                callback_data="img_png"
            )
        ],

        [
            InlineKeyboardButton(
                "📐 Resize",
                callback_data="img_resize"
            ),
            InlineKeyboardButton(
                "JPG ↔ PNG",
                callback_data="img_convert"
            )
        ],

        [
            InlineKeyboardButton(
                "📏 Custom Resize",
                callback_data="img_custom"
            ),
            InlineKeyboardButton(
                "🌐 WebP",
                callback_data="img_webp"
            )
        ],

        [
            InlineKeyboardButton(
                "📚 Multiple → PDF",
                callback_data="img_multi_pdf"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="main_menu"
            )
        ]
    ]

    await update.message.reply_text(
        "🖼️ *Image Tools*\n\n"
        "Choose a tool:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# PREMIUM
# =========================================================

async def premium_menu(
    update,
    context
):

    keyboard = [

        [
            InlineKeyboardButton(
                "⭐ Weekly — ৳50",
                callback_data="premium_weekly"
            )
        ],

        [
            InlineKeyboardButton(
                "💎 Monthly — ৳150",
                callback_data="premium_monthly"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="main_menu"
            )
        ]
    ]

    await update.message.reply_text(
        "💎 *Premium Plans*\n\n"
        "⭐ Premium benefits:\n"
        "• Larger file limit\n"
        "• More credits\n"
        "• Batch processing\n"
        "• Priority processing\n"
        "• Ad-free experience\n"
        "• Premium badge\n\n"
        "Choose a plan:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


async def premium_command(
    update,
    context
):

    await premium_menu(
        update,
        context
    )


# =========================================================
# ACCOUNT
# =========================================================

async def account(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)

    row = get_user(user.id)

    premium_text = (
        "💎 Premium"
        if is_premium(user.id)
        else "🆓 Free"
    )

    await update.message.reply_text(
        "👤 *My Account*\n\n"
        f"🆔 User ID: `{user.id}`\n"
        f"💰 Credits: *{row['credits']}*\n"
        f"🏷️ Plan: *{premium_text}*\n"
        f"⭐ Level: *{row['level']}*\n"
        f"✨ XP: *{row['xp']}*\n"
        f"🔥 Streak: *{row['streak']} days*\n"
        f"👥 Referrals: *{row['referral_count']}*",
        parse_mode="Markdown"
    )


async def account_command(
    update,
    context
):

    await account(
        update,
        context
    )


# =========================================================
# DAILY BONUS
# =========================================================

async def daily_bonus(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)

    row = get_user(user.id)

    today = date.today().isoformat()

    if row["last_bonus"] == today:

        await update.message.reply_text(
            "🎁 Today's bonus has already been claimed.\n"
            "Come back tomorrow!"
        )

        return

    streak = update_streak(
        user.id
    )

    bonus = DAILY_BONUS

    if streak >= 7:
        bonus += 2

    add_credits(
        user.id,
        bonus,
        "Daily Bonus"
    )

    conn = db()

    conn.execute("""
        UPDATE users
        SET last_bonus=?
        WHERE user_id=?
    """, (
        today,
        user.id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎁 *Daily Bonus Claimed!*\n\n"
        f"💰 +{bonus} credits\n"
        f"🔥 Streak: {streak} days",
        parse_mode="Markdown"
    )


async def bonus_command(
    update,
    context
):

    await daily_bonus(
        update,
        context
    )


# =========================================================
# REFERRAL
# =========================================================

async def refer(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)

    me = await context.bot.get_me()

    link = (
        f"https://t.me/"
        f"{me.username}"
        f"?start=RAFIM{user.id}"
    )

    row = get_user(user.id)

    await update.message.reply_text(
        "👥 *Refer & Earn*\n\n"
        f"🔗 Your invite link:\n{link}\n\n"
        "🎁 Referral reward: 2 credits\n"
        f"👥 Total referrals: "
        f"{row['referral_count']}\n\n"
        "Share your link with friends.",
        parse_mode="Markdown"
    )


async def referral_leaderboard(
    update,
    context
):

    conn = db()

    rows = conn.execute("""
        SELECT first_name,
               username,
               referral_count
        FROM users
        ORDER BY referral_count DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    text = (
        "🏆 *Referral Leaderboard*\n\n"
    )

    for i, row in enumerate(
        rows,
        1
    ):

        name = (
            row["first_name"]
            or row["username"]
            or "User"
        )

        text += (
            f"{i}. {name} — "
            f"{row['referral_count']} referrals\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def refer_command(
    update,
    context
):

    await refer(
        update,
        context
    )


# =========================================================
# REDEEM
# =========================================================

async def redeem(
    update,
    context
):

    if not context.args:

        await update.message.reply_text(
            "🎟️ Use:\n/redeem CODE"
        )

        return

    code = context.args[0].upper()

    user = update.effective_user

    ensure_user(user)

    conn = db()

    code_row = conn.execute("""
        SELECT *
        FROM redeem_codes
        WHERE code=?
    """, (
        code,
    )).fetchone()

    if not code_row:

        conn.close()

        await update.message.reply_text(
            "❌ Invalid redeem code."
        )

        return

    if not code_row["active"]:

        conn.close()

        await update.message.reply_text(
            "❌ This code is disabled."
        )

        return

    if (
        code_row["used_count"]
        >= code_row["max_uses"]
    ):

        conn.close()

        await update.message.reply_text(
            "❌ This code has reached its usage limit."
        )

        return

    already = conn.execute("""
        SELECT id
        FROM redemptions
        WHERE user_id=? AND code=?
    """, (
        user.id,
        code
    )).fetchone()

    if already:

        conn.close()

        await update.message.reply_text(
            "⚠️ You have already used this code."
        )

        return

    conn.execute("""
        INSERT INTO redemptions
        (
            user_id,
            code,
            redeemed_at
        )
        VALUES (?, ?, ?)
    """, (
        user.id,
        code,
        datetime.now().isoformat()
    ))

    conn.execute("""
        UPDATE redeem_codes
        SET used_count=used_count+1
        WHERE code=?
    """, (
        code,
    ))

    conn.commit()
    conn.close()

    add_credits(
        user.id,
        code_row["credits"],
        f"Redeem: {code}"
    )

    await update.message.reply_text(
        f"🎉 Code redeemed successfully!\n\n"
        f"💰 +{code_row['credits']} credits"
    )


async def redeem_button(
    update,
    context
):

    await update.message.reply_text(
        "🎟️ Send your redeem code like this:\n\n"
        "`/redeem RAFIM20`",
        parse_mode="Markdown"
    )


# =========================================================
# HISTORY
# =========================================================

async def history(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)

    conn = db()

    rows = conn.execute("""
        SELECT tool,
               status,
               cost,
               created_at
        FROM history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 20
    """, (
        user.id,
    )).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "📜 No history yet."
        )

        return

    text = (
        "📜 *Recent History*\n\n"
    )

    for row in rows:

        text += (
            f"• {row['tool']}\n"
            f"  Status: {row['status']}\n"
            f"  Cost: {row['cost']}\n"
            f"  {row['created_at'][:19]}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def credit_history_cmd(
    update,
    context
):

    user = update.effective_user

    conn = db()

    rows = conn.execute("""
        SELECT amount,
               reason,
               created_at
        FROM credit_history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 20
    """, (
        user.id,
    )).fetchall()

    conn.close()

    text = (
        "💳 *Credit History*\n\n"
    )

    if not rows:

        text += "No credit history."

    else:

        for row in rows:

            sign = (
                "+"
                if row["amount"] > 0
                else ""
            )

            text += (
                f"{sign}{row['amount']} — "
                f"{row['reason']}\n"
            )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


# =========================================================
# SUPPORT
# =========================================================

async def support(
    update,
    context
):

    await update.message.reply_text(
        "🆘 *Support*\n\n"
        f"👨‍💻 Direct support: @{SUPPORT_USERNAME}\n\n"
        "Or send your problem here and it will be "
        "created as a support ticket.",
        parse_mode="Markdown"
    )

    context.user_data[
        "support_waiting"
    ] = True


async def support_message(
    update,
    context
):

    if not context.user_data.get(
        "support_waiting"
    ):
        return False

    if not update.message:
        return False

    if update.effective_user.id == ADMIN_ID:
        return False

    msg = (
        update.message.text
        or update.message.caption
        or "Media message"
    )

    conn = db()

    cur = conn.execute("""
        INSERT INTO support_tickets
        (
            user_id,
            message,
            status,
            created_at
        )
        VALUES (?, ?, 'open', ?)
    """, (
        update.effective_user.id,
        msg,
        datetime.now().isoformat()
    ))

    ticket_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data[
        "support_waiting"
    ] = False

    await update.message.reply_text(
        f"🎫 Support ticket #{ticket_id} created.\n"
        "Our support team will check it."
    )

    try:

        await context.bot.send_message(
            ADMIN_ID,
            "🆘 *New Support Ticket*\n\n"
            f"🎫 Ticket: #{ticket_id}\n"
            f"👤 User: "
            f"{update.effective_user.id}\n"
            f"💬 Message:\n{msg}",
            parse_mode="Markdown"
        )

    except Exception:
        pass

    return True


# =========================================================
# SETTINGS
# =========================================================

async def settings(
    update,
    context
):

    keyboard = [

        [
            InlineKeyboardButton(
                "🇧🇩 বাংলা",
                callback_data="lang_bn"
            ),
            InlineKeyboardButton(
                "🇺🇸 English",
                callback_data="lang_en"
            )
        ],

        [
            InlineKeyboardButton(
                "🔔 Notifications ON/OFF",
                callback_data="toggle_notifications"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="main_menu"
            )
        ]
    ]

    await update.message.reply_text(
        "⚙️ *Settings*\n\n"
        "Choose your settings:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# HELP / ABOUT / STATUS
# =========================================================

async def help_command(
    update,
    context
):

    await update.message.reply_text(
        "📚 *Rafim PDF Pro Help*\n\n"
        "/start — Start bot\n"
        "/menu — Main menu\n"
        "/premium — Premium plans\n"
        "/account — Account\n"
        "/bonus — Daily bonus\n"
        "/refer — Referral\n"
        "/redeem CODE — Redeem\n"
        "/history — History\n"
        "/help — Help\n"
        "/about — About\n"
        "/status — Bot status\n\n"
        "For support use 🆘 Support.",
        parse_mode="Markdown"
    )


async def about_command(
    update,
    context
):

    await update.message.reply_text(
        "🤖 *Rafim PDF Pro*\n\n"
        "A multi-purpose PDF and image processing bot.\n\n"
        "📕 PDF Tools\n"
        "🖼️ Image Tools\n"
        "💎 Premium\n"
        "🎁 Rewards\n"
        "👥 Referral system\n\n"
        "Powered by Rafim PDF Pro.",
        parse_mode="Markdown"
    )


async def status_command(
    update,
    context
):

    await update.message.reply_text(
        "🟢 *Bot Status*\n\n"
        "Status: Online\n"
        "PDF engine: Ready\n"
        "Image engine: Ready\n"
        "Database: Ready",
        parse_mode="Markdown"
    )


# =========================================================
# PREMIUM REQUEST
# =========================================================

async def premium_plan(
    update,
    context,
    plan,
    amount
):

    user = update.effective_user

    context.user_data[
        "premium_plan"
    ] = plan

    context.user_data[
        "premium_amount"
    ] = amount

    context.user_data[
        "premium_waiting"
    ] = True

    await update.callback_query.answer()

    await update.callback_query.message.reply_text(
        f"💎 *{plan} Premium*\n\n"
        f"💰 Price: ৳{amount}\n\n"
        "Send your transaction ID now.\n\n"
        "Example:\n"
        "`TXN123456789`",
        parse_mode="Markdown"
    )


async def submit_premium_request(
    update,
    context
):

    if not context.user_data.get(
        "premium_waiting"
    ):
        return False

    txn = (
        update.message.text or ""
    ).strip()

    if not txn:
        return False

    user = update.effective_user

    plan = context.user_data.get(
        "premium_plan",
        "Unknown"
    )

    amount = context.user_data.get(
        "premium_amount",
        0
    )

    request_id = (
        uuid.uuid4()
        .hex[:10]
        .upper()
    )

    conn = db()

    cur = conn.execute("""
        INSERT INTO premium_requests
        (
            user_id,
            username,
            plan,
            amount,
            txn_id,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    """, (
        user.id,
        user.username or "",
        plan,
        amount,
        txn,
        datetime.now().isoformat()
    ))

    db_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data[
        "premium_waiting"
    ] = False

    await update.message.reply_text(
        "✅ Premium request submitted!\n\n"
        f"🆔 Request ID: `{request_id}`\n"
        "⏳ Status: Pending admin approval.",
        parse_mode="Markdown"
    )

    keyboard = [

        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=(
                    f"approve_premium_{db_id}"
                )
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=(
                    f"reject_premium_{db_id}"
                )
            )
        ]
    ]

    await context.bot.send_message(
        ADMIN_ID,
        "💎 *New Premium Request*\n\n"
        f"🆔 Request: `{request_id}`\n"
        f"👤 User: `{user.id}`\n"
        f"Username: @{user.username or 'N/A'}\n"
        f"📦 Plan: {plan}\n"
        f"💰 Amount: ৳{amount}\n"
        f"🧾 Transaction ID: `{txn}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )

    return True


async def activate_premium(
    user_id,
    plan
):

    if plan.lower() == "weekly":

        until = (
            datetime.now()
            + timedelta(days=7)
        )

    else:

        until = (
            datetime.now()
            + timedelta(days=30)
        )

    conn = db()

    conn.execute("""
        UPDATE users
        SET premium=1,
            premium_until=?
        WHERE user_id=?
    """, (
        until.isoformat(),
        user_id
    ))

    conn.commit()
    conn.close()

    add_credits(
        user_id,
        (
            20
            if plan.lower() == "weekly"
            else 60
        ),
        "Premium Bonus"
    )


# =========================================================
# ADMIN
# =========================================================

def admin_only(update):

    return (
        update.effective_user.id
        == ADMIN_ID
    )


async def admin_dashboard(
    update,
    context
):

    if not admin_only(update):
        return

    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    premium = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE premium=1"
    ).fetchone()["c"]

    banned = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE banned=1"
    ).fetchone()["c"]

    credits = conn.execute(
        "SELECT COALESCE(SUM(credits),0) c FROM users"
    ).fetchone()["c"]

    requests = conn.execute(
        "SELECT COUNT(*) c FROM premium_requests "
        "WHERE status='pending'"
    ).fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        "👑 *Admin Dashboard*\n\n"
        f"👥 Total Users: {total}\n"
        f"💎 Premium Users: {premium}\n"
        f"🚫 Banned Users: {banned}\n"
        f"💰 Total Credits: {credits}\n"
        f"⏳ Pending Premium: {requests}\n\n"
        "📢 /broadcast\n"
        "💎 /broadcastpremium\n"
        "🆓 /broadcastfree\n"
        "❌ /cancelbroadcast\n\n"
        "🎟️ /createcode CODE CREDITS USES\n"
        "📋 /codes\n"
        "🚫 /disablecode CODE\n"
        "💰 /addcredits USER_ID AMOUNT\n"
        "💎 /addpremium USER_ID DAYS\n"
        "📊 /stats\n"
        "🚷 /ban USER_ID\n"
        "✅ /unban USER_ID",
        parse_mode="Markdown"
    )


async def createcode(
    update,
    context
):

    if not admin_only(update):
        return

    if len(context.args) < 3:

        await update.message.reply_text(
            "Use:\n/createcode CODE CREDITS USES"
        )

        return

    code = context.args[0].upper()

    try:

        credits = int(
            context.args[1]
        )

        uses = int(
            context.args[2]
        )

    except Exception:

        await update.message.reply_text(
            "Credits and uses must be numbers."
        )

        return

    conn = db()

    try:

        conn.execute("""
            INSERT INTO redeem_codes
            (
                code,
                credits,
                max_uses,
                created_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            code,
            credits,
            uses,
            datetime.now().isoformat()
        ))

        conn.commit()

        await update.message.reply_text(
            f"✅ Code created:\n"
            f"{code}\n"
            f"Credits: {credits}\n"
            f"Uses: {uses}"
        )

    except sqlite3.IntegrityError:

        await update.message.reply_text(
            "❌ Code already exists."
        )

    finally:

        conn.close()


async def codes(
    update,
    context
):

    if not admin_only(update):
        return

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM redeem_codes
        ORDER BY created_at DESC
    """).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "No redeem codes."
        )

        return

    text = (
        "🎟️ *Redeem Codes*\n\n"
    )

    for row in rows:

        status = (
            "ON"
            if row["active"]
            else "OFF"
        )

        text += (
            f"`{row['code']}`\n"
            f"Credits: {row['credits']}\n"
            f"Used: "
            f"{row['used_count']}/"
            f"{row['max_uses']}\n"
            f"Status: {status}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def disablecode(
    update,
    context
):

    if not admin_only(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Use:\n/disablecode CODE"
        )

        return

    code = context.args[0].upper()

    conn = db()

    conn.execute("""
        UPDATE redeem_codes
        SET active=0
        WHERE code=?
    """, (
        code,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🚫 Code disabled: {code}"
    )


async def addcredits_admin(
    update,
    context
):

    if not admin_only(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "/addcredits USER_ID AMOUNT"
        )

        return

    try:

        uid = int(
            context.args[0]
        )

        amount = int(
            context.args[1]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid numbers."
        )

        return

    add_credits(
        uid,
        amount,
        "Admin Credit"
    )

    await update.message.reply_text(
        f"✅ Added {amount} credits to {uid}."
    )


async def addpremium_admin(
    update,
    context
):

    if not admin_only(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "/addpremium USER_ID DAYS"
        )

        return

    try:

        uid = int(
            context.args[0]
        )

        days = int(
            context.args[1]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid numbers."
        )

        return

    until = (
        datetime.now()
        + timedelta(days=days)
    )

    conn = db()

    conn.execute("""
        UPDATE users
        SET premium=1,
            premium_until=?
        WHERE user_id=?
    """, (
        until.isoformat(),
        uid
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"💎 Premium activated for {uid}\n"
        f"Days: {days}"
    )


async def stats(
    update,
    context
):

    if not admin_only(update):
        return

    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    today = date.today().isoformat()

    today_users = conn.execute("""
        SELECT COUNT(*) c
        FROM users
        WHERE substr(joined_at,1,10)=?
    """, (
        today,
    )).fetchone()["c"]

    today_tools = conn.execute("""
        SELECT COUNT(*) c
        FROM history
        WHERE substr(created_at,1,10)=?
    """, (
        today,
    )).fetchone()["c"]

    sent = conn.execute("""
        SELECT COALESCE(SUM(sent),0) c
        FROM broadcast_jobs
    """).fetchone()["c"]

    failed = conn.execute("""
        SELECT COALESCE(SUM(failed),0) c
        FROM broadcast_jobs
    """).fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        "📊 *Statistics*\n\n"
        f"👥 Total users: {total}\n"
        f"🆕 Today joined: {today_users}\n"
        f"🛠️ Today's tools: {today_tools}\n"
        f"📢 Broadcast sent: {sent}\n"
        f"❌ Broadcast failed: {failed}",
        parse_mode="Markdown"
    )


async def ban_user(
    update,
    context
):

    if not admin_only(update):
        return

    if not context.args:

        await update.message.reply_text(
            "/ban USER_ID"
        )

        return

    uid = int(
        context.args[0]
    )

    conn = db()

    conn.execute(
        "UPDATE users SET banned=1 WHERE user_id=?",
        (uid,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🚫 User {uid} banned."
    )


async def unban_user(
    update,
    context
):

    if not admin_only(update):
        return

    if not context.args:

        await update.message.reply_text(
            "/unban USER_ID"
        )

        return

    uid = int(
        context.args[0]
    )

    conn = db()

    conn.execute(
        "UPDATE users SET banned=0 WHERE user_id=?",
        (uid,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ User {uid} unbanned."
    )


# =========================================================
# BROADCAST SYSTEM
# =========================================================

async def broadcast_start(
    update,
    context
):

    if not admin_only(update):
        return

    conn = db()

    running = conn.execute("""
        SELECT id
        FROM broadcast_jobs
        WHERE status IN ('waiting','running')
        LIMIT 1
    """).fetchone()

    conn.close()

    if running:

        await update.message.reply_text(
            "⚠️ A broadcast is already running."
        )

        return

    context.bot_data[
        "broadcast_waiting"
    ] = True

    context.bot_data[
        "broadcast_target"
    ] = "all"

    await update.message.reply_text(
        "📢 *Broadcast Mode*\n\n"
        "Send the message you want to broadcast.\n\n"
        "Text, photo, video, document and other Telegram messages are supported.\n\n"
        "Use /cancelbroadcast to cancel.",
        parse_mode="Markdown"
    )


async def broadcast_premium(
    update,
    context
):

    if not admin_only(update):
        return

    context.bot_data[
        "broadcast_waiting"
    ] = True

    context.bot_data[
        "broadcast_target"
    ] = "premium"

    await update.message.reply_text(
        "💎 Send the message for PREMIUM users.\n\n"
        "Use /cancelbroadcast to cancel."
    )


async def broadcast_free(
    update,
    context
):

    if not admin_only(update):
        return

    context.bot_data[
        "broadcast_waiting"
    ] = True

    context.bot_data[
        "broadcast_target"
    ] = "free"

    await update.message.reply_text(
        "🆓 Send the message for FREE users.\n\n"
        "Use /cancelbroadcast to cancel."
    )


async def cancel_broadcast(
    update,
    context
):

    if not admin_only(update):
        return

    context.bot_data[
        "broadcast_waiting"
    ] = False

    conn = db()

    conn.execute("""
        UPDATE broadcast_jobs
        SET status='cancelled',
            finished_at=?
        WHERE status IN ('waiting','running')
    """, (
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "❌ Broadcast cancelled."
    )


async def broadcast_content_handler(
    update,
    context
):

    if not admin_only(update):
        return False

    if not context.bot_data.get(
        "broadcast_waiting"
    ):
        return False

    if not update.message:
        return False

    if (
        update.message.text
        and update.message.text.startswith("/")
    ):
        return False

    target = context.bot_data.get(
        "broadcast_target",
        "all"
    )

    context.bot_data[
        "broadcast_waiting"
    ] = False

    conn = db()

    cur = conn.execute("""
        INSERT INTO broadcast_jobs
        (
            admin_id,
            target,
            status,
            message_id,
            created_at
        )
        VALUES (?, ?, 'running', ?, ?)
    """, (
        ADMIN_ID,
        target,
        update.message.message_id,
        datetime.now().isoformat()
    ))

    job_id = cur.lastrowid

    conn.commit()
    conn.close()

    conn = db()

    if target == "premium":

        rows = conn.execute("""
            SELECT user_id
            FROM users
            WHERE premium=1
              AND banned=0
        """).fetchall()

    elif target == "free":

        rows = conn.execute("""
            SELECT user_id
            FROM users
            WHERE premium=0
              AND banned=0
        """).fetchall()

    else:

        rows = conn.execute("""
            SELECT user_id
            FROM users
            WHERE banned=0
        """).fetchall()

    conn.close()

    total = len(rows)

    conn = db()

    conn.execute("""
        UPDATE broadcast_jobs
        SET total=?
        WHERE id=?
    """, (
        total,
        job_id
    ))

    conn.commit()
    conn.close()

    sent = 0
    failed = 0

    status_message = (
        await update.message.reply_text(
            f"📢 Broadcast started.\n\n"
            f"🎯 Target: {target}\n"
            f"👥 Total: {total}\n"
            f"✅ Sent: 0\n"
            f"❌ Failed: 0"
        )
    )

    for index, row in enumerate(
        rows,
        1
    ):

        conn = db()

        job = conn.execute("""
            SELECT status
            FROM broadcast_jobs
            WHERE id=?
        """, (
            job_id,
        )).fetchone()

        conn.close()

        if (
            not job
            or job["status"] == "cancelled"
        ):
            break

        uid = row["user_id"]

        try:

            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )

            sent += 1

        except Exception:

            failed += 1

        if (
            index % 10 == 0
            or index == total
        ):

            conn = db()

            conn.execute("""
                UPDATE broadcast_jobs
                SET sent=?,
                    failed=?
                WHERE id=?
            """, (
                sent,
                failed,
                job_id
            ))

            conn.commit()
            conn.close()

            try:

                await status_message.edit_text(
                    f"📢 Broadcast running...\n\n"
                    f"🎯 Target: {target}\n"
                    f"📊 Progress: "
                    f"{index}/{total}\n"
                    f"✅ Sent: {sent}\n"
                    f"❌ Failed: {failed}"
                )

            except Exception:
                pass

        await asyncio.sleep(
            0.05
        )

    conn = db()

    job = conn.execute("""
        SELECT status
        FROM broadcast_jobs
        WHERE id=?
    """, (
        job_id,
    )).fetchone()

    final_status = (
        "cancelled"
        if (
            job
            and job["status"] == "cancelled"
        )
        else "completed"
    )

    conn.execute("""
        UPDATE broadcast_jobs
        SET status=?,
            sent=?,
            failed=?,
            finished_at=?
        WHERE id=?
    """, (
        final_status,
        sent,
        failed,
        datetime.now().isoformat(),
        job_id
    ))

    conn.commit()
    conn.close()

    try:

        await status_message.edit_text(
            f"📢 *Broadcast Finished*\n\n"
            f"🎯 Target: {target}\n"
            f"👥 Total: {total}\n"
            f"✅ Sent: {sent}\n"
            f"❌ Failed: {failed}\n"
            f"📌 Status: {final_status}",
            parse_mode="Markdown"
        )

    except Exception:
        pass

    return True


# =========================================================
# PROFESSIONAL LOADING SYSTEM
# =========================================================

PROGRESS_DATA = {

    10: (
        "📥",
        "ফাইল গ্রহণ করা হচ্ছে...",
        "আপনার ফাইলটি নিরাপদে নেওয়া হয়েছে।"
    ),

    20: (
        "🔍",
        "ফাইল বিশ্লেষণ করা হচ্ছে...",
        "ডকুমেন্টের গঠন পরীক্ষা চলছে।"
    ),

    30: (
        "📑",
        "পেজ প্রস্তুত করা হচ্ছে...",
        "প্রয়োজনীয় পেজ ও ডেটা প্রস্তুত করা হচ্ছে।"
    ),

    40: (
        "⚙️",
        "প্রসেসিং শুরু হয়েছে...",
        "মূল কাজ এখন চলছে।"
    ),

    50: (
        "📊",
        "ডকুমেন্ট প্রসেস করা হচ্ছে...",
        "ডেটা রূপান্তরের কাজ চলছে।"
    ),

    60: (
        "🛠️",
        "ফাইল আরও প্রসেস করা হচ্ছে...",
        "প্রায় অর্ধেকের বেশি কাজ সম্পন্ন।"
    ),

    70: (
        "✨",
        "ফাইল অপ্টিমাইজ করা হচ্ছে...",
        "আউটপুট আরও সুন্দর ও প্রস্তুত করা হচ্ছে।"
    ),

    80: (
        "📦",
        "আউটপুট তৈরি করা হচ্ছে...",
        "ফাইনাল ফাইল প্রস্তুত হচ্ছে।"
    ),

    90: (
        "🚀",
        "ফাইনাল প্রস্তুতি চলছে...",
        "আর মাত্র শেষ ধাপ বাকি।"
    ),

    100: (
        "✅",
        "প্রসেসিং সম্পন্ন!",
        "আপনার ফাইল সফলভাবে প্রস্তুত।"
    ),
}


def make_progress_bar(
    percent
):

    filled = percent // 10

    return (
        "▰" * filled
        + "□" * (10 - filled)
    )


def make_progress_text(
    tool,
    percent
):

    icon, title, subtitle = (
        PROGRESS_DATA.get(
            percent,
            (
                "⚙️",
                "Processing...",
                "Please wait..."
            )
        )
    )

    bar = make_progress_bar(
        percent
    )

    if percent == 100:

        header = (
            "🎉 *Rafim PDF Pro*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏁 *FINAL RESULT READY*"
        )

    else:

        header = (
            "🚀 *Rafim PDF Pro*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ *SMART PROCESSING MODE*"
        )

    return (
        f"{header}\n\n"
        f"📄 *Tool:* `{tool}`\n\n"
        f"🔄 *{percent}%*  `{bar}`\n\n"
        f"{icon} *{title}*\n"
        f"└─ {subtitle}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 *Professional PDF Processing*\n"
        f"🔒 Processing securely...\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


async def update_progress(
    message,
    tool,
    percent
):

    try:

        await message.edit_text(
            make_progress_text(
                tool,
                percent
            ),
            parse_mode="Markdown"
        )

    except Exception:
        pass


async def animate_progress(
    message,
    tool,
    stop_event
):

    steps = [
        30,
        40,
        50,
        60,
        70,
        80,
        90
    ]

    for percent in steps:

        if stop_event.is_set():
            return

        await update_progress(
            message,
            tool,
            percent
        )

        # Small delay so the user can see
        # every stage without flooding Telegram.
        await asyncio.sleep(
            0.65
        )


# =========================================================
# FILE PROCESSING HELPERS
# =========================================================

def get_cost(tool):

    return TOOL_COST.get(
        tool,
        1
    )


def can_use_tool(
    user_id,
    tool
):

    row = get_user(
        user_id
    )

    if not row:
        return False, 0

    cost = get_cost(
        tool
    )

    if row["credits"] < cost:
        return False, cost

    return True, cost


# =========================================================
# PDF PROCESSOR
# =========================================================

async def process_pdf(
    file_path,
    tool,
    output_dir,
    context
):

    doc = fitz.open(
        file_path
    )

    output = None

    if tool == "PDF → Word":

        word = WordDocument()

        for page in doc:

            text = page.get_text()

            if text.strip():
                word.add_paragraph(
                    text
                )

        output = os.path.join(
            output_dir,
            "converted.docx"
        )

        word.save(
            output
        )

    elif tool == "PDF → TXT":

        output = os.path.join(
            output_dir,
            "converted.txt"
        )

        with open(
            output,
            "w",
            encoding="utf-8"
        ) as f:

            for page in doc:

                f.write(
                    page.get_text()
                )

                f.write(
                    "\n\n"
                )

    elif tool in [
        "PDF → JPG",
        "PDF → PNG"
    ]:

        ext = (
            "jpg"
            if tool.endswith("JPG")
            else "png"
        )

        output = os.path.join(
            output_dir,
            f"page_1.{ext}"
        )

        page = doc[0]

        pix = page.get_pixmap(
            matrix=fitz.Matrix(
                2,
                2
            ),
            alpha=False
        )

        pix.save(
            output
        )

    elif tool == "Compress PDF":

        output = os.path.join(
            output_dir,
            "compressed.pdf"
        )

        new_doc = fitz.open()

        for page in doc:

            new_doc.insert_pdf(
                doc,
                from_page=page.number,
                to_page=page.number
            )

        new_doc.save(
            output,
            garbage=4,
            deflate=True,
            clean=True
        )

        new_doc.close()

    elif tool == "Split PDF":

        output = os.path.join(
            output_dir,
            "split.pdf"
        )

        new_doc = fitz.open()

        if len(doc) > 0:

            new_doc.insert_pdf(
                doc,
                from_page=0,
                to_page=0
            )

        new_doc.save(
            output
        )

        new_doc.close()

    elif tool == "Extract Pages":

        output = os.path.join(
            output_dir,
            "extracted.pdf"
        )

        new_doc = fitz.open()

        if len(doc) > 0:

            new_doc.insert_pdf(
                doc,
                from_page=0,
                to_page=0
            )

        new_doc.save(
            output
        )

        new_doc.close()

    elif tool == "Rotate PDF":

        output = os.path.join(
            output_dir,
            "rotated.pdf"
        )

        for page in doc:

            page.set_rotation(
                (
                    page.rotation
                    + 90
                ) % 360
            )

        doc.save(
            output
        )

    elif tool == "PDF Page Size":

        output = os.path.join(
            output_dir,
            "page_size.pdf"
        )

        new_doc = fitz.open()

        for page in doc:

            rect = page.rect

            new_page = new_doc.new_page(
                width=rect.height,
                height=rect.width
            )

            new_page.show_pdf_page(
                new_page.rect,
                doc,
                page.number
            )

        new_doc.save(
            output
        )

        new_doc.close()

    elif tool == "Add Page Numbers":

        output = os.path.join(
            output_dir,
            "numbered.pdf"
        )

        total = len(doc)

        for i, page in enumerate(
            doc,
            1
        ):

            page.insert_text(
                (
                    page.rect.width / 2,
                    page.rect.height - 25
                ),
                f"{i} / {total}",
                fontsize=10
            )

        doc.save(
            output
        )

    elif tool == "Add Watermark":

        output = os.path.join(
            output_dir,
            "watermarked.pdf"
        )

        for page in doc:

            page.insert_textbox(
                page.rect,
                "Rafim PDF Pro",
                fontsize=30,
                rotate=45,
                align=1,
                color=(
                    0.5,
                    0.5,
                    0.5
                ),
                fill_opacity=0.15,
                stroke_opacity=0
            )

        doc.save(
            output
        )

    elif tool == "Remove Metadata":

        output = os.path.join(
            output_dir,
            "clean.pdf"
        )

        doc.set_metadata({})

        doc.save(
            output
        )

    elif tool == "PDF Info":

        info = doc.metadata

        output = os.path.join(
            output_dir,
            "pdf_info.txt"
        )

        with open(
            output,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                json.dumps(
                    info,
                    indent=2,
                    ensure_ascii=False
                )
            )

            f.write(
                f"\n\nPages: "
                f"{len(doc)}\n"
            )

    elif tool == "Protect PDF":

        output = os.path.join(
            output_dir,
            "protected.pdf"
        )

        doc.save(
            output,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="rafim",
            user_pw="123456"
        )

    elif tool == "PDF → XPS":

        output = os.path.join(
            output_dir,
            "output.xps"
        )

        temp_pdf = os.path.join(
            output_dir,
            "temp.pdf"
        )

        doc.save(
            temp_pdf
        )

        proc = (
            await asyncio
            .create_subprocess_exec(
                "gs",
                "-dBATCH",
                "-dNOPAUSE",
                "-sDEVICE=xps2",
                f"-sOutputFile={output}",
                temp_pdf,
                stdout=(
                    asyncio
                    .subprocess
                    .PIPE
                ),
                stderr=(
                    asyncio
                    .subprocess
                    .PIPE
                )
            )
        )

        await proc.communicate()

        if not os.path.exists(output):

            raise RuntimeError(
                "XPS conversion failed."
            )

    else:

        output = os.path.join(
            output_dir,
            "output.pdf"
        )

        doc.save(
            output
        )

    doc.close()

    return output


# =========================================================
# DOCUMENT HANDLER
# =========================================================

async def document_handler(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)

    if is_banned(user.id):
        return

    if await submit_premium_request(
        update,
        context
    ):
        return

    if await support_message(
        update,
        context
    ):
        return

    tool = context.user_data.get(
        "selected_tool"
    )

    if not tool:
        return

    if not update.message.document:
        return

    file_size = (
        update.message.document.file_size
        or 0
    )

    limit = (
        PREMIUM_FILE_LIMIT_MB
        if is_premium(user.id)
        else FREE_FILE_LIMIT_MB
    )

    if file_size > (
        limit * 1024 * 1024
    ):

        await update.message.reply_text(
            f"❌ File too large.\n"
            f"Your limit is {limit} MB."
        )

        return

    ok, cost = can_use_tool(
        user.id,
        tool
    )

    if not ok:

        await update.message.reply_text(
            f"❌ Not enough credits.\n\n"
            f"💰 Required: {cost}\n"
            f"💳 Your credits: "
            f"{get_user(user.id)['credits']}"
        )

        return

    # -----------------------------------------------------
    # PROFESSIONAL SAME-MESSAGE LOADING
    # -----------------------------------------------------

    status = await update.message.reply_text(
        make_progress_text(
            tool,
            10
        ),
        parse_mode="Markdown"
    )

    await asyncio.sleep(
        0.35
    )

    tmp_dir = tempfile.mkdtemp()

    input_path = os.path.join(
        tmp_dir,
        update.message.document.file_name
        or "input.pdf"
    )

    output_dir = tmp_dir

    stop_event = None
    progress_task = None

    try:

        # 20%
        await update_progress(
            status,
            tool,
            20
        )

        tg_file = await context.bot.get_file(
            update.message.document.file_id
        )

        await tg_file.download_to_drive(
            input_path
        )

        await asyncio.sleep(
            0.25
        )

        # 30% starts when actual processing begins
        await update_progress(
            status,
            tool,
            30
        )

        stop_event = asyncio.Event()

        # Animate 30 -> 90 while the real processor works.
        progress_task = asyncio.create_task(
            animate_progress(
                status,
                tool,
                stop_event
            )
        )

        # REAL PROCESSING
        output = await process_pdf(
            input_path,
            tool,
            output_dir,
            context
        )

        # Stop animation after real processing finishes.
        stop_event.set()

        if progress_task:

            try:
                await progress_task
            except Exception:
                pass

        # 100% ONLY AFTER SUCCESSFUL PROCESSING
        await update_progress(
            status,
            tool,
            100
        )

        await asyncio.sleep(
            0.8
        )

        remove_credits(
            user.id,
            cost,
            f"Tool: {tool}"
        )

        add_xp(
            user.id,
            2
        )

        log_history(
            user.id,
            tool,
            "Success",
            cost
        )

        # Final sending message in SAME status message
        try:

            await status.edit_text(
                "🎉 *Rafim PDF Pro*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "✅ *PROCESSING COMPLETE*\n\n"
                f"📄 Tool: `{tool}`\n"
                "🔄 Progress: `100%` "
                "`▰▰▰▰▰▰▰▰▰▰`\n\n"
                "📦 Your file is ready.\n"
                "📤 Sending your file now...\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "✨ Thank you for using Rafim PDF Pro!",
                parse_mode="Markdown"
            )

        except Exception:
            pass

        with open(
            output,
            "rb"
        ) as f:

            await update.message.reply_document(
                document=f,
                filename=os.path.basename(
                    output
                ),
                caption=(
                    f"✅ *{tool} completed!*\n\n"
                    f"💰 Cost: {cost} credits"
                ),
                parse_mode="Markdown"
            )

    except Exception:

        if stop_event:
            stop_event.set()

        if progress_task:

            try:
                await progress_task
            except Exception:
                pass

        log_history(
            user.id,
            tool,
            "Failed",
            0
        )

        try:

            await status.edit_text(
                "⚠️ *Rafim PDF Pro*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "❌ *PROCESSING FAILED*\n\n"
                "Something went wrong while "
                "processing your file.\n\n"
                "💰 *You were NOT charged.*\n"
                "🔁 Please try again.\n\n"
                "━━━━━━━━━━━━━━━━━━━━",
                parse_mode="Markdown"
            )

        except Exception:

            await update.message.reply_text(
                "❌ Processing failed.\n"
                "You were not charged."
            )

    finally:

        try:

            import shutil

            shutil.rmtree(
                tmp_dir
            )

        except Exception:
            pass

        context.user_data.pop(
            "selected_tool",
            None
        )


# =========================================================
# IMAGE PROCESSOR
# =========================================================

async def process_image(
    input_path,
    tool,
    output_dir
):

    img = Image.open(
        input_path
    )

    output = None

    if tool in [
        "Compress Image",
        "Image Compressor"
    ]:

        output = os.path.join(
            output_dir,
            "compressed.jpg"
        )

        if img.mode not in [
            "RGB",
            "L"
        ]:

            img = img.convert(
                "RGB"
            )

        img.save(
            output,
            "JPEG",
            quality=60,
            optimize=True
        )

    elif tool in [
        "Convert PNG",
        "JPG ↔ PNG"
    ]:

        output = os.path.join(
            output_dir,
            "converted.png"
        )

        img.save(
            output,
            "PNG"
        )

    elif tool in [
        "Resize Image",
        "Custom Resize"
    ]:

        max_width = 1280

        ratio = (
            max_width
            / img.width
        )

        if ratio < 1:

            new_size = (
                int(
                    img.width
                    * ratio
                ),
                int(
                    img.height
                    * ratio
                )
            )

            img = img.resize(
                new_size,
                Image.Resampling.LANCZOS
            )

        output = os.path.join(
            output_dir,
            "resized.jpg"
        )

        if img.mode not in [
            "RGB",
            "L"
        ]:

            img = img.convert(
                "RGB"
            )

        img.save(
            output,
            "JPEG",
            quality=90
        )

    elif tool == "Image → WebP":

        output = os.path.join(
            output_dir,
            "converted.webp"
        )

        img.save(
            output,
            "WEBP",
            quality=85
        )

    else:

        output = os.path.join(
            output_dir,
            "image.jpg"
        )

        img.save(
            output
        )

    return output


async def photo_handler(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)

    if is_banned(user.id):
        return

    if await support_message(
        update,
        context
    ):
        return

    tool = context.user_data.get(
        "selected_tool"
    )

    if not tool:
        return

    ok, cost = can_use_tool(
        user.id,
        tool
    )

    if not ok:

        await update.message.reply_text(
            "❌ Not enough credits."
        )

        return

    status = await update.message.reply_text(
        make_progress_text(
            tool,
            10
        ),
        parse_mode="Markdown"
    )

    await asyncio.sleep(
        0.35
    )

    tmp_dir = tempfile.mkdtemp()

    input_path = os.path.join(
        tmp_dir,
        "input.jpg"
    )

    stop_event = None
    progress_task = None

    try:

        await update_progress(
            status,
            tool,
            20
        )

        tg_file = await context.bot.get_file(
            update.message.photo[-1].file_id
        )

        await tg_file.download_to_drive(
            input_path
        )

        await asyncio.sleep(
            0.25
        )

        await update_progress(
            status,
            tool,
            30
        )

        stop_event = asyncio.Event()

        progress_task = asyncio.create_task(
            animate_progress(
                status,
                tool,
                stop_event
            )
        )

        output = await process_image(
            input_path,
            tool,
            tmp_dir
        )

        stop_event.set()

        if progress_task:

            try:
                await progress_task
            except Exception:
                pass

        await update_progress(
            status,
            tool,
            100
        )

        await asyncio.sleep(
            0.8
        )

        remove_credits(
            user.id,
            cost,
            f"Tool: {tool}"
        )

        add_xp(
            user.id,
            2
        )

        log_history(
            user.id,
            tool,
            "Success",
            cost
        )

        try:

            await status.edit_text(
                "🎉 *Rafim PDF Pro*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "✅ *IMAGE PROCESSING COMPLETE*\n\n"
                f"🖼️ Tool: `{tool}`\n"
                "🔄 Progress: `100%` "
                "`▰▰▰▰▰▰▰▰▰▰`\n\n"
                "📦 Your image is ready.\n"
                "📤 Sending it now...\n\n"
                "━━━━━━━━━━━━━━━━━━━━",
                parse_mode="Markdown"
            )

        except Exception:
            pass

        with open(
            output,
            "rb"
        ) as f:

            await update.message.reply_document(
                document=f,
                filename=os.path.basename(
                    output
                ),
                caption=(
                    f"✅ *{tool} completed!*\n\n"
                    f"💰 Cost: {cost}"
                ),
                parse_mode="Markdown"
            )

    except Exception:

        if stop_event:
            stop_event.set()

        if progress_task:

            try:
                await progress_task
            except Exception:
                pass

        log_history(
            user.id,
            tool,
            "Failed",
            0
        )

        try:

            await status.edit_text(
                "⚠️ *Rafim PDF Pro*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "❌ *IMAGE PROCESSING FAILED*\n\n"
                "The image could not be processed.\n\n"
                "💰 *You were NOT charged.*\n"
                "🔁 Please try again.\n\n"
                "━━━━━━━━━━━━━━━━━━━━",
                parse_mode="Markdown"
            )

        except Exception:

            await update.message.reply_text(
                "❌ Image processing failed."
            )

    finally:

        try:

            import shutil

            shutil.rmtree(
                tmp_dir
            )

        except Exception:
            pass

        context.user_data.pop(
            "selected_tool",
            None
        )


# =========================================================
# TEXT PROCESSOR / MENU
# =========================================================

async def text_handler(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)

    if is_banned(user.id):
        return

    if await broadcast_content_handler(
        update,
        context
    ):
        return

    if await support_message(
        update,
        context
    ):
        return

    if await submit_premium_request(
        update,
        context
    ):
        return

    text = (
        update.message.text or ""
    ).strip()

    if text == "📕 PDF Tools":

        await pdf_menu(
            update,
            context
        )

        return

    if text == "🖼️ Image Tools":

        await image_menu(
            update,
            context
        )

        return

    if text == "💎 Premium":

        await premium_menu(
            update,
            context
        )

        return

    if text == "👤 My Account":

        await account(
            update,
            context
        )

        return

    if text == "🎁 Daily Bonus":

        await daily_bonus(
            update,
            context
        )

        return

    if text == "👥 Refer & Earn":

        await refer(
            update,
            context
        )

        return

    if text == "🎟️ Redeem Code":

        await redeem_button(
            update,
            context
        )

        return

    if text == "📜 History":

        await history(
            update,
            context
        )

        return

    if text == "🆘 Support":

        await support(
            update,
            context
        )

        return

    if text == "⚙️ Settings":

        await settings(
            update,
            context
        )

        return

    tool = context.user_data.get(
        "selected_tool"
    )

    if tool:

        if tool in TOOL_COST:

            await update.message.reply_text(
                f"📎 Please send the file for:\n\n"
                f"*{tool}*\n\n"
                f"💰 Cost: "
                f"{TOOL_COST[tool]} credits",
                parse_mode="Markdown"
            )

            return


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    data = query.data

    user = query.from_user

    ensure_user(user)

    if data == "main_menu":

        await query.message.reply_text(
            "🏠 Main Menu",
            reply_markup=MAIN_MARKUP
        )

        return

    if data == "pdf_menu":

        await query.message.reply_text(
            "📕 Open PDF Tools from the main menu."
        )

        return

    if data == "image_menu":

        await query.message.reply_text(
            "🖼️ Open Image Tools from the main menu."
        )

        return

    if data.startswith("pdf_"):

        tool_map = {

            "pdf_word": "PDF → Word",
            "pdf_txt": "PDF → TXT",
            "pdf_jpg": "PDF → JPG",
            "pdf_png": "PDF → PNG",
            "pdf_compress": "Compress PDF",
            "pdf_merge": "Merge PDF",
            "pdf_split": "Split PDF",
            "pdf_extract": "Extract Pages",
            "pdf_xps": "PDF → XPS",
            "pdf_protect": "Protect PDF",
            "pdf_unlock": "Unlock PDF",
            "pdf_from_images": "JPG/PNG → PDF",
            "pdf_rotate": "Rotate PDF",
            "pdf_pagesize": "PDF Page Size",
            "pdf_numbers": "Add Page Numbers",
            "pdf_watermark": "Add Watermark",
            "pdf_metadata": "Remove Metadata",
            "pdf_info": "PDF Info",
        }

        tool = tool_map.get(
            data
        )

        if tool:

            context.user_data[
                "selected_tool"
            ] = tool

            cost = get_cost(
                tool
            )

            await query.message.reply_text(
                f"🛠️ *{tool}*\n\n"
                f"💰 Cost: {cost} credits\n\n"
                "📎 Now send your file.",
                parse_mode="Markdown"
            )

        return

    if data.startswith("img_"):

        tool_map = {

            "img_compress":
                "Compress Image",

            "img_png":
                "Convert PNG",

            "img_resize":
                "Resize Image",

            "img_convert":
                "JPG ↔ PNG",

            "img_custom":
                "Custom Resize",

            "img_webp":
                "Image → WebP",

            "img_multi_pdf":
                "Multiple Images → PDF",
        }

        tool = tool_map.get(
            data
        )

        if tool:

            context.user_data[
                "selected_tool"
            ] = tool

            await query.message.reply_text(
                f"🖼️ *{tool}*\n\n"
                f"💰 Cost: "
                f"{get_cost(tool)} credits\n\n"
                "📎 Send your image.",
                parse_mode="Markdown"
            )

        return

    if data == "premium_weekly":

        await premium_plan(
            update,
            context,
            "Weekly",
            WEEKLY_PRICE
        )

        return

    if data == "premium_monthly":

        await premium_plan(
            update,
            context,
            "Monthly",
            MONTHLY_PRICE
        )

        return

    if data.startswith(
        "approve_premium_"
    ):

        if user.id != ADMIN_ID:
            return

        request_id = int(
            data.replace(
                "approve_premium_",
                ""
            )
        )

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM premium_requests
            WHERE id=?
        """, (
            request_id,
        )).fetchone()

        if not row:

            conn.close()
            return

        if row["status"] != "pending":

            conn.close()

            await query.message.reply_text(
                "⚠️ This request was already processed."
            )

            return

        conn.execute("""
            UPDATE premium_requests
            SET status='approved'
            WHERE id=?
        """, (
            request_id,
        ))

        conn.commit()
        conn.close()

        await activate_premium(
            row["user_id"],
            row["plan"]
        )

        await query.message.edit_text(
            "✅ Premium request approved."
        )

        try:

            await context.bot.send_message(
                row["user_id"],
                "🎉 *Premium Activated!*\n\n"
                f"💎 Plan: {row['plan']}\n"
                "Enjoy your premium benefits!",
                parse_mode="Markdown"
            )

        except Exception:
            pass

        return

    if data.startswith(
        "reject_premium_"
    ):

        if user.id != ADMIN_ID:
            return

        request_id = int(
            data.replace(
                "reject_premium_",
                ""
            )
        )

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM premium_requests
            WHERE id=?
        """, (
            request_id,
        )).fetchone()

        if not row:

            conn.close()
            return

        if row["status"] != "pending":

            conn.close()

            await query.message.reply_text(
                "⚠️ Already processed."
            )

            return

        conn.execute("""
            UPDATE premium_requests
            SET status='rejected'
            WHERE id=?
        """, (
            request_id,
        ))

        conn.commit()
        conn.close()

        await query.message.edit_text(
            "❌ Premium request rejected."
        )

        try:

            await context.bot.send_message(
                row["user_id"],
                "❌ Your premium request was rejected.\n\n"
                "Please contact support if you think this was a mistake."
            )

        except Exception:
            pass

        return

    if data == "lang_bn":

        conn = db()

        conn.execute("""
            UPDATE users
            SET language='bn'
            WHERE user_id=?
        """, (
            user.id,
        ))

        conn.execute("""
            UPDATE user_settings
            SET language='bn'
            WHERE user_id=?
        """, (
            user.id,
        ))

        conn.commit()
        conn.close()

        await query.message.reply_text(
            "🇧🇩 বাংলা ভাষা সেট করা হয়েছে।"
        )

        return

    if data == "lang_en":

        conn = db()

        conn.execute("""
            UPDATE users
            SET language='en'
            WHERE user_id=?
        """, (
            user.id,
        ))

        conn.execute("""
            UPDATE user_settings
            SET language='en'
            WHERE user_id=?
        """, (
            user.id,
        ))

        conn.commit()
        conn.close()

        await query.message.reply_text(
            "🇺🇸 English language selected."
        )

        return

    if data == "toggle_notifications":

        conn = db()

        row = conn.execute("""
            SELECT notifications
            FROM user_settings
            WHERE user_id=?
        """, (
            user.id,
        )).fetchone()

        current = (
            row["notifications"]
            if row
            else 1
        )

        new_value = (
            0
            if current
            else 1
        )

        conn.execute("""
            INSERT OR REPLACE INTO user_settings
            (
                user_id,
                language,
                notifications
            )
            VALUES (
                ?,
                COALESCE(
                    (
                        SELECT language
                        FROM user_settings
                        WHERE user_id=?
                    ),
                    'en'
                ),
                ?
            )
        """, (
            user.id,
            user.id,
            new_value
        ))

        conn.commit()
        conn.close()

        await query.message.reply_text(
            "🔔 Notifications: "
            f"{'ON' if new_value else 'OFF'}"
        )

        return


# =========================================================
# MERGE PDF
# =========================================================

async def merge_pdf_handler(
    update,
    context
):

    if not update.message:
        return

    user = update.effective_user

    if not context.user_data.get(
        "merge_mode"
    ):
        return

    if not update.message.document:
        return

    files = context.user_data.setdefault(
        "merge_files",
        []
    )

    tmp_dir = context.user_data.setdefault(
        "merge_dir",
        tempfile.mkdtemp()
    )

    file_name = (
        update.message.document.file_name
        or f"file_{len(files)+1}.pdf"
    )

    path = os.path.join(
        tmp_dir,
        f"{len(files)+1}_{file_name}"
    )

    tg_file = await context.bot.get_file(
        update.message.document.file_id
    )

    await tg_file.download_to_drive(
        path
    )

    files.append(
        path
    )

    await update.message.reply_text(
        f"📎 Added PDF #{len(files)}.\n\n"
        "Send more PDFs or type:\n"
        "`/done`",
        parse_mode="Markdown"
    )


async def done_merge(
    update,
    context
):

    if not context.user_data.get(
        "merge_mode"
    ):
        return

    user = update.effective_user

    files = context.user_data.get(
        "merge_files",
        []
    )

    if len(files) < 2:

        await update.message.reply_text(
            "❌ Send at least 2 PDF files."
        )

        return

    cost = get_cost(
        "Merge PDF"
    )

    ok, _ = can_use_tool(
        user.id,
        "Merge PDF"
    )

    if not ok:

        await update.message.reply_text(
            "❌ Not enough credits."
        )

        return

    output = os.path.join(
        context.user_data["merge_dir"],
        "merged.pdf"
    )

    try:

        result = fitz.open()

        for path in files:

            doc = fitz.open(
                path
            )

            result.insert_pdf(
                doc
            )

            doc.close()

        result.save(
            output
        )

        result.close()

        remove_credits(
            user.id,
            cost,
            "Tool: Merge PDF"
        )

        add_xp(
            user.id,
            3
        )

        log_history(
            user.id,
            "Merge PDF",
            "Success",
            cost
        )

        with open(
            output,
            "rb"
        ) as f:

            await update.message.reply_document(
                document=f,
                filename="merged.pdf",
                caption=(
                    "✅ *PDFs merged successfully!*\n\n"
                    f"📄 Files: {len(files)}\n"
                    f"💰 Cost: {cost}"
                ),
                parse_mode="Markdown"
            )

    except Exception:

        log_history(
            user.id,
            "Merge PDF",
            "Failed",
            0
        )

        await update.message.reply_text(
            "❌ Merge failed."
        )

    finally:

        try:

            import shutil

            shutil.rmtree(
                context.user_data[
                    "merge_dir"
                ]
            )

        except Exception:
            pass

        context.user_data.pop(
            "merge_mode",
            None
        )

        context.user_data.pop(
            "merge_files",
            None
        )

        context.user_data.pop(
            "merge_dir",
            None
        )


# =========================================================
# BOT COMMAND MENU
# =========================================================

async def setup_commands(
    app
):

    from telegram import BotCommand

    commands = [

        BotCommand(
            "start",
            "Start bot"
        ),

        BotCommand(
            "menu",
            "Main menu"
        ),

        BotCommand(
            "premium",
            "Premium plans"
        ),

        BotCommand(
            "account",
            "My account"
        ),

        BotCommand(
            "bonus",
            "Daily bonus"
        ),

        BotCommand(
            "refer",
            "Refer & Earn"
        ),

        BotCommand(
            "redeem",
            "Redeem code"
        ),

        BotCommand(
            "history",
            "History"
        ),

        BotCommand(
            "help",
            "Help"
        ),

        BotCommand(
            "about",
            "About"
        ),

        BotCommand(
            "status",
            "Bot status"
        ),
    ]

    await app.bot.set_my_commands(
        commands
    )


# =========================================================
# MAIN
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
        .build()
    )

    # -----------------------------------------------------
    # BASIC COMMANDS
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "menu",
            menu
        )
    )

    application.add_handler(
        CommandHandler(
            "premium",
            premium_command
        )
    )

    application.add_handler(
        CommandHandler(
            "account",
            account_command
        )
    )

    application.add_handler(
        CommandHandler(
            "bonus",
            bonus_command
        )
    )

    application.add_handler(
        CommandHandler(
            "refer",
            refer_command
        )
    )

    application.add_handler(
        CommandHandler(
            "redeem",
            redeem
        )
    )

    application.add_handler(
        CommandHandler(
            "history",
            history
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "about",
            about_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    # -----------------------------------------------------
    # ADMIN COMMANDS
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "admin",
            admin_dashboard
        )
    )

    application.add_handler(
        CommandHandler(
            "createcode",
            createcode
        )
    )

    application.add_handler(
        CommandHandler(
            "codes",
            codes
        )
    )

    application.add_handler(
        CommandHandler(
            "disablecode",
            disablecode
        )
    )

    application.add_handler(
        CommandHandler(
            "addcredits",
            addcredits_admin
        )
    )

    application.add_handler(
        CommandHandler(
            "addpremium",
            addpremium_admin
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            ban_user
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            unban_user
        )
    )

    # -----------------------------------------------------
    # BROADCAST COMMANDS
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_start
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcastpremium",
            broadcast_premium
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcastfree",
            broadcast_free
        )
    )

    application.add_handler(
        CommandHandler(
            "cancelbroadcast",
            cancel_broadcast
        )
    )

    # -----------------------------------------------------
    # MERGE / DONE
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "done",
            done_merge
        )
    )

    # -----------------------------------------------------
    # CALLBACKS
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # -----------------------------------------------------
    # BROADCAST MESSAGE HANDLER
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.ALL,
            broadcast_content_handler
        ),
        group=0
    )

    # -----------------------------------------------------
    # MERGE PDF HANDLER
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Document.PDF,
            merge_pdf_handler
        ),
        group=1
    )

    # -----------------------------------------------------
    # NORMAL DOCUMENT HANDLER
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler
        ),
        group=2
    )

    # -----------------------------------------------------
    # PHOTO HANDLER
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler
        ),
        group=2
    )

    # -----------------------------------------------------
    # TEXT HANDLER
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        ),
        group=3
    )

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    async def post_init(
        app
    ):
        await setup_commands(
            app
        )

    application.post_init = post_init

    print(
        "Rafim PDF Pro started."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
