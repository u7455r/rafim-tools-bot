# ============================================================
# RAFIM PDF PRO — ALL-IN-ONE BOT
# Old system preserved + advanced systems added
# ============================================================

import os
import io
import re
import json
import time
import uuid
import shutil
import sqlite3
import asyncio
import threading
import tempfile
import zipfile
import subprocess
from datetime import datetime, date, timedelta

import fitz
from PIL import Image, ImageOps, ImageEnhance
from docx import Document as WordDocument
from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

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

MAX_BATCH_FILES = 20
MAX_HISTORY = 50


# ============================================================
# FLASK / RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Rafim PDF Pro is running!"


@app.route("/health")
def health():
    return "OK"


@app.route("/status")
def web_status():
    return {
        "bot": "Rafim PDF Pro",
        "status": "online",
        "pdf_engine": "ready",
        "image_engine": "ready",
        "database": "ready"
    }


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False,
        timeout=30
    )
    conn.row_factory = sqlite3.Row
    return conn


def add_column_if_missing(table, column, definition):
    conn = db()
    try:
        cols = [
            r["name"]
            for r in conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        ]

        if column not in cols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

        conn.commit()
    finally:
        conn.close()


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
            notifications INTEGER DEFAULT 1,
            quality INTEGER DEFAULT 85,
            compression TEXT DEFAULT 'medium'
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            tool TEXT,
            status TEXT,
            created_at TEXT,
            finished_at TEXT,
            error TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            tool TEXT,
            created_at TEXT,
            UNIQUE(user_id, tool)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            rating INTEGER,
            message TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            body TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usage_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tool TEXT,
            seconds REAL DEFAULT 0,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()

    # Safe migration for databases from the old bot.
    add_column_if_missing(
        "user_settings", "quality", "INTEGER DEFAULT 85"
    )
    add_column_if_missing(
        "user_settings", "compression", "TEXT DEFAULT 'medium'"
    )


# ============================================================
# USER SYSTEM
# ============================================================

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

    uid = user.id
    username = user.username or ""
    first_name = user.first_name or ""

    if not get_user(uid):

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
            uid,
            username,
            first_name,
            FREE_CREDITS,
            datetime.now().isoformat(),
            f"RAFIM{uid}"
        ))

        conn.execute("""
            INSERT OR IGNORE INTO user_settings
            (user_id, language, notifications, quality, compression)
            VALUES (?, 'en', 1, 85, 'medium')
        """, (uid,))

        conn.commit()
        conn.close()

    else:

        conn = db()

        conn.execute("""
            UPDATE users
            SET username=?, first_name=?
            WHERE user_id=?
        """, (
            username,
            first_name,
            uid
        ))

        conn.commit()
        conn.close()


def is_banned(uid):
    row = get_user(uid)
    return bool(row and row["banned"])


def is_premium(uid):

    row = get_user(uid)

    if not row or not row["premium"]:
        return False

    until = row["premium_until"]

    if not until:
        return True

    try:
        return datetime.fromisoformat(until) > datetime.now()
    except Exception:
        return False


def add_credits(uid, amount, reason="Admin"):

    conn = db()

    conn.execute("""
        UPDATE users
        SET credits=credits+?
        WHERE user_id=?
    """, (amount, uid))

    conn.execute("""
        INSERT INTO credit_history
        (user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        uid,
        amount,
        reason,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def remove_credits(uid, amount, reason="Tool"):

    conn = db()

    conn.execute("""
        UPDATE users
        SET credits=MAX(0, credits-?)
        WHERE user_id=?
    """, (amount, uid))

    conn.execute("""
        INSERT INTO credit_history
        (user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        uid,
        -amount,
        reason,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def add_xp(uid, amount=1):

    row = get_user(uid)

    if not row:
        return

    xp = row["xp"] + amount
    level = max(1, xp // 50 + 1)

    conn = db()

    conn.execute("""
        UPDATE users
        SET xp=?, level=?
        WHERE user_id=?
    """, (
        xp,
        level,
        uid
    ))

    conn.execute("""
        INSERT OR REPLACE INTO user_levels
        (user_id, xp, level)
        VALUES (?, ?, ?)
    """, (
        uid,
        xp,
        level
    ))

    conn.commit()
    conn.close()


def update_streak(uid):

    row = get_user(uid)

    if not row:
        return 1

    today = date.today().isoformat()

    if row["last_streak"] == today:
        return row["streak"]

    yesterday = (
        date.today() - timedelta(days=1)
    ).isoformat()

    streak = (
        row["streak"] + 1
        if row["last_streak"] == yesterday
        else 1
    )

    conn = db()

    conn.execute("""
        UPDATE users
        SET streak=?, last_streak=?
        WHERE user_id=?
    """, (
        streak,
        today,
        uid
    ))

    conn.commit()
    conn.close()

    add_xp(uid, 5)

    return streak


def log_history(uid, tool, status, cost=0):

    conn = db()

    conn.execute("""
        INSERT INTO history
        (user_id, tool, status, cost, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        uid,
        tool,
        status,
        cost,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


# ============================================================
# TOOL COSTS
# ============================================================

TOOL_COST = {

    "PDF → Word": 2,
    "PDF → TXT": 1,
    "PDF → JPG": 2,
    "PDF → PNG": 2,
    "PDF → Images ZIP": 3,

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

    "Image Info": 1,
    "Grayscale Image": 1,
    "Flip Image": 1,
    "Mirror Image": 1,
    "Rotate Image": 1,
    "Auto Enhance Image": 2,
}


def get_cost(tool):
    return TOOL_COST.get(tool, 1)


def can_use_tool(uid, tool):

    row = get_user(uid)

    if not row:
        return False, get_cost(tool)

    cost = get_cost(tool)

    return row["credits"] >= cost, cost


# ============================================================
# MAIN KEYBOARD
# ============================================================

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


# ============================================================
# PROFESSIONAL PROGRESS SYSTEM
# ============================================================

PROGRESS_DATA = {

    10: (
        "📥",
        "ফাইল সফলভাবে গ্রহণ করা হয়েছে!",
        "আপনার ফাইল এখন নিরাপদ processing pipeline-এ প্রবেশ করেছে।"
    ),

    20: (
        "🔍",
        "ফাইল গভীরভাবে বিশ্লেষণ করা হচ্ছে!",
        "ডকুমেন্টের structure, pages এবং data যাচাই করা হচ্ছে।"
    ),

    30: (
        "📑",
        "ডকুমেন্ট প্রস্তুত হচ্ছে!",
        "প্রয়োজনীয় pages ও internal data প্রস্তুত করা হচ্ছে।"
    ),

    40: (
        "⚙️",
        "Processing engine চালু হয়েছে!",
        "এখন মূল conversion ও optimization কাজ চলছে।"
    ),

    50: (
        "🧠",
        "Smart processing চলছে!",
        "ফাইলের content আরও নির্ভুলভাবে প্রক্রিয়া করা হচ্ছে।"
    ),

    60: (
        "🛠️",
        "Advanced processing চলছে!",
        "আপনার output-এর quality ও structure প্রস্তুত করা হচ্ছে।"
    ),

    70: (
        "✨",
        "Output optimize করা হচ্ছে!",
        "ফাইলকে আরও পরিষ্কার ও ব্যবহারযোগ্য করার কাজ চলছে।"
    ),

    80: (
        "📦",
        "Final package তৈরি হচ্ছে!",
        "প্রসেস করা data এখন final output-এ সাজানো হচ্ছে।"
    ),

    90: (
        "🚀",
        "শেষ ধাপ চলছে!",
        "সবকিছু যাচাই করে final output প্রস্তুত করা হচ্ছে।"
    ),

    100: (
        "🏆",
        "PROCESSING COMPLETE!",
        "আপনার ফাইল সফলভাবে প্রস্তুত হয়েছে।"
    ),
}


def progress_bar(percent):

    n = max(0, min(10, percent // 10))

    return "▰" * n + "□" * (10 - n)


def progress_text(tool, percent, job_id=""):

    icon, title, subtitle = PROGRESS_DATA.get(
        percent,
        (
            "⚙️",
            "Processing...",
            "Please wait..."
        )
    )

    return (
        "🚀 *RAFIM PDF PRO*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ *SMART PROCESSING ENGINE*\n\n"

        f"📄 *Tool:* `{tool}`\n"
        f"🆔 *Job:* `{job_id[:8] if job_id else 'PROCESS'}`\n\n"

        f"🔄 *{percent}%*\n"
        f"`{progress_bar(percent)}`\n\n"

        f"{icon} *{title}*\n"
        f"└─ {subtitle}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "💎 *Professional Processing*\n"
        "🔒 Secure • ⚡ Fast • 🧠 Smart\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


async def update_progress(message, tool, percent, job_id=""):

    try:
        await message.edit_text(
            progress_text(
                tool,
                percent,
                job_id
            ),
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def animate_progress(
    message,
    tool,
    stop_event,
    job_id=""
):

    for percent in [
        40, 50, 60, 70, 80, 90
    ]:

        if stop_event.is_set():
            return

        await update_progress(
            message,
            tool,
            percent,
            job_id
        )

        await asyncio.sleep(0.65)


# ============================================================
# JOB SYSTEM
# ============================================================

def create_job(uid, tool):

    job_id = uuid.uuid4().hex

    conn = db()

    conn.execute("""
        INSERT INTO jobs
        (id, user_id, tool, status, created_at)
        VALUES (?, ?, ?, 'processing', ?)
    """, (
        job_id,
        uid,
        tool,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return job_id


def finish_job(job_id, status, error=""):

    conn = db()

    conn.execute("""
        UPDATE jobs
        SET status=?, error=?, finished_at=?
        WHERE id=?
    """, (
        status,
        error[:1000],
        datetime.now().isoformat(),
        job_id
    ))

    conn.commit()
    conn.close()


def active_job(uid):

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM jobs
        WHERE user_id=?
        AND status='processing'
        ORDER BY created_at DESC
        LIMIT 1
    """, (uid,)).fetchone()

    conn.close()

    return row


# ============================================================
# START
# ============================================================

async def start(update, context):

    user = update.effective_user

    ensure_user(user)

    if is_banned(user.id):

        await update.message.reply_text(
            "🚫 *ACCESS RESTRICTED*\n\n"
            "Your account is currently blocked.",
            parse_mode="Markdown"
        )

        return

    if context.args:

        ref = context.args[0]

        if ref.startswith("RAFIM"):

            try:

                ref_id = int(
                    ref.replace("RAFIM", "")
                )

                if ref_id != user.id:

                    row = get_user(user.id)

                    if row and row["referred_by"] is None:

                        ref_user = get_user(ref_id)

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
                                SET referral_count=referral_count+1
                                WHERE user_id=?
                            """, (ref_id,))

                            conn.commit()
                            conn.close()

                            add_credits(
                                ref_id,
                                2,
                                "Referral Bonus"
                            )

                            try:
                                await context.bot.send_message(
                                    ref_id,
                                    "🎉 *REFERRAL BONUS UNLOCKED!*\n\n"
                                    "Someone joined using your invitation.\n\n"
                                    "💰 *+2 Credits*\n"
                                    "👥 Your referral network just grew!\n\n"
                                    "Keep sharing and keep earning 🚀",
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                pass

            except Exception:
                pass

    await update.message.reply_text(
        "🔥 *WELCOME TO RAFIM PDF PRO* 🔥\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "📕 *PDF Processing*\n"
        "🖼️ *Image Processing*\n"
        "💎 *Premium System*\n"
        "🎁 *Daily Rewards*\n"
        "👥 *Refer & Earn*\n"
        "🏆 *XP & Levels*\n"
        "🎟️ *Redeem Rewards*\n\n"

        "⚡ Fast processing\n"
        "🔒 Secure file handling\n"
        "🧠 Smart conversion engine\n\n"

        "👇 *Choose what you want to do:*",
        parse_mode="Markdown",
        reply_markup=MAIN_MARKUP
    )


async def menu(update, context):
    await start(update, context)


# ============================================================
# PDF MENU
# ============================================================

async def pdf_menu(update, context):

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
                "📦 PDF → Images ZIP",
                callback_data="pdf_images_zip"
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
        "📕 *RAFIM PDF PRO — PDF LAB*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🧠 Professional document tools\n"
        "⚡ Fast conversion\n"
        "🔒 Secure processing\n\n"
        "👇 *Select a tool:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# IMAGE MENU
# ============================================================

async def image_menu(update, context):

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
                "📊 Image Info",
                callback_data="img_info"
            ),
            InlineKeyboardButton(
                "✨ Auto Enhance",
                callback_data="img_enhance"
            )
        ],

        [
            InlineKeyboardButton(
                "⚫ Grayscale",
                callback_data="img_gray"
            ),
            InlineKeyboardButton(
                "🔄 Rotate",
                callback_data="img_rotate"
            )
        ],

        [
            InlineKeyboardButton(
                "↔️ Mirror",
                callback_data="img_mirror"
            ),
            InlineKeyboardButton(
                "↕️ Flip",
                callback_data="img_flip"
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
        "🖼️ *RAFIM PDF PRO — IMAGE LAB*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "✨ Enhance • Resize • Convert\n"
        "🗜️ Compress • Rotate • Optimize\n\n"
        "👇 *Select a tool:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# PREMIUM
# ============================================================

async def premium_menu(update, context):

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
        "💎 *RAFIM PREMIUM*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "🚀 Unlock the professional experience.\n\n"

        "📦 Larger file limit\n"
        "⚡ Priority processing\n"
        "📚 Batch processing\n"
        "🎁 Bonus credits\n"
        "🏷️ Premium status\n"
        "🔓 Advanced tools\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 *Choose your plan:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def premium_command(update, context):
    await premium_menu(update, context)


# ============================================================
# ACCOUNT
# ============================================================

async def account(update, context):

    user = update.effective_user
    ensure_user(user)

    row = get_user(user.id)

    plan = (
        "💎 PREMIUM"
        if is_premium(user.id)
        else "🆓 FREE"
    )

    until = row["premium_until"] or "N/A"

    await update.message.reply_text(
        "👤 *YOUR RAFIM PROFILE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"🆔 ID: `{user.id}`\n"
        f"👤 Name: `{user.first_name or 'User'}`\n"
        f"💰 Credits: *{row['credits']}*\n"
        f"🏷️ Plan: *{plan}*\n"
        f"⭐ Level: *{row['level']}*\n"
        f"✨ XP: *{row['xp']}*\n"
        f"🔥 Streak: *{row['streak']} days*\n"
        f"👥 Referrals: *{row['referral_count']}*\n"
        f"⏳ Premium Until: `{until[:19]}`\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 Keep processing files to earn XP!",
        parse_mode="Markdown"
    )


async def account_command(update, context):
    await account(update, context)


# ============================================================
# DAILY BONUS
# ============================================================

async def daily_bonus(update, context):

    user = update.effective_user
    ensure_user(user)

    row = get_user(user.id)
    today = date.today().isoformat()

    if row["last_bonus"] == today:

        await update.message.reply_text(
            "🎁 *DAILY REWARD ALREADY CLAIMED*\n\n"
            "⏳ Your next reward is waiting tomorrow.\n"
            "🔥 Keep your streak alive!",
            parse_mode="Markdown"
        )

        return

    streak = update_streak(user.id)

    bonus = DAILY_BONUS

    if streak >= 7:
        bonus += 2

    if streak >= 30:
        bonus += 5

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
        "🎉 *DAILY REWARD UNLOCKED!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 *+{bonus} Credits*\n"
        f"🔥 *{streak} Day Streak*\n"
        "✨ *+5 XP*\n\n"

        "🏆 Keep coming back every day.\n"
        "Your streak can unlock bigger rewards!\n\n"
        "━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown"
    )


async def bonus_command(update, context):
    await daily_bonus(update, context)


# ============================================================
# REFERRAL
# ============================================================

async def refer(update, context):

    user = update.effective_user
    ensure_user(user)

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=RAFIM{user.id}"
    )

    row = get_user(user.id)

    await update.message.reply_text(
        "👥 *REFER & EARN*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "🎁 Invite your friends.\n"
        "💰 Earn *2 credits* for each valid referral.\n\n"

        f"🔗 *Your Link:*\n{link}\n\n"

        f"👥 Total referrals: *{row['referral_count']}*\n\n"

        "🚀 Share your link and grow your rewards!",
        parse_mode="Markdown"
    )


async def refer_command(update, context):
    await refer(update, context)


async def referral_leaderboard(update, context):

    conn = db()

    rows = conn.execute("""
        SELECT first_name, username, referral_count
        FROM users
        ORDER BY referral_count DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    text = (
        "🏆 *REFERRAL LEADERBOARD*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, row in enumerate(rows, 1):

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


# ============================================================
# REDEEM
# ============================================================

async def redeem(update, context):

    if not context.args:

        await update.message.reply_text(
            "🎟️ *REDEEM CODE*\n\n"
            "Use:\n"
            "`/redeem YOURCODE`",
            parse_mode="Markdown"
        )

        return

    code = context.args[0].upper()

    user = update.effective_user
    ensure_user(user)

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM redeem_codes
        WHERE code=?
    """, (code,)).fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "❌ *CODE NOT FOUND*\n\n"
            "The code is invalid or does not exist.",
            parse_mode="Markdown"
        )

        return

    if not row["active"]:

        conn.close()

        await update.message.reply_text(
            "🚫 This redeem code has been disabled."
        )

        return

    if row["used_count"] >= row["max_uses"]:

        conn.close()

        await update.message.reply_text(
            "⚠️ This code has reached its maximum usage."
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
            "⚠️ You already redeemed this code."
        )

        return

    conn.execute("""
        INSERT INTO redemptions
        (user_id, code, redeemed_at)
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
    """, (code,))

    conn.commit()
    conn.close()

    add_credits(
        user.id,
        row["credits"],
        f"Redeem: {code}"
    )

    await update.message.reply_text(
        "🎉 *REWARD UNLOCKED!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎟️ Code: `{code}`\n"
        f"💰 Reward: *+{row['credits']} credits*\n\n"
        "🔥 Your balance has been updated!",
        parse_mode="Markdown"
    )


async def redeem_button(update, context):

    await update.message.reply_text(
        "🎟️ *REDEEM YOUR REWARD*\n\n"
        "Send:\n"
        "`/redeem CODE`\n\n"
        "Example:\n"
        "`/redeem RAFIM20`",
        parse_mode="Markdown"
    )


# ============================================================
# HISTORY
# ============================================================

async def history(update, context):

    user = update.effective_user
    ensure_user(user)

    conn = db()

    rows = conn.execute("""
        SELECT tool, status, cost, created_at
        FROM history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
    """, (
        user.id,
        MAX_HISTORY
    )).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "📜 *NO PROCESSING HISTORY YET*\n\n"
            "Your completed jobs will appear here.",
            parse_mode="Markdown"
        )

        return

    text = (
        "📜 *PROCESSING HISTORY*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for row in rows:

        icon = (
            "✅"
            if row["status"] == "Success"
            else "❌"
        )

        text += (
            f"{icon} `{row['tool']}`\n"
            f"   Status: {row['status']}\n"
            f"   Cost: {row['cost']}\n"
            f"   {row['created_at'][:19]}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def credit_history_cmd(update, context):

    user = update.effective_user

    conn = db()

    rows = conn.execute("""
        SELECT amount, reason, created_at
        FROM credit_history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 30
    """, (user.id,)).fetchall()

    conn.close()

    text = (
        "💳 *CREDIT WALLET HISTORY*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not rows:
        text += "No transactions yet."

    else:

        for row in rows:

            sign = "+" if row["amount"] > 0 else ""

            text += (
                f"{sign}{row['amount']} "
                f"— {row['reason']}\n"
            )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


# ============================================================
# SETTINGS
# ============================================================

async def settings(update, context):

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
                "🔔 Notifications",
                callback_data="toggle_notifications"
            )
        ],

        [
            InlineKeyboardButton(
                "⭐ Quality Settings",
                callback_data="quality_menu"
            )
        ],

        [
            InlineKeyboardButton(
                "🗜️ Compression Settings",
                callback_data="compression_menu"
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
        "⚙️ *RAFIM CONTROL CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Customize your processing experience.\n\n"
        "👇 Select a setting:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# SUPPORT
# ============================================================

async def support(update, context):

    await update.message.reply_text(
        "🆘 *RAFIM SUPPORT CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👨‍💻 Direct support: @{SUPPORT_USERNAME}\n\n"

        "Or send your problem in the next message.\n"
        "🎫 A support ticket will automatically be created.\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ We are here to help!",
        parse_mode="Markdown"
    )

    context.user_data["support_waiting"] = True


async def support_message(update, context):

    if not context.user_data.get("support_waiting"):
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
        (user_id, message, status, created_at)
        VALUES (?, ?, 'open', ?)
    """, (
        update.effective_user.id,
        msg,
        datetime.now().isoformat()
    ))

    ticket_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data["support_waiting"] = False

    await update.message.reply_text(
        "🎫 *SUPPORT TICKET CREATED*\n\n"
        f"🆔 Ticket: `#{ticket_id}`\n"
        "⏳ Status: Open\n\n"
        "Your message has been forwarded to support.",
        parse_mode="Markdown"
    )

    try:

        await context.bot.send_message(
            ADMIN_ID,
            "🆘 *NEW SUPPORT TICKET*\n\n"
            f"🎫 #{ticket_id}\n"
            f"👤 User: `{update.effective_user.id}`\n"
            f"💬 Message:\n{msg}",
            parse_mode="Markdown"
        )

    except Exception:
        pass

    return True


# ============================================================
# PDF PROCESSING
# ============================================================

def parse_page_range(text, total):

    text = text.strip()

    if not text:
        return list(range(total))

    pages = set()

    for part in text.split(","):

        part = part.strip()

        if "-" in part:

            a, b = part.split("-", 1)

            a = max(1, int(a))
            b = min(total, int(b))

            for x in range(a, b + 1):
                pages.add(x - 1)

        else:

            x = int(part)

            if 1 <= x <= total:
                pages.add(x - 1)

    return sorted(pages)


async def process_pdf(
    file_path,
    tool,
    output_dir,
    context,
    user_id
):

    doc = fitz.open(file_path)

    if len(doc) == 0:
        raise RuntimeError("PDF has no pages.")

    output = None

    # --------------------------------------------------------
    # PDF → WORD
    # --------------------------------------------------------

    if tool == "PDF → Word":

        word = WordDocument()

        for page in doc:

            text = page.get_text()

            if text.strip():
                word.add_paragraph(text)

        output = os.path.join(
            output_dir,
            "converted.docx"
        )

        word.save(output)

    # --------------------------------------------------------
    # PDF → TXT
    # --------------------------------------------------------

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

            for i, page in enumerate(doc, 1):

                f.write(
                    f"\n===== PAGE {i} =====\n\n"
                )

                f.write(
                    page.get_text()
                )

    # --------------------------------------------------------
    # PDF → JPG / PNG FIRST PAGE
    # --------------------------------------------------------

    elif tool in ["PDF → JPG", "PDF → PNG"]:

        ext = (
            "jpg"
            if tool == "PDF → JPG"
            else "png"
        )

        output = os.path.join(
            output_dir,
            f"page_1.{ext}"
        )

        pix = doc[0].get_pixmap(
            matrix=fitz.Matrix(2, 2),
            alpha=False
        )

        pix.save(output)

    # --------------------------------------------------------
    # ALL PDF PAGES → ZIP
    # --------------------------------------------------------

    elif tool == "PDF → Images ZIP":

        zip_path = os.path.join(
            output_dir,
            "pdf_images.zip"
        )

        with zipfile.ZipFile(
            zip_path,
            "w",
            zipfile.ZIP_DEFLATED
        ) as z:

            for i, page in enumerate(doc, 1):

                path = os.path.join(
                    output_dir,
                    f"page_{i}.png"
                )

                pix = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    alpha=False
                )

                pix.save(path)

                z.write(
                    path,
                    f"page_{i}.png"
                )

        output = zip_path

    # --------------------------------------------------------
    # COMPRESS
    # --------------------------------------------------------

    elif tool == "Compress PDF":

        output = os.path.join(
            output_dir,
            "compressed.pdf"
        )

        new_doc = fitz.open()

        new_doc.insert_pdf(doc)

        new_doc.save(
            output,
            garbage=4,
            deflate=True,
            clean=True
        )

        new_doc.close()

    # --------------------------------------------------------
    # SPLIT PDF → ZIP
    # --------------------------------------------------------

    elif tool == "Split PDF":

        zip_path = os.path.join(
            output_dir,
            "split_pages.zip"
        )

        with zipfile.ZipFile(
            zip_path,
            "w",
            zipfile.ZIP_DEFLATED
        ) as z:

            for i in range(len(doc)):

                one = fitz.open()

                one.insert_pdf(
                    doc,
                    from_page=i,
                    to_page=i
                )

                path = os.path.join(
                    output_dir,
                    f"page_{i+1}.pdf"
                )

                one.save(path)
                one.close()

                z.write(
                    path,
                    f"page_{i+1}.pdf"
                )

        output = zip_path

    # --------------------------------------------------------
    # EXTRACT PAGES
    # --------------------------------------------------------

    elif tool == "Extract Pages":

        pages = context.user_data.pop(
            "page_range",
            None
        )

        if pages:
            indexes = parse_page_range(
                pages,
                len(doc)
            )
        else:
            indexes = [0]

        output = os.path.join(
            output_dir,
            "extracted.pdf"
        )

        new_doc = fitz.open()

        for i in indexes:

            new_doc.insert_pdf(
                doc,
                from_page=i,
                to_page=i
            )

        new_doc.save(output)
        new_doc.close()

    # --------------------------------------------------------
    # ROTATE
    # --------------------------------------------------------

    elif tool == "Rotate PDF":

        output = os.path.join(
            output_dir,
            "rotated.pdf"
        )

        for page in doc:

            page.set_rotation(
                (page.rotation + 90) % 360
            )

        doc.save(output)

    # --------------------------------------------------------
    # PAGE SIZE
    # --------------------------------------------------------

    elif tool == "PDF Page Size":

        output = os.path.join(
            output_dir,
            "page_size.pdf"
        )

        new_doc = fitz.open()

        for page in doc:

            rect = page.rect

            new_page = new_doc.new_page(
                width=rect.width,
                height=rect.height
            )

            new_page.show_pdf_page(
                new_page.rect,
                doc,
                page.number
            )

        new_doc.save(output)
        new_doc.close()

    # --------------------------------------------------------
    # PAGE NUMBERS
    # --------------------------------------------------------

    elif tool == "Add Page Numbers":

        output = os.path.join(
            output_dir,
            "numbered.pdf"
        )

        total = len(doc)

        for i, page in enumerate(doc, 1):

            page.insert_text(
                (
                    page.rect.width / 2 - 15,
                    page.rect.height - 25
                ),
                f"{i} / {total}",
                fontsize=10
            )

        doc.save(output)

    # --------------------------------------------------------
    # WATERMARK
    # --------------------------------------------------------

    elif tool == "Add Watermark":

        output = os.path.join(
            output_dir,
            "watermarked.pdf"
        )

        watermark = context.user_data.pop(
            "watermark_text",
            "Rafim PDF Pro"
        )

        for page in doc:

            page.insert_textbox(
                page.rect,
                watermark,
                fontsize=28,
                rotate=45,
                align=1,
                color=(0.5, 0.5, 0.5),
                fill_opacity=0.15,
                stroke_opacity=0
            )

        doc.save(output)

    # --------------------------------------------------------
    # REMOVE METADATA
    # --------------------------------------------------------

    elif tool == "Remove Metadata":

        output = os.path.join(
            output_dir,
            "clean.pdf"
        )

        doc.set_metadata({})

        doc.save(output)

    # --------------------------------------------------------
    # PDF INFO
    # --------------------------------------------------------

    elif tool == "PDF Info":

        output = os.path.join(
            output_dir,
            "pdf_info.txt"
        )

        info = doc.metadata

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
                f"\n\nPages: {len(doc)}\n"
            )

            f.write(
                f"File size: "
                f"{os.path.getsize(file_path)} bytes\n"
            )

    # --------------------------------------------------------
    # PROTECT
    # --------------------------------------------------------

    elif tool == "Protect PDF":

        output = os.path.join(
            output_dir,
            "protected.pdf"
        )

        password = context.user_data.pop(
            "pdf_password",
            "123456"
        )

        doc.save(
            output,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=password,
            user_pw=password
        )

    # --------------------------------------------------------
    # UNLOCK
    # --------------------------------------------------------

    elif tool == "Unlock PDF":

        output = os.path.join(
            output_dir,
            "unlocked.pdf"
        )

        password = context.user_data.pop(
            "pdf_password",
            ""
        )

        if password:
            doc.authenticate(password)

        new_doc = fitz.open()

        new_doc.insert_pdf(doc)

        new_doc.save(output)
        new_doc.close()

    # --------------------------------------------------------
    # PDF → XPS
    # --------------------------------------------------------

    elif tool == "PDF → XPS":

        output = os.path.join(
            output_dir,
            "output.xps"
        )

        temp_pdf = os.path.join(
            output_dir,
            "temp.pdf"
        )

        doc.save(temp_pdf)

        proc = await asyncio.create_subprocess_exec(
            "gs",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=xps2",
            f"-sOutputFile={output}",
            temp_pdf,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        await proc.communicate()

        if not os.path.exists(output):
            raise RuntimeError(
                "Ghostscript XPS conversion is unavailable."
            )

    else:

        output = os.path.join(
            output_dir,
            "output.pdf"
        )

        doc.save(output)

    doc.close()

    return output


# ============================================================
# IMAGE PROCESSOR
# ============================================================

async def process_image(
    input_path,
    tool,
    output_dir,
    user_id,
    context
):

    img = Image.open(input_path)

    output = None

    if tool == "Compress Image":

        output = os.path.join(
            output_dir,
            "compressed.jpg"
        )

        if img.mode not in ["RGB", "L"]:
            img = img.convert("RGB")

        quality = 60

        img.save(
            output,
            "JPEG",
            quality=quality,
            optimize=True
        )

    elif tool == "Convert PNG":

        output = os.path.join(
            output_dir,
            "converted.png"
        )

        if img.mode not in [
            "RGB",
            "RGBA",
            "L"
        ]:
            img = img.convert("RGBA")

        img.save(output, "PNG")

    elif tool == "JPG ↔ PNG":

        output = os.path.join(
            output_dir,
            "converted.png"
        )

        if img.format == "PNG":

            output = os.path.join(
                output_dir,
                "converted.jpg"
            )

            if img.mode != "RGB":
                img = img.convert("RGB")

            img.save(
                output,
                "JPEG",
                quality=90
            )

        else:

            img.save(
                output,
                "PNG"
            )

    elif tool in [
        "Resize Image",
        "Custom Resize"
    ]:

        if tool == "Custom Resize":

            size_text = context.user_data.pop(
                "custom_size",
                ""
            )

            match = re.match(
                r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$",
                size_text
            )

            if match:

                width = int(match.group(1))
                height = int(match.group(2))

                img = img.resize(
                    (width, height),
                    Image.Resampling.LANCZOS
                )

        else:

            max_width = 1280

            if img.width > max_width:

                ratio = max_width / img.width

                img = img.resize(
                    (
                        int(img.width * ratio),
                        int(img.height * ratio)
                    ),
                    Image.Resampling.LANCZOS
                )

        output = os.path.join(
            output_dir,
            "resized.jpg"
        )

        if img.mode not in ["RGB", "L"]:
            img = img.convert("RGB")

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

    elif tool == "Image Info":

        output = os.path.join(
            output_dir,
            "image_info.txt"
        )

        info = {
            "format": img.format,
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "file_size": os.path.getsize(input_path)
        }

        with open(
            output,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                info,
                f,
                indent=2,
                ensure_ascii=False
            )

    elif tool == "Grayscale Image":

        output = os.path.join(
            output_dir,
            "grayscale.jpg"
        )

        img = ImageOps.grayscale(img)

        img.save(
            output,
            "JPEG",
            quality=90
        )

    elif tool == "Mirror Image":

        output = os.path.join(
            output_dir,
            "mirror.jpg"
        )

        img = ImageOps.mirror(img)

        if img.mode != "RGB":
            img = img.convert("RGB")

        img.save(output, "JPEG", quality=90)

    elif tool == "Flip Image":

        output = os.path.join(
            output_dir,
            "flip.jpg"
        )

        img = ImageOps.flip(img)

        if img.mode != "RGB":
            img = img.convert("RGB")

        img.save(output, "JPEG", quality=90)

    elif tool == "Rotate Image":

        output = os.path.join(
            output_dir,
            "rotated.jpg"
        )

        img = img.rotate(
            90,
            expand=True
        )

        if img.mode != "RGB":
            img = img.convert("RGB")

        img.save(output, "JPEG", quality=90)

    elif tool == "Auto Enhance Image":

        output = os.path.join(
            output_dir,
            "enhanced.jpg"
        )

        if img.mode != "RGB":
            img = img.convert("RGB")

        img = ImageEnhance.Contrast(
            img
        ).enhance(1.15)

        img = ImageEnhance.Sharpness(
            img
        ).enhance(1.20)

        img = ImageEnhance.Color(
            img
        ).enhance(1.10)

        img.save(
            output,
            "JPEG",
            quality=92
        )

    else:

        output = os.path.join(
            output_dir,
            "image.jpg"
        )

        img.save(output)

    return output


# ============================================================
# DOCUMENT HANDLER
# ============================================================

async def document_handler(update, context):

    user = update.effective_user

    ensure_user(user)

    if is_banned(user.id):
        return

    if await support_message(update, context):
        return

    if await submit_premium_request(update, context):
        return

    tool = context.user_data.get(
        "selected_tool"
    )

    if not tool:
        return

    if not update.message.document:
        return

    file_size = (
        update.message.document.file_size or 0
    )

    limit = (
        PREMIUM_FILE_LIMIT_MB
        if is_premium(user.id)
        else FREE_FILE_LIMIT_MB
    )

    if file_size > limit * 1024 * 1024:

        await update.message.reply_text(
            "🚫 *FILE TOO LARGE*\n\n"
            f"📦 Your limit: *{limit} MB*\n"
            f"📄 Your file: *{file_size / 1024 / 1024:.1f} MB*\n\n"
            "💎 Upgrade to Premium for a larger limit.",
            parse_mode="Markdown"
        )

        return

    ok, cost = can_use_tool(
        user.id,
        tool
    )

    if not ok:

        await update.message.reply_text(
            "💳 *INSUFFICIENT CREDITS*\n\n"
            f"Required: *{cost}*\n"
            f"Available: *{get_user(user.id)['credits']}*\n\n"
            "🎁 Claim your daily bonus or use Premium.",
            parse_mode="Markdown"
        )

        return

    # Special interactive tools.
    if tool == "Extract Pages":

        context.user_data["awaiting_page_range"] = True

        await update.message.reply_text(
            "📑 *PAGE RANGE SELECTOR*\n\n"
            "Send pages like:\n\n"
            "`1-3`\n"
            "`1,3,5`\n"
            "`1-3,7,10-12`\n\n"
            "Then send the PDF.",
            parse_mode="Markdown"
        )

        return

    status = await update.message.reply_text(
        progress_text(tool, 10),
        parse_mode="Markdown"
    )

    await asyncio.sleep(0.3)

    tmp_dir = tempfile.mkdtemp()

    filename = (
        update.message.document.file_name
        or "input.pdf"
    )

    input_path = os.path.join(
        tmp_dir,
        filename
    )

    job_id = create_job(
        user.id,
        tool
    )

    stop_event = asyncio.Event()
    progress_task = None

    started = time.time()

    try:

        await update_progress(
            status,
            tool,
            20,
            job_id
        )

        tg_file = await context.bot.get_file(
            update.message.document.file_id
        )

        await tg_file.download_to_drive(
            input_path
        )

        await update_progress(
            status,
            tool,
            30,
            job_id
        )

        progress_task = asyncio.create_task(
            animate_progress(
                status,
                tool,
                stop_event,
                job_id
            )
        )

        output = await process_pdf(
            input_path,
            tool,
            tmp_dir,
            context,
            user.id
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
            100,
            job_id
        )

        await asyncio.sleep(0.7)

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

        finish_job(
            job_id,
            "success"
        )

        elapsed = time.time() - started

        conn = db()

        conn.execute("""
            INSERT INTO usage_stats
            (user_id, tool, seconds, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            user.id,
            tool,
            elapsed,
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

        await status.edit_text(
            "🎉 *RAFIM PDF PRO*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🏆 *PROCESSING COMPLETE!*\n\n"

            f"📄 Tool: `{tool}`\n"
            "🔄 Progress: `100%`\n"
            "`▰▰▰▰▰▰▰▰▰▰`\n\n"

            "📦 Output is ready.\n"
            "📤 Sending your file now...\n\n"

            f"💰 Cost: *{cost} credits*\n"
            f"⚡ Time: *{elapsed:.1f}s*\n\n"

            "━━━━━━━━━━━━━━━━━━━━\n"
            "✨ *Thank you for using RAFIM PDF PRO!*",
            parse_mode="Markdown"
        )

        with open(output, "rb") as f:

            await update.message.reply_document(
                document=f,
                filename=os.path.basename(output),
                caption=(
                    f"✅ *{tool} completed!*\n\n"
                    f"💰 Cost: {cost} credits\n"
                    "🚀 Rafim PDF Pro"
                ),
                parse_mode="Markdown"
            )

    except Exception as e:

        stop_event.set()

        if progress_task:
            try:
                await progress_task
            except Exception:
                pass

        finish_job(
            job_id,
            "failed",
            str(e)
        )

        log_history(
            user.id,
            tool,
            "Failed",
            0
        )

        await status.edit_text(
            "⚠️ *RAFIM PDF PRO*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            "❌ *PROCESSING FAILED*\n\n"

            "Something went wrong while "
            "processing your file.\n\n"

            "💰 *NO CREDITS WERE CHARGED.*\n"
            "🔁 Please send the file again.\n\n"

            "━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ Your balance is safe.",
            parse_mode="Markdown"
        )

    finally:

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True
        )

        context.user_data.pop(
            "selected_tool",
            None
        )


# ============================================================
# PHOTO HANDLER
# ============================================================

async def photo_handler(update, context):

    user = update.effective_user

    ensure_user(user)

    if is_banned(user.id):
        return

    if await support_message(update, context):
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
            "💳 *NOT ENOUGH CREDITS*\n\n"
            f"Required: {cost}\n"
            f"Available: {get_user(user.id)['credits']}",
            parse_mode="Markdown"
        )

        return

    status = await update.message.reply_text(
        progress_text(tool, 10),
        parse_mode="Markdown"
    )

    tmp_dir = tempfile.mkdtemp()

    input_path = os.path.join(
        tmp_dir,
        "input.jpg"
    )

    job_id = create_job(
        user.id,
        tool
    )

    stop_event = asyncio.Event()
    progress_task = None

    started = time.time()

    try:

        await update_progress(
            status,
            tool,
            20,
            job_id
        )

        tg_file = await context.bot.get_file(
            update.message.photo[-1].file_id
        )

        await tg_file.download_to_drive(
            input_path
        )

        await update_progress(
            status,
            tool,
            30,
            job_id
        )

        progress_task = asyncio.create_task(
            animate_progress(
                status,
                tool,
                stop_event,
                job_id
            )
        )

        output = await process_image(
            input_path,
            tool,
            tmp_dir,
            user.id,
            context
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
            100,
            job_id
        )

        await asyncio.sleep(0.7)

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

        finish_job(
            job_id,
            "success"
        )

        elapsed = time.time() - started

        await status.edit_text(
            "🎉 *RAFIM PDF PRO*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🏆 *IMAGE PROCESSING COMPLETE!*\n\n"
            f"🖼️ Tool: `{tool}`\n"
            "🔄 Progress: `100%`\n"
            "`▰▰▰▰▰▰▰▰▰▰`\n\n"
            "📦 Your image is ready.\n"
            "📤 Sending now...\n\n"
            f"💰 Cost: *{cost} credits*\n"
            f"⚡ Time: *{elapsed:.1f}s*\n\n"
            "━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown"
        )

        with open(output, "rb") as f:

            await update.message.reply_document(
                document=f,
                filename=os.path.basename(output),
                caption=(
                    f"✅ *{tool} completed!*\n\n"
                    f"💰 Cost: {cost} credits"
                ),
                parse_mode="Markdown"
            )

    except Exception as e:

        stop_event.set()

        if progress_task:
            try:
                await progress_task
            except Exception:
                pass

        finish_job(
            job_id,
            "failed",
            str(e)
        )

        log_history(
            user.id,
            tool,
            "Failed",
            0
        )

        await status.edit_text(
            "❌ *IMAGE PROCESSING FAILED*\n\n"
            "💰 No credits were charged.\n"
            "🔁 Please try again.",
            parse_mode="Markdown"
        )

    finally:

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True
        )

        context.user_data.pop(
            "selected_tool",
            None
        )


# ============================================================
# MULTIPLE IMAGE → PDF
# ============================================================

async def multi_image_start(update, context):

    user = update.effective_user

    ok, cost = can_use_tool(
        user.id,
        "Multiple Images → PDF"
    )

    if not ok:

        await update.message.reply_text(
            "❌ Not enough credits."
        )

        return

    context.user_data["multi_images"] = []

    await update.message.reply_text(
        "📚 *MULTI-IMAGE PDF MODE*\n\n"
        "Send up to 20 images.\n\n"
        "When finished, type:\n"
        "`/doneimages`",
        parse_mode="Markdown"
    )


async def multi_image_photo(update, context):

    if "multi_images" not in context.user_data:
        return

    files = context.user_data["multi_images"]

    if len(files) >= MAX_BATCH_FILES:

        await update.message.reply_text(
            "⚠️ Maximum 20 images reached.\n"
            "Use /doneimages now."
        )

        return

    tmp_dir = context.user_data.setdefault(
        "multi_dir",
        tempfile.mkdtemp()
    )

    path = os.path.join(
        tmp_dir,
        f"image_{len(files)+1}.jpg"
    )

    tg_file = await context.bot.get_file(
        update.message.photo[-1].file_id
    )

    await tg_file.download_to_drive(path)

    files.append(path)

    await update.message.reply_text(
        f"📸 Image #{len(files)} added.\n\n"
        "Send more images or use:\n"
        "`/doneimages`",
        parse_mode="Markdown"
    )


async def done_images(update, context):

    files = context.user_data.get(
        "multi_images"
    )

    if not files:
        return

    user = update.effective_user

    cost = get_cost(
        "Multiple Images → PDF"
    )

    ok, _ = can_use_tool(
        user.id,
        "Multiple Images → PDF"
    )

    if not ok:

        await update.message.reply_text(
            "❌ Not enough credits."
        )

        return

    tmp_dir = context.user_data["multi_dir"]

    output = os.path.join(
        tmp_dir,
        "images_to_pdf.pdf"
    )

    try:

        pdf = fitz.open()

        for path in files:

            img = Image.open(path)

            if img.mode not in ["RGB", "L"]:
                img = img.convert("RGB")

            image_bytes = io.BytesIO()

            img.save(
                image_bytes,
                format="JPEG",
                quality=90
            )

            image_bytes.seek(0)

            rect = fitz.Rect(
                0,
                0,
                img.width,
                img.height
            )

            page = pdf.new_page(
                width=rect.width,
                height=rect.height
            )

            page.insert_image(
                rect,
                stream=image_bytes.getvalue()
            )

        pdf.save(output)
        pdf.close()

        remove_credits(
            user.id,
            cost,
            "Tool: Multiple Images → PDF"
        )

        add_xp(user.id, 3)

        log_history(
            user.id,
            "Multiple Images → PDF",
            "Success",
            cost
        )

        with open(output, "rb") as f:

            await update.message.reply_document(
                document=f,
                filename="images_to_pdf.pdf",
                caption=(
                    "🎉 *PDF CREATED SUCCESSFULLY!*\n\n"
                    f"📸 Images: {len(files)}\n"
                    f"💰 Cost: {cost} credits"
                ),
                parse_mode="Markdown"
            )

    except Exception:

        log_history(
            user.id,
            "Multiple Images → PDF",
            "Failed",
            0
        )

        await update.message.reply_text(
            "❌ Could not create the PDF."
        )

    finally:

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True
        )

        context.user_data.pop(
            "multi_images",
            None
        )

        context.user_data.pop(
            "multi_dir",
            None
        )


# ============================================================
# MERGE PDF
# ============================================================

async def merge_pdf_handler(update, context):

    if not context.user_data.get("merge_mode"):
        return

    if not update.message.document:
        return

    user = update.effective_user

    files = context.user_data.setdefault(
        "merge_files",
        []
    )

    if len(files) >= MAX_BATCH_FILES:

        await update.message.reply_text(
            "⚠️ Maximum 20 PDFs reached.\n"
            "Use /done."
        )

        return

    tmp_dir = context.user_data.setdefault(
        "merge_dir",
        tempfile.mkdtemp()
    )

    name = (
        update.message.document.file_name
        or f"file_{len(files)+1}.pdf"
    )

    path = os.path.join(
        tmp_dir,
        f"{len(files)+1}_{name}"
    )

    tg_file = await context.bot.get_file(
        update.message.document.file_id
    )

    await tg_file.download_to_drive(path)

    files.append(path)

    await update.message.reply_text(
        f"📎 *PDF #{len(files)} ADDED*\n\n"
        "Send another PDF or type:\n"
        "`/done`",
        parse_mode="Markdown"
    )


async def done_merge(update, context):

    if not context.user_data.get("merge_mode"):
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

    cost = get_cost("Merge PDF")

    ok, _ = can_use_tool(
        user.id,
        "Merge PDF"
    )

    if not ok:

        await update.message.reply_text(
            "❌ Not enough credits."
        )

        return

    tmp_dir = context.user_data["merge_dir"]

    output = os.path.join(
        tmp_dir,
        "merged.pdf"
    )

    status = await update.message.reply_text(
        progress_text(
            "Merge PDF",
            10
        ),
        parse_mode="Markdown"
    )

    try:

        await update_progress(
            status,
            "Merge PDF",
            20
        )

        result = fitz.open()

        await update_progress(
            status,
            "Merge PDF",
            40
        )

        for path in files:

            doc = fitz.open(path)

            result.insert_pdf(doc)

            doc.close()

        await update_progress(
            status,
            "Merge PDF",
            70
        )

        result.save(output)
        result.close()

        await update_progress(
            status,
            "Merge PDF",
            100
        )

        remove_credits(
            user.id,
            cost,
            "Tool: Merge PDF"
        )

        add_xp(user.id, 3)

        log_history(
            user.id,
            "Merge PDF",
            "Success",
            cost
        )

        await status.edit_text(
            "🏆 *MERGE COMPLETE!*\n\n"
            f"📄 PDFs merged: *{len(files)}*\n"
            "🔄 Progress: `100%`\n"
            "📤 Sending merged PDF...",
            parse_mode="Markdown"
        )

        with open(output, "rb") as f:

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

        await status.edit_text(
            "❌ *MERGE FAILED*\n\n"
            "💰 No credits were charged.",
            parse_mode="Markdown"
        )

    finally:

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True
        )

        context.user_data.pop("merge_mode", None)
        context.user_data.pop("merge_files", None)
        context.user_data.pop("merge_dir", None)


# ============================================================
# PREMIUM REQUEST
# ============================================================

async def premium_plan(
    update,
    context,
    plan,
    amount
):

    context.user_data["premium_plan"] = plan
    context.user_data["premium_amount"] = amount
    context.user_data["premium_waiting"] = True

    await update.callback_query.answer()

    await update.callback_query.message.reply_text(
        f"💎 *{plan.upper()} PREMIUM*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Price: *৳{amount}*\n\n"
        "🧾 Send your transaction ID.\n\n"
        "Example:\n"
        "`TXN123456789`\n\n"
        "⏳ Your request will be reviewed by admin.",
        parse_mode="Markdown"
    )


async def submit_premium_request(update, context):

    if not context.user_data.get(
        "premium_waiting"
    ):
        return False

    if not update.message or not update.message.text:
        return False

    txn = update.message.text.strip()

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

    conn = db()

    cur = conn.execute("""
        INSERT INTO premium_requests
        (user_id, username, plan, amount, txn_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    """, (
        user.id,
        user.username or "",
        plan,
        amount,
        txn,
        datetime.now().isoformat()
    ))

    request_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data["premium_waiting"] = False

    await update.message.reply_text(
        "✅ *PREMIUM REQUEST SUBMITTED!*\n\n"
        f"🆔 Request: `#{request_id}`\n"
        f"💎 Plan: *{plan}*\n"
        "⏳ Status: *Pending review*\n\n"
        "Please wait for admin confirmation.",
        parse_mode="Markdown"
    )

    keyboard = [[
        InlineKeyboardButton(
            "✅ Approve",
            callback_data=f"approve_premium_{request_id}"
        ),
        InlineKeyboardButton(
            "❌ Reject",
            callback_data=f"reject_premium_{request_id}"
        )
    ]]

    try:

        await context.bot.send_message(
            ADMIN_ID,
            "💎 *NEW PREMIUM REQUEST*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 Request: `#{request_id}`\n"
            f"👤 User: `{user.id}`\n"
            f"Username: @{user.username or 'N/A'}\n"
            f"📦 Plan: {plan}\n"
            f"💰 Amount: ৳{amount}\n"
            f"🧾 TXN: `{txn}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception:
        pass

    return True


async def activate_premium(uid, plan):

    days = (
        7
        if plan.lower() == "weekly"
        else 30
    )

    bonus = (
        20
        if plan.lower() == "weekly"
        else 60
    )

    until = datetime.now() + timedelta(days=days)

    conn = db()

    conn.execute("""
        UPDATE users
        SET premium=1, premium_until=?
        WHERE user_id=?
    """, (
        until.isoformat(),
        uid
    ))

    conn.commit()
    conn.close()

    add_credits(
        uid,
        bonus,
        "Premium Bonus"
    )


# ============================================================
# TEXT HANDLER
# ============================================================

async def text_handler(update, context):

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

    # Interactive inputs.
    if context.user_data.get(
        "awaiting_page_range"
    ):

        context.user_data[
            "page_range"
        ] = text

        context.user_data[
            "awaiting_page_range"
        ] = False

        await update.message.reply_text(
            "✅ Page range saved.\n\n"
            "📎 Now send your PDF.",
            parse_mode="Markdown"
        )

        return

    if context.user_data.get(
        "awaiting_custom_size"
    ):

        if not re.match(
            r"^\s*\d+\s*[xX]\s*\d+\s*$",
            text
        ):

            await update.message.reply_text(
                "❌ Invalid size.\n\n"
                "Use example:\n"
                "`1920x1080`",
                parse_mode="Markdown"
            )

            return

        context.user_data[
            "custom_size"
        ] = text

        context.user_data[
            "awaiting_custom_size"
        ] = False

        await update.message.reply_text(
            "✅ Custom size saved.\n\n"
            "📎 Now send the image.",
            parse_mode="Markdown"
        )

        return

    if context.user_data.get(
        "awaiting_password"
    ):

        context.user_data[
            "pdf_password"
        ] = text

        context.user_data[
            "awaiting_password"
        ] = False

        await update.message.reply_text(
            "🔐 Password saved.\n\n"
            "📎 Now send your PDF.",
            parse_mode="Markdown"
        )

        return

    if context.user_data.get(
        "awaiting_watermark"
    ):

        context.user_data[
            "watermark_text"
        ] = text[:100]

        context.user_data[
            "awaiting_watermark"
        ] = False

        await update.message.reply_text(
            "💧 Watermark saved.\n\n"
            "📎 Now send your PDF.",
            parse_mode="Markdown"
        )

        return

    # Main menu.
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
        await redeem_button(update, context)
        return

    if text == "📜 History":
        await history(update, context)
        return

    if text == "🆘 Support":
        await support(update, context)
        return

    if text == "⚙️ Settings":
        await settings(update, context)
        return

    tool = context.user_data.get(
        "selected_tool"
    )

    if tool:

        await update.message.reply_text(
            "📎 *FILE REQUIRED*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛠️ Tool: `{tool}`\n"
            f"💰 Cost: `{get_cost(tool)} credits`\n\n"
            "Please send the required file.",
            parse_mode="Markdown"
        )


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(update, context):

    query = update.callback_query

    await query.answer()

    data = query.data
    user = query.from_user

    ensure_user(user)

    if data == "main_menu":

        await query.message.reply_text(
            "🏠 *MAIN MENU*\n\n"
            "Choose your next action.",
            parse_mode="Markdown",
            reply_markup=MAIN_MARKUP
        )

        return

    if data.startswith("pdf_"):

        tool_map = {

            "pdf_word": "PDF → Word",
            "pdf_txt": "PDF → TXT",
            "pdf_jpg": "PDF → JPG",
            "pdf_png": "PDF → PNG",
            "pdf_images_zip": "PDF → Images ZIP",
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

        tool = tool_map.get(data)

        if not tool:
            return

        context.user_data["selected_tool"] = tool

        # Special modes.
        if tool == "Merge PDF":

            context.user_data["merge_mode"] = True
            context.user_data["merge_files"] = []
            context.user_data["merge_dir"] = tempfile.mkdtemp()

            await query.message.reply_text(
                "🔗 *MERGE PDF MODE ACTIVATED*\n\n"
                "📎 Send 2–20 PDF files.\n"
                "When finished, type `/done`.",
                parse_mode="Markdown"
            )

            return

        if tool == "Extract Pages":

            context.user_data[
                "awaiting_page_range"
            ] = True

            await query.message.reply_text(
                "📑 *EXTRACT PAGES*\n\n"
                "First send your page range:\n\n"
                "`1-5`\n"
                "`1,3,7`\n"
                "`1-3,8-10`\n\n"
                "Then send the PDF.",
                parse_mode="Markdown"
            )

            return

        if tool in ["Protect PDF", "Unlock PDF"]:

            context.user_data[
                "awaiting_password"
            ] = True

            await query.message.reply_text(
                "🔐 *PASSWORD REQUIRED*\n\n"
                "Send the PDF password.\n\n"
                "For Protect PDF, this becomes the new password.\n"
                "For Unlock PDF, send the existing password.",
                parse_mode="Markdown"
            )

            return

        if tool == "Add Watermark":

            context.user_data[
                "awaiting_watermark"
            ] = True

            await query.message.reply_text(
                "💧 *CUSTOM WATERMARK*\n\n"
                "Send the watermark text.\n\n"
                "Example:\n"
                "`Rafim PDF Pro`",
                parse_mode="Markdown"
            )

            return

        await query.message.reply_text(
            "🚀 *TOOL READY!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛠️ Tool: `{tool}`\n"
            f"💰 Cost: `{get_cost(tool)} credits`\n\n"
            "📎 *Now send your file.*",
            parse_mode="Markdown"
        )

        return

    if data.startswith("img_"):

        tool_map = {

            "img_compress": "Compress Image",
            "img_png": "Convert PNG",
            "img_resize": "Resize Image",
            "img_convert": "JPG ↔ PNG",
            "img_custom": "Custom Resize",
            "img_webp": "Image → WebP",
            "img_multi_pdf": "Multiple Images → PDF",
            "img_info": "Image Info",
            "img_enhance": "Auto Enhance Image",
            "img_gray": "Grayscale Image",
            "img_rotate": "Rotate Image",
            "img_mirror": "Mirror Image",
            "img_flip": "Flip Image",
        }

        tool = tool_map.get(data)

        if not tool:
            return

        context.user_data["selected_tool"] = tool

        if tool == "Custom Resize":

            context.user_data[
                "awaiting_custom_size"
            ] = True

            await query.message.reply_text(
                "📏 *CUSTOM IMAGE SIZE*\n\n"
                "Send width × height.\n\n"
                "Example:\n"
                "`1920x1080`",
                parse_mode="Markdown"
            )

            return

        if tool == "Multiple Images → PDF":

            await multi_image_start(
                query.message,
                context
            )

            return

        await query.message.reply_text(
            "🖼️ *IMAGE TOOL READY!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛠️ `{tool}`\n"
            f"💰 Cost: `{get_cost(tool)} credits`\n\n"
            "📎 Send your image now.",
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

    if data.startswith("approve_premium_"):

        if user.id != ADMIN_ID:
            return

        rid = int(
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
        """, (rid,)).fetchone()

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
            SET status='approved'
            WHERE id=?
        """, (rid,))

        conn.commit()
        conn.close()

        await activate_premium(
            row["user_id"],
            row["plan"]
        )

        await query.message.edit_text(
            "✅ *PREMIUM APPROVED*\n\n"
            f"👤 User: `{row['user_id']}`\n"
            f"💎 Plan: {row['plan']}",
            parse_mode="Markdown"
        )

        try:

            await context.bot.send_message(
                row["user_id"],
                "🎉 *PREMIUM ACTIVATED!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💎 Plan: *{row['plan']}*\n"
                "🎁 Bonus credits added.\n"
                "🚀 Premium tools are now available!",
                parse_mode="Markdown"
            )

        except Exception:
            pass

        return

    if data.startswith("reject_premium_"):

        if user.id != ADMIN_ID:
            return

        rid = int(
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
        """, (rid,)).fetchone()

        if not row:
            conn.close()
            return

        conn.execute("""
            UPDATE premium_requests
            SET status='rejected'
            WHERE id=?
        """, (rid,))

        conn.commit()
        conn.close()

        await query.message.edit_text(
            "❌ *PREMIUM REQUEST REJECTED*",
            parse_mode="Markdown"
        )

        try:

            await context.bot.send_message(
                row["user_id"],
                "❌ Your premium request was rejected.\n\n"
                "Please contact support if needed."
            )

        except Exception:
            pass

        return

    if data in ["lang_bn", "lang_en"]:

        lang = (
            "bn"
            if data == "lang_bn"
            else "en"
        )

        conn = db()

        conn.execute("""
            UPDATE users
            SET language=?
            WHERE user_id=?
        """, (
            lang,
            user.id
        ))

        conn.execute("""
            UPDATE user_settings
            SET language=?
            WHERE user_id=?
        """, (
            lang,
            user.id
        ))

        conn.commit()
        conn.close()

        await query.message.reply_text(
            "🇧🇩 বাংলা ভাষা সেট করা হয়েছে।"
            if lang == "bn"
            else "🇺🇸 English language selected."
        )

        return

    if data == "toggle_notifications":

        conn = db()

        row = conn.execute("""
            SELECT notifications
            FROM user_settings
            WHERE user_id=?
        """, (user.id,)).fetchone()

        current = (
            row["notifications"]
            if row else 1
        )

        new_value = 0 if current else 1

        conn.execute("""
            UPDATE user_settings
            SET notifications=?
            WHERE user_id=?
        """, (
            new_value,
            user.id
        ))

        conn.commit()
        conn.close()

        await query.message.reply_text(
            "🔔 Notifications: "
            f"{'ON 🟢' if new_value else 'OFF 🔴'}"
        )

        return

    if data == "quality_menu":

        keyboard = [[
            InlineKeyboardButton(
                "High 95%",
                callback_data="quality_95"
            ),
            InlineKeyboardButton(
                "Medium 85%",
                callback_data="quality_85"
            ),
            InlineKeyboardButton(
                "Low 60%",
                callback_data="quality_60"
            )
        ]]

        await query.message.reply_text(
            "⭐ *IMAGE QUALITY*\n\n"
            "Choose your default quality:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if data.startswith("quality_"):

        quality = int(
            data.replace("quality_", "")
        )

        conn = db()

        conn.execute("""
            UPDATE user_settings
            SET quality=?
            WHERE user_id=?
        """, (
            quality,
            user.id
        ))

        conn.commit()
        conn.close()

        await query.message.reply_text(
            f"✅ Default quality set to {quality}%."
        )

        return

    if data == "compression_menu":

        keyboard = [[
            InlineKeyboardButton(
                "🟢 Low",
                callback_data="compression_low"
            ),
            InlineKeyboardButton(
                "🟡 Medium",
                callback_data="compression_medium"
            ),
            InlineKeyboardButton(
                "🔴 High",
                callback_data="compression_high"
            )
        ]]

        await query.message.reply_text(
            "🗜️ *COMPRESSION LEVEL*\n\n"
            "Choose your default level:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if data.startswith("compression_"):

        level = data.replace(
            "compression_",
            ""
        )

        conn = db()

        conn.execute("""
            UPDATE user_settings
            SET compression=?
            WHERE user_id=?
        """, (
            level,
            user.id
        ))

        conn.commit()
        conn.close()

        await query.message.reply_text(
            f"✅ Compression level set to *{level}*.",
            parse_mode="Markdown"
        )


# ============================================================
# HELP / ABOUT / STATUS
# ============================================================

async def help_command(update, context):

    await update.message.reply_text(
        "📚 *RAFIM PDF PRO HELP CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "/start — Start bot\n"
        "/menu — Main menu\n"
        "/premium — Premium plans\n"
        "/account — Account\n"
        "/bonus — Daily reward\n"
        "/refer — Referral link\n"
        "/leaderboard — Referral leaderboard\n"
        "/redeem CODE — Redeem reward\n"
        "/history — Processing history\n"
        "/credits — Credit history\n"
        "/cancel — Cancel current job\n"
        "/help — Help\n"
        "/about — About\n"
        "/status — Status\n\n"

        "🆘 Need help? Use Support.",
        parse_mode="Markdown"
    )


async def about_command(update, context):

    await update.message.reply_text(
        "🤖 *RAFIM PDF PRO*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "A professional Telegram file-processing system.\n\n"

        "📕 PDF Lab\n"
        "🖼️ Image Lab\n"
        "💎 Premium\n"
        "🎁 Rewards\n"
        "👥 Referral\n"
        "🏆 XP & Levels\n"
        "🎟️ Redeem\n"
        "🆘 Support\n"
        "👑 Admin Control\n\n"

        "⚡ Built for fast and convenient file processing.",
        parse_mode="Markdown"
    )


async def status_command(update, context):

    await update.message.reply_text(
        "🟢 *RAFIM PDF PRO STATUS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "🟢 Bot: Online\n"
        "🟢 PDF Engine: Ready\n"
        "🟢 Image Engine: Ready\n"
        "🟢 Database: Ready\n"
        "🟢 Render Health: Ready\n"
        "🟢 Reward System: Ready\n"
        "🟢 Premium System: Ready\n\n"

        "⚡ All major systems operational.",
        parse_mode="Markdown"
    )


# ============================================================
# CANCEL
# ============================================================

async def cancel_command(update, context):

    user = update.effective_user

    context.user_data.clear()

    await update.message.reply_text(
        "🛑 *CURRENT SESSION RESET*\n\n"
        "Any waiting file/tool selection has been cancelled.\n\n"
        "🏠 Use the menu to start again.",
        parse_mode="Markdown",
        reply_markup=MAIN_MARKUP
    )


# ============================================================
# ADMIN
# ============================================================

def admin_only(update):
    return update.effective_user.id == ADMIN_ID


async def admin_dashboard(update, context):

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

    pending = conn.execute(
        "SELECT COUNT(*) c FROM premium_requests WHERE status='pending'"
    ).fetchone()["c"]

    jobs = conn.execute(
        "SELECT COUNT(*) c FROM jobs"
    ).fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        "👑 *RAFIM ADMIN CONTROL CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Users: *{total}*\n"
        f"💎 Premium: *{premium}*\n"
        f"🚫 Banned: *{banned}*\n"
        f"💰 Credits in system: *{credits}*\n"
        f"⏳ Pending premium: *{pending}*\n"
        f"⚙️ Total jobs: *{jobs}*\n\n"

        "📢 /broadcast\n"
        "💎 /broadcastpremium\n"
        "🆓 /broadcastfree\n"
        "❌ /cancelbroadcast\n\n"

        "🎟️ /createcode CODE CREDITS USES\n"
        "📋 /codes\n"
        "🚫 /disablecode CODE\n\n"

        "💰 /addcredits USER_ID AMOUNT\n"
        "💎 /addpremium USER_ID DAYS\n"
        "👤 /userinfo USER_ID\n"
        "📊 /stats\n"
        "🚷 /ban USER_ID\n"
        "✅ /unban USER_ID",
        parse_mode="Markdown"
    )


async def createcode(update, context):

    if not admin_only(update):
        return

    if len(context.args) < 3:

        await update.message.reply_text(
            "/createcode CODE CREDITS USES"
        )

        return

    code = context.args[0].upper()

    try:

        credits = int(context.args[1])
        uses = int(context.args[2])

    except Exception:

        await update.message.reply_text(
            "Credits and uses must be numbers."
        )

        return

    conn = db()

    try:

        conn.execute("""
            INSERT INTO redeem_codes
            (code, credits, max_uses, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            code,
            credits,
            uses,
            datetime.now().isoformat()
        ))

        conn.commit()

        await update.message.reply_text(
            "🎟️ *REDEEM CODE CREATED*\n\n"
            f"Code: `{code}`\n"
            f"Credits: *{credits}*\n"
            f"Uses: *{uses}*",
            parse_mode="Markdown"
        )

    except sqlite3.IntegrityError:

        await update.message.reply_text(
            "❌ Code already exists."
        )

    finally:
        conn.close()


async def codes(update, context):

    if not admin_only(update):
        return

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM redeem_codes
        ORDER BY created_at DESC
    """).fetchall()

    conn.close()

    text = (
        "🎟️ *REDEEM CODE MANAGER*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for row in rows:

        status = (
            "🟢 ON"
            if row["active"]
            else "🔴 OFF"
        )

        text += (
            f"`{row['code']}` — "
            f"{row['credits']} credits — "
            f"{row['used_count']}/{row['max_uses']} — "
            f"{status}\n"
        )

    await update.message.reply_text(
        text or "No codes.",
        parse_mode="Markdown"
    )


async def disablecode(update, context):

    if not admin_only(update):
        return

    if not context.args:
        await update.message.reply_text(
            "/disablecode CODE"
        )
        return

    code = context.args[0].upper()

    conn = db()

    conn.execute("""
        UPDATE redeem_codes
        SET active=0
        WHERE code=?
    """, (code,))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🚫 Code disabled: `{code}`",
        parse_mode="Markdown"
    )


async def addcredits_admin(update, context):

    if not admin_only(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "/addcredits USER_ID AMOUNT"
        )

        return

    uid = int(context.args[0])
    amount = int(context.args[1])

    add_credits(
        uid,
        amount,
        "Admin Credit"
    )

    await update.message.reply_text(
        f"✅ Added *{amount} credits* to `{uid}`.",
        parse_mode="Markdown"
    )


async def addpremium_admin(update, context):

    if not admin_only(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "/addpremium USER_ID DAYS"
        )

        return

    uid = int(context.args[0])
    days = int(context.args[1])

    until = datetime.now() + timedelta(days=days)

    conn = db()

    conn.execute("""
        UPDATE users
        SET premium=1, premium_until=?
        WHERE user_id=?
    """, (
        until.isoformat(),
        uid
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"💎 Premium activated for `{uid}`\n"
        f"⏳ Days: *{days}*",
        parse_mode="Markdown"
    )


async def userinfo(update, context):

    if not admin_only(update):
        return

    if not context.args:
        await update.message.reply_text(
            "/userinfo USER_ID"
        )
        return

    uid = int(context.args[0])

    row = get_user(uid)

    if not row:

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    await update.message.reply_text(
        "👤 *USER INFORMATION*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"ID: `{uid}`\n"
        f"Username: @{row['username'] or 'N/A'}\n"
        f"Name: {row['first_name']}\n"
        f"Credits: *{row['credits']}*\n"
        f"Premium: *{bool(row['premium'])}*\n"
        f"Level: *{row['level']}*\n"
        f"XP: *{row['xp']}*\n"
        f"Referrals: *{row['referral_count']}*\n"
        f"Banned: *{bool(row['banned'])}*",
        parse_mode="Markdown"
    )


async def stats(update, context):

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
    """, (today,)).fetchone()["c"]

    today_jobs = conn.execute("""
        SELECT COUNT(*) c
        FROM history
        WHERE substr(created_at,1,10)=?
    """, (today,)).fetchone()["c"]

    successful = conn.execute("""
        SELECT COUNT(*) c
        FROM history
        WHERE status='Success'
    """).fetchone()["c"]

    failed = conn.execute("""
        SELECT COUNT(*) c
        FROM history
        WHERE status='Failed'
    """).fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        "📊 *RAFIM ANALYTICS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total users: *{total}*\n"
        f"🆕 Joined today: *{today_users}*\n"
        f"⚙️ Jobs today: *{today_jobs}*\n"
        f"✅ Successful jobs: *{successful}*\n"
        f"❌ Failed jobs: *{failed}*\n\n"
        "📈 Database analytics are active.",
        parse_mode="Markdown"
    )


async def ban_user(update, context):

    if not admin_only(update):
        return

    if not context.args:
        return

    uid = int(context.args[0])

    conn = db()

    conn.execute(
        "UPDATE users SET banned=1 WHERE user_id=?",
        (uid,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🚫 User `{uid}` banned.",
        parse_mode="Markdown"
    )


async def unban_user(update, context):

    if not admin_only(update):
        return

    if not context.args:
        return

    uid = int(context.args[0])

    conn = db()

    conn.execute(
        "UPDATE users SET banned=0 WHERE user_id=?",
        (uid,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ User `{uid}` unbanned.",
        parse_mode="Markdown"
    )


# ============================================================
# BROADCAST
# ============================================================

async def broadcast_start(update, context):

    if not admin_only(update):
        return

    context.bot_data["broadcast_waiting"] = True
    context.bot_data["broadcast_target"] = "all"

    await update.message.reply_text(
        "📢 *BROADCAST MODE*\n\n"
        "Send the message now.\n"
        "Text, photo, video and document are supported.\n\n"
        "Use /cancelbroadcast to cancel.",
        parse_mode="Markdown"
    )


async def broadcast_premium(update, context):

    if not admin_only(update):
        return

    context.bot_data["broadcast_waiting"] = True
    context.bot_data["broadcast_target"] = "premium"

    await update.message.reply_text(
        "💎 Send the Premium broadcast message."
    )


async def broadcast_free(update, context):

    if not admin_only(update):
        return

    context.bot_data["broadcast_waiting"] = True
    context.bot_data["broadcast_target"] = "free"

    await update.message.reply_text(
        "🆓 Send the Free-user broadcast message."
    )


async def cancel_broadcast(update, context):

    if not admin_only(update):
        return

    context.bot_data["broadcast_waiting"] = False

    conn = db()

    conn.execute("""
        UPDATE broadcast_jobs
        SET status='cancelled', finished_at=?
        WHERE status IN ('waiting','running')
    """, (
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🛑 Broadcast cancelled."
    )


async def broadcast_content_handler(update, context):

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

    context.bot_data["broadcast_waiting"] = False

    conn = db()

    if target == "premium":

        rows = conn.execute("""
            SELECT user_id
            FROM users
            WHERE premium=1 AND banned=0
        """).fetchall()

    elif target == "free":

        rows = conn.execute("""
            SELECT user_id
            FROM users
            WHERE premium=0 AND banned=0
        """).fetchall()

    else:

        rows = conn.execute("""
            SELECT user_id
            FROM users
            WHERE banned=0
        """).fetchall()

    conn.close()

    status = await update.message.reply_text(
        "📢 *BROADCAST STARTED*\n\n"
        f"🎯 Target: {target}\n"
        f"👥 Total: {len(rows)}\n"
        "✅ Sent: 0\n"
        "❌ Failed: 0",
        parse_mode="Markdown"
    )

    sent = 0
    failed = 0

    for index, row in enumerate(rows, 1):

        if not context.bot_data.get(
            "broadcast_target"
        ):
            break

        try:

            await context.bot.copy_message(
                chat_id=row["user_id"],
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )

            sent += 1

        except Exception:
            failed += 1

        if index % 10 == 0 or index == len(rows):

            try:

                await status.edit_text(
                    "📢 *BROADCAST RUNNING*\n\n"
                    f"🎯 Target: {target}\n"
                    f"📊 Progress: {index}/{len(rows)}\n"
                    f"✅ Sent: {sent}\n"
                    f"❌ Failed: {failed}",
                    parse_mode="Markdown"
                )

            except Exception:
                pass

        await asyncio.sleep(0.05)

    try:

        await status.edit_text(
            "🏁 *BROADCAST FINISHED*\n\n"
            f"🎯 Target: {target}\n"
            f"👥 Total: {len(rows)}\n"
            f"✅ Sent: {sent}\n"
            f"❌ Failed: {failed}",
            parse_mode="Markdown"
        )

    except Exception:
        pass

    return True


# ============================================================
# BOT COMMANDS
# ============================================================

async def setup_commands(application):

    commands = [

        BotCommand("start", "Start bot"),
        BotCommand("menu", "Main menu"),
        BotCommand("premium", "Premium plans"),
        BotCommand("account", "My account"),
        BotCommand("bonus", "Daily bonus"),
        BotCommand("refer", "Refer and earn"),
        BotCommand("leaderboard", "Referral leaderboard"),
        BotCommand("redeem", "Redeem code"),
        BotCommand("history", "Processing history"),
        BotCommand("credits", "Credit history"),
        BotCommand("cancel", "Cancel current session"),
        BotCommand("help", "Help"),
        BotCommand("about", "About"),
        BotCommand("status", "Bot status"),

    ]

    await application.bot.set_my_commands(
        commands
    )


# ============================================================
# MAIN
# ============================================================

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

    # --------------------------------------------------------
    # USER COMMANDS
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("menu", menu)
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
        CommandHandler(
            "leaderboard",
            referral_leaderboard
        )
    )

    application.add_handler(
        CommandHandler("redeem", redeem)
    )

    application.add_handler(
        CommandHandler("history", history)
    )

    application.add_handler(
        CommandHandler(
            "credits",
            credit_history_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("about", about_command)
    )

    application.add_handler(
        CommandHandler("status", status_command)
    )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("admin", admin_dashboard)
    )

    application.add_handler(
        CommandHandler("createcode", createcode)
    )

    application.add_handler(
        CommandHandler("codes", codes)
    )

    application.add_handler(
        CommandHandler("disablecode", disablecode)
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
        CommandHandler("userinfo", userinfo)
    )

    application.add_handler(
        CommandHandler("stats", stats)
    )

    application.add_handler(
        CommandHandler("ban", ban_user)
    )

    application.add_handler(
        CommandHandler("unban", unban_user)
    )

    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MERGE / IMAGE BATCH
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "done",
            done_merge
        )
    )

    application.add_handler(
        CommandHandler(
            "doneimages",
            done_images
        )
    )

    # --------------------------------------------------------
    # CALLBACK
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # --------------------------------------------------------
    # BROADCAST FIRST
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.ALL,
            broadcast_content_handler
        ),
        group=0
    )

    # --------------------------------------------------------
    # MERGE PDF
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Document.PDF,
            merge_pdf_handler
        ),
        group=1
    )

    # --------------------------------------------------------
    # NORMAL DOCUMENT
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler
        ),
        group=2
    )

    # --------------------------------------------------------
    # PHOTO
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            multi_image_photo
        ),
        group=2
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler
        ),
        group=3
    )

    # --------------------------------------------------------
    # TEXT
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        ),
        group=4
    )

    # --------------------------------------------------------
    # POST INIT
    # --------------------------------------------------------

    async def post_init(app_instance):

        await setup_commands(
            app_instance
        )

    application.post_init = post_init

    print(
        "🔥 Rafim PDF Pro started successfully."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
