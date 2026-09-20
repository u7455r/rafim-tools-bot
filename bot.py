# ============================================================
# RAFIM PDF PRO — ALL-IN-ONE TELEGRAM BOT
# ============================================================
# Render Start Command:
#     python bot.py
#
# requirements.txt:
#     python-telegram-bot
#     PyMuPDF
#     Pillow
#     python-docx
#     Flask
#
# Environment:
#     BOT_TOKEN=YOUR_BOT_TOKEN
#     ADMIN_ID=YOUR_ADMIN_ID
#     SUPPORT_USERNAME=rafimhossen
#     BKASH_NUMBER=YOUR_BKASH_NUMBER
#     NAGAD_NUMBER=YOUR_NAGAD_NUMBER
# ============================================================

import os
import io
import re
import json
import time
import uuid
import zipfile
import shutil
import sqlite3
import asyncio
import tempfile
import threading
import subprocess
from datetime import datetime, date, timedelta

import fitz
from PIL import Image, ImageOps, ImageEnhance
from docx import Document
from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "8298133943"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "rafimhossen")

# ------------------------------------------------------------
# PREMIUM PAYMENT NUMBERS
# ------------------------------------------------------------
BKASH_NUMBER = os.getenv(
    "BKASH_NUMBER",
    "YOUR bKASH NUMBER"
).strip()

NAGAD_NUMBER = os.getenv(
    "NAGAD_NUMBER",
    "YOUR NAGAD NUMBER"
).strip()

DB_FILE = os.getenv("DB_FILE", "rafim_pdf_pro.db")

FREE_CREDITS = int(os.getenv("FREE_CREDITS", "10"))
DAILY_BONUS = int(os.getenv("DAILY_BONUS", "3"))

FREE_FILE_LIMIT_MB = int(os.getenv("FREE_FILE_LIMIT_MB", "20"))
PREMIUM_FILE_LIMIT_MB = int(os.getenv("PREMIUM_FILE_LIMIT_MB", "100"))

WEEKLY_PRICE = int(os.getenv("WEEKLY_PRICE", "50"))
MONTHLY_PRICE = int(os.getenv("MONTHLY_PRICE", "150"))

REFERRAL_REWARD = int(os.getenv("REFERRAL_REWARD", "5"))
REFERRAL_XP = int(os.getenv("REFERRAL_XP", "20"))

XP_SUCCESS = int(os.getenv("XP_SUCCESS", "5"))

TEMP_DIR = "rafim_temp"
os.makedirs(TEMP_DIR, exist_ok=True)

app_flask = Flask(__name__)


@app_flask.route("/")
def home():
    return "Rafim PDF Pro is running!"


@app_flask.route("/health")
def health():
    return "OK"


def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app_flask.run(host="0.0.0.0", port=port)


threading.Thread(target=run_flask, daemon=True).start()


# ============================================================
# DATABASE
# ============================================================

db_lock = threading.Lock()


def db():
    con = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        credits INTEGER DEFAULT 10,
        premium INTEGER DEFAULT 0,
        premium_until TEXT,
        joined_at TEXT,
        last_bonus TEXT,
        referral_code TEXT UNIQUE,
        referred_by INTEGER,
        referral_count INTEGER DEFAULT 0,
        referral_earned INTEGER DEFAULT 0,
        language TEXT DEFAULT 'en',
        banned INTEGER DEFAULT 0,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        streak INTEGER DEFAULT 0,
        last_streak TEXT,
        notifications INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS redeem_codes(
        code TEXT PRIMARY KEY,
        credits INTEGER DEFAULT 0,
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS redemptions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        code TEXT,
        credits INTEGER,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tool TEXT,
        status TEXT,
        filename TEXT,
        credits INTEGER,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS credit_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        reason TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS premium_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan TEXT,
        transaction_id TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        reviewed_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS support_tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_settings(
        user_id INTEGER PRIMARY KEY,
        language TEXT DEFAULT 'en',
        notifications INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS broadcast_jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        mode TEXT,
        message TEXT,
        total INTEGER DEFAULT 0,
        sent INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        status TEXT DEFAULT 'running',
        created_at TEXT,
        finished_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS jobs(
        job_id TEXT PRIMARY KEY,
        user_id INTEGER,
        tool TEXT,
        filename TEXT,
        status TEXT DEFAULT 'processing',
        created_at TEXT,
        finished_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    con.commit()
    con.close()


init_db()


# ============================================================
# LANGUAGE SYSTEM
# ============================================================

LANGUAGES = {
    "bn": "🇧🇩 বাংলা",
    "en": "🇺🇸 English",
    "hi": "🇮🇳 हिन्दी",
    "ur": "🇵🇰 اردو",
    "ar": "🇸🇦 العربية",
    "es": "🇪🇸 Español",
    "fr": "🇫🇷 Français",
    "de": "🇩🇪 Deutsch",
    "it": "🇮🇹 Italiano",
    "pt": "🇵🇹 Português",
    "ru": "🇷🇺 Русский",
    "zh": "🇨🇳 中文",
    "ja": "🇯🇵 日本語",
    "ko": "🇰🇷 한국어",
    "tr": "🇹🇷 Türkçe",
    "id": "🇮🇩 Bahasa Indonesia",
    "ms": "🇲🇾 Bahasa Melayu",
    "th": "🇹🇭 ไทย",
    "vi": "🇻🇳 Tiếng Việt",
    "ta": "🇮🇳 தமிழ்",
    "te": "🇮🇳 తెలుగు",
    "mr": "🇮🇳 मराठी",
    "gu": "🇮🇳 ગુજરાતી",
    "kn": "🇮🇳 ಕನ್ನಡ",
    "pa": "🇮🇳 ਪੰਜਾਬੀ",
    "ne": "🇳🇵 नेपाली",
    "fa": "🇮🇷 فارسی",
    "sw": "🌍 Kiswahili",
    "nl": "🇳🇱 Nederlands",
}


T = {
    "en": {
        "pdf": "📕 PDF Tools",
        "image": "🖼️ Image Tools",
        "premium": "💎 Premium",
        "account": "👤 My Account",
        "bonus": "🎁 Daily Bonus",
        "refer": "👥 Refer & Earn",
        "redeem": "🎟️ Redeem Code",
        "history": "📜 History",
        "support": "🆘 Support",
        "settings": "⚙️ Settings",
        "back": "🔙 Back",
        "language": "🌐 Language",
        "help": "❓ Help",
        "about": "ℹ️ About",
        "home": "🏠 Main Menu",
        "welcome": """╔══════════════════════════════╗
        🚀 RAFIM PDF PRO
   ⚡ YOUR FILE. OUR POWER.
╚══════════════════════════════╝

👋 Welcome, {name}!

Your file is about to enter our
⚡ PRO PROCESSING ENGINE!

━━━━━━━━━━━━━━━━━━━━
💳 Credits      : {credits}
💎 Premium      : {premium}
⭐ Level        : {level}
🔥 Streak       : {streak}
👥 Referrals    : {referrals}
━━━━━━━━━━━━━━━━━━━━

🔥 LET'S PROCESS SOMETHING AWESOME!""",
        "processing": "⚡ PROCESSING ENGINE",
        "complete": "🎉 PROCESSING COMPLETE!",
        "failed": "🚨 PROCESSING INTERRUPTED",
        "cancelled": "⏹️ PROCESSING CANCELLED",
        "no_credit": "💳 You don't have enough credits.",
        "banned": "🚫 Your account is currently restricted.",
        "saved": "✅ Settings saved successfully!",
    },

    "bn": {
        "pdf": "📕 PDF Tools",
        "image": "🖼️ Image Tools",
        "premium": "💎 Premium",
        "account": "👤 আমার অ্যাকাউন্ট",
        "bonus": "🎁 দৈনিক বোনাস",
        "refer": "👥 রেফার & আর্ন",
        "redeem": "🎟️ রিডিম কোড",
        "history": "📜 হিস্টোরি",
        "support": "🆘 সাপোর্ট",
        "settings": "⚙️ সেটিংস",
        "back": "🔙 ফিরে যান",
        "language": "🌐 ভাষা",
        "help": "❓ সাহায্য",
        "about": "ℹ️ আমাদের সম্পর্কে",
        "home": "🏠 মেইন মেনু",
        "welcome": """╔══════════════════════════════╗
        🚀 RAFIM PDF PRO
   ⚡ আপনার ফাইল • আমাদের পাওয়ার
╚══════════════════════════════╝

👋 স্বাগতম, {name}!

আপনার ফাইল এখন ঢুকছে
⚡ PRO PROCESSING ENGINE-এর ভিতরে!

━━━━━━━━━━━━━━━━━━━━
💳 ক্রেডিট       : {credits}
💎 প্রিমিয়াম     : {premium}
⭐ লেভেল         : {level}
🔥 স্ট্রিক        : {streak}
👥 রেফারেল       : {referrals}
━━━━━━━━━━━━━━━━━━━━

🔥 চলুন, ফাইলকে POWER-UP করি!""",
        "processing": "⚡ PROCESSING ENGINE",
        "complete": "🎉 PROCESSING COMPLETE!",
        "failed": "🚨 PROCESSING INTERRUPTED",
        "cancelled": "⏹️ PROCESSING CANCELLED",
        "no_credit": "💳 আপনার পর্যাপ্ত ক্রেডিট নেই।",
        "banned": "🚫 আপনার অ্যাকাউন্ট বর্তমানে সীমাবদ্ধ।",
        "saved": "✅ সেটিংস সফলভাবে সংরক্ষণ হয়েছে!",
    },

    "hi": {
        "pdf": "📕 PDF Tools",
        "image": "🖼️ Image Tools",
        "premium": "💎 Premium",
        "account": "👤 मेरा अकाउंट",
        "bonus": "🎁 Daily Bonus",
        "refer": "👥 Refer & Earn",
        "redeem": "🎟️ Redeem Code",
        "history": "📜 History",
        "support": "🆘 Support",
        "settings": "⚙️ Settings",
        "back": "🔙 वापस",
        "language": "🌐 भाषा",
        "help": "❓ मदद",
        "about": "ℹ️ जानकारी",
        "home": "🏠 मुख्य मेनू",
        "welcome": """╔══════════════════════════════╗
        🚀 RAFIM PDF PRO
      ⚡ आपकी फाइल • हमारी Power
╚══════════════════════════════╝

👋 स्वागत है, {name}!

━━━━━━━━━━━━━━━━━━━━
💳 Credits : {credits}
💎 Premium : {premium}
⭐ Level   : {level}
🔥 Streak  : {streak}
👥 Referrals: {referrals}
━━━━━━━━━━━━━━━━━━━━

🔥 LET'S PROCESS SOMETHING AWESOME!""",
        "processing": "⚡ PROCESSING ENGINE",
        "complete": "🎉 PROCESSING COMPLETE!",
        "failed": "🚨 PROCESSING INTERRUPTED",
        "cancelled": "⏹️ PROCESSING CANCELLED",
        "no_credit": "💳 आपके पास पर्याप्त Credits नहीं हैं।",
        "banned": "🚫 आपका अकाउंट प्रतिबंधित है।",
        "saved": "✅ सेटिंग्स सेव हो गईं!",
    }
}


def tr(user_id, key, **kwargs):
    u = get_user(user_id)
    lang = u["language"] if u else "en"

    data = T.get(lang, T["en"])
    value = data.get(
        key,
        T["en"].get(key, key)
    )

    try:
        return value.format(**kwargs)
    except Exception:
        return value


def get_lang(user_id):
    u = get_user(user_id)
    return u["language"] if u else "en"


def set_language(user_id, lang):
    if lang not in LANGUAGES:
        lang = "en"

    con = db()

    con.execute(
        "UPDATE users SET language=? WHERE user_id=?",
        (lang, user_id)
    )

    con.execute(
        "INSERT OR REPLACE INTO user_settings("
        "user_id,language,notifications"
        ") VALUES(?,?,COALESCE("
        "(SELECT notifications FROM user_settings WHERE user_id=?),1))",
        (user_id, lang, user_id)
    )

    con.commit()
    con.close()


# ============================================================
# USER SYSTEM
# ============================================================

def referral_code_for(user_id):
    return f"R{user_id}"


def get_user(user_id):
    con = db()

    row = con.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    con.close()

    return row


def ensure_user(tg_user, referred_by=None):
    uid = tg_user.id
    now = datetime.now().isoformat()

    existing = get_user(uid)

    if existing:
        con = db()

        con.execute(
            "UPDATE users SET username=?, first_name=? "
            "WHERE user_id=?",
            (
                tg_user.username or "",
                tg_user.first_name or "",
                uid
            )
        )

        con.commit()
        con.close()

        return existing, False

    code = referral_code_for(uid)

    con = db()

    con.execute("""
        INSERT INTO users(
            user_id,username,first_name,credits,joined_at,
            referral_code,referred_by
        )
        VALUES(?,?,?,?,?,?,?)
    """, (
        uid,
        tg_user.username or "",
        tg_user.first_name or "",
        FREE_CREDITS,
        now,
        code,
        referred_by
    ))

    con.execute("""
        INSERT OR REPLACE INTO user_settings(
            user_id,language,notifications
        )
        VALUES(?,?,?)
    """, (
        uid,
        "en",
        1
    ))

    con.commit()
    con.close()

    return get_user(uid), True


def is_banned(user_id):
    u = get_user(user_id)
    return bool(u and u["banned"])


# ============================================================
# PREMIUM STATUS
# ============================================================

def is_premium(user_id):
    u = get_user(user_id)

    if not u:
        return False

    if not u["premium"]:
        return False

    if u["premium_until"]:
        try:
            expiry = datetime.fromisoformat(
                u["premium_until"]
            )

            if datetime.now() > expiry:
                con = db()

                con.execute(
                    "UPDATE users SET premium=0 WHERE user_id=?",
                    (user_id,)
                )

                con.commit()
                con.close()

                return False

        except Exception:
            pass

    return True


def premium_expiry_text(user_id):
    u = get_user(user_id)

    if not u or not u["premium"]:
        return "❌ Not Active"

    if not u["premium_until"]:
        return "♾️ Active"

    try:
        expiry = datetime.fromisoformat(
            u["premium_until"]
        )

        if datetime.now() >= expiry:
            return "❌ Expired"

        return expiry.strftime(
            "%Y-%m-%d %H:%M"
        )

    except Exception:
        return "N/A"


async def premium_expiry_watcher(application):
    """
    Background Premium expiry checker.
    Expired Premium users are automatically disabled.
    """

    while True:
        try:
            now = datetime.now().isoformat()

            con = db()

            rows = con.execute("""
                SELECT user_id,premium_until
                FROM users
                WHERE premium=1
                AND premium_until IS NOT NULL
                AND premium_until <= ?
            """, (now,)).fetchall()

            if rows:
                con.execute("""
                    UPDATE users
                    SET premium=0
                    WHERE premium=1
                    AND premium_until IS NOT NULL
                    AND premium_until <= ?
                """, (now,))

                con.commit()

            con.close()

            for row in rows:
                try:
                    await application.bot.send_message(
                        row["user_id"],
                        """⏰ <b>PREMIUM EXPIRED</b>

💎 আপনার Premium membership-এর মেয়াদ শেষ হয়েছে।

👤 আপনার account এখন Free plan-এ ফিরে গেছে।

🚀 আবার Premium নিতে নিচের Premium button ব্যবহার করুন।""",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton(
                                    "💎 Get Premium",
                                    callback_data="premium:menu"
                                )
                            ]
                        ])
                    )
                except Exception:
                    pass

        except Exception:
            pass

        await asyncio.sleep(60)


# ============================================================
# CREDIT / XP / STREAK
# ============================================================

def add_credits(user_id, amount, reason=""):
    con = db()

    con.execute(
        "UPDATE users SET credits=credits+? WHERE user_id=?",
        (amount, user_id)
    )

    con.execute("""
        INSERT INTO credit_history(
            user_id,amount,reason,created_at
        )
        VALUES(?,?,?,?)
    """, (
        user_id,
        amount,
        reason,
        datetime.now().isoformat()
    ))

    con.commit()
    con.close()


def remove_credits(user_id, amount, reason=""):
    u = get_user(user_id)

    if not u or u["credits"] < amount:
        return False

    add_credits(
        user_id,
        -amount,
        reason
    )

    return True


def add_xp(user_id, amount):
    con = db()

    u = get_user(user_id)

    if not u:
        con.close()
        return

    xp = u["xp"] + amount
    level = max(
        1,
        (xp // 100) + 1
    )

    con.execute(
        "UPDATE users SET xp=?,level=? WHERE user_id=?",
        (
            xp,
            level,
            user_id
        )
    )

    con.commit()
    con.close()


def update_streak(user_id):
    u = get_user(user_id)

    if not u:
        return

    today = date.today().isoformat()

    if u["last_streak"] == today:
        return

    streak = 1

    if u["last_streak"]:
        try:
            old = date.fromisoformat(
                u["last_streak"]
            )

            if old == date.today() - timedelta(days=1):
                streak = u["streak"] + 1

        except Exception:
            pass

    con = db()

    con.execute("""
        UPDATE users
        SET streak=?,last_streak=?
        WHERE user_id=?
    """, (
        streak,
        today,
        user_id
    ))

    con.commit()
    con.close()

    if streak in [3, 7, 14, 30]:
        add_credits(
            user_id,
            min(streak, 10),
            f"Streak bonus {streak}"
        )


# ============================================================
# HISTORY / JOBS
# ============================================================

def log_history(
    user_id,
    tool,
    status,
    filename="",
    credits=0
):
    con = db()

    con.execute("""
        INSERT INTO history(
            user_id,tool,status,filename,credits,created_at
        )
        VALUES(?,?,?,?,?,?)
    """, (
        user_id,
        tool,
        status,
        filename,
        credits,
        datetime.now().isoformat()
    ))

    con.commit()
    con.close()


def create_job(user_id, tool, filename):
    job = str(uuid.uuid4())[:12]

    con = db()

    con.execute("""
        INSERT INTO jobs(
            job_id,user_id,tool,filename,status,created_at
        )
        VALUES(?,?,?,?,?,?)
    """, (
        job,
        user_id,
        tool,
        filename,
        "processing",
        datetime.now().isoformat()
    ))

    con.commit()
    con.close()

    return job


def finish_job(job_id, status):
    con = db()

    con.execute("""
        UPDATE jobs
        SET status=?,finished_at=?
        WHERE job_id=?
    """, (
        status,
        datetime.now().isoformat(),
        job_id
    ))

    con.commit()
    con.close()


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard(user_id):
    return ReplyKeyboardMarkup([
        [
            tr(user_id, "pdf"),
            tr(user_id, "image")
        ],
        [
            tr(user_id, "premium"),
            tr(user_id, "account")
        ],
        [
            tr(user_id, "bonus"),
            tr(user_id, "refer")
        ],
        [
            tr(user_id, "redeem"),
            tr(user_id, "history")
        ],
        [
            tr(user_id, "support"),
            tr(user_id, "settings")
        ],
    ], resize_keyboard=True)


def pdf_keyboard(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📄 PDF → Word",
                callback_data="tool:PDF → Word"
            ),
            InlineKeyboardButton(
                "📝 PDF → TXT",
                callback_data="tool:PDF → TXT"
            ),
        ],
        [
            InlineKeyboardButton(
                "🖼️ PDF → JPG",
                callback_data="tool:PDF → JPG"
            ),
            InlineKeyboardButton(
                "🖼️ PDF → PNG",
                callback_data="tool:PDF → PNG"
            ),
        ],
        [
            InlineKeyboardButton(
                "🗜️ Compress PDF",
                callback_data="tool:Compress PDF"
            ),
            InlineKeyboardButton(
                "🔗 Merge PDF",
                callback_data="merge_start"
            ),
        ],
        [
            InlineKeyboardButton(
                "✂️ Split PDF",
                callback_data="tool:Split PDF"
            ),
            InlineKeyboardButton(
                "📑 Extract Pages",
                callback_data="tool:Extract Pages"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Rotate PDF",
                callback_data="tool:Rotate PDF"
            ),
            InlineKeyboardButton(
                "📐 Page Size",
                callback_data="tool:PDF Page Size"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔢 Page Numbers",
                callback_data="tool:Add Page Numbers"
            ),
            InlineKeyboardButton(
                "💧 Watermark",
                callback_data="tool:Add Watermark"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔐 Protect PDF",
                callback_data="tool:Protect PDF"
            ),
            InlineKeyboardButton(
                "🔓 Unlock PDF",
                callback_data="tool:Unlock PDF"
            ),
        ],
        [
            InlineKeyboardButton(
                "🧹 Remove Metadata",
                callback_data="tool:Remove Metadata"
            ),
            InlineKeyboardButton(
                "ℹ️ PDF Info",
                callback_data="tool:PDF Info"
            ),
        ],
        [
            InlineKeyboardButton(
                "📦 PDF → XPS",
                callback_data="tool:PDF → XPS"
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="home"
            )
        ]
    ])


def image_keyboard(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📄 JPG → PDF",
                callback_data="tool:JPG → PDF"
            ),
            InlineKeyboardButton(
                "📄 PNG → PDF",
                callback_data="tool:PNG → PDF"
            ),
        ],
        [
            InlineKeyboardButton(
                "📚 Multiple Images → PDF",
                callback_data="tool:Multiple Images → PDF"
            ),
        ],
        [
            InlineKeyboardButton(
                "🗜️ Compress Image",
                callback_data="tool:Compress Image"
            ),
            InlineKeyboardButton(
                "📏 Resize Image",
                callback_data="tool:Resize Image"
            ),
        ],
        [
            InlineKeyboardButton(
                "📐 Custom Resize",
                callback_data="tool:Custom Resize"
            ),
            InlineKeyboardButton(
                "🔄 JPG ↔ PNG",
                callback_data="tool:JPG ↔ PNG"
            ),
        ],
        [
            InlineKeyboardButton(
                "🌐 Image → WebP",
                callback_data="tool:Image → WebP"
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="home"
            ),
        ]
    ])


def settings_keyboard(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🌐 Language",
                callback_data="settings:language"
            )
        ],
        [
            InlineKeyboardButton(
                "🔔 Notifications",
                callback_data="settings:notifications"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="home"
            )
        ]
    ])


def language_keyboard():
    rows = []
    items = list(LANGUAGES.items())

    for i in range(0, len(items), 2):
        row = []

        for code, name in items[i:i + 2]:
            row.append(
                InlineKeyboardButton(
                    name,
                    callback_data=f"lang:{code}"
                )
            )

        rows.append(row)

    return InlineKeyboardMarkup(rows)


# ============================================================
# PREMIUM KEYBOARDS
# ============================================================

def premium_plan_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"💎 Weekly — ৳{WEEKLY_PRICE}",
                callback_data="premium:weekly"
            )
        ],
        [
            InlineKeyboardButton(
                f"👑 Monthly — ৳{MONTHLY_PRICE}",
                callback_data="premium:monthly"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 My Premium Status",
                callback_data="premium:status"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="home"
            )
        ]
    ])


def premium_payment_keyboard(plan):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📱 bKash",
                callback_data=f"payment:bkash:{plan}"
            ),
            InlineKeyboardButton(
                "📱 Nagad",
                callback_data=f"payment:nagad:{plan}"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="premium:menu"
            )
        ]
    ])


def admin_premium_request_keyboard(request_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ APPROVE",
                callback_data=f"premium_admin:approve:{request_id}"
            ),
            InlineKeyboardButton(
                "❌ REJECT",
                callback_data=f"premium_admin:reject:{request_id}"
            )
        ]
    ])


# ============================================================
# PROGRESS SYSTEM
# ============================================================

PROGRESS_DATA = {
    10: (
        "📥",
        "ফাইল গ্রহণ করা হচ্ছে...",
        "আপনার ফাইল নিরাপদে নেওয়া হয়েছে।"
    ),
    20: (
        "🔍",
        "ফাইল বিশ্লেষণ করা হচ্ছে...",
        "ডকুমেন্টের গঠন পরীক্ষা চলছে।"
    ),
    30: (
        "📑",
        "পেজ প্রস্তুত করা হচ্ছে...",
        "প্রয়োজনীয় ডেটা প্রস্তুত করা হচ্ছে।"
    ),
    40: (
        "⚙️",
        "প্রসেসিং শুরু হয়েছে...",
        "মূল কাজ এখন চলছে।"
    ),
    50: (
        "📊",
        "ডকুমেন্ট প্রসেস করা হচ্ছে...",
        "ডেটা রূপান্তর চলছে।"
    ),
    60: (
        "🛠️",
        "ফাইল আরও প্রসেস করা হচ্ছে...",
        "সিস্টেম কাজ চালিয়ে যাচ্ছে।"
    ),
    70: (
        "✨",
        "ফাইল অপ্টিমাইজ করা হচ্ছে...",
        "আউটপুট আরও সুন্দর করা হচ্ছে।"
    ),
    80: (
        "📦",
        "আউটপুট তৈরি করা হচ্ছে...",
        "ফাইনাল ফাইল প্রস্তুত হচ্ছে।"
    ),
    90: (
        "🚀",
        "ফাইনাল প্রস্তুতি চলছে...",
        "আর মাত্র শেষ ধাপ।"
    ),
    100: (
        "✅",
        "প্রসেসিং সম্পন্ন!",
        "আপনার ফাইল সফলভাবে প্রস্তুত।"
    ),
}


def progress_bar(percent):
    filled = percent // 10

    return (
        "█" * filled
        + "░" * (10 - filled)
    )


def progress_text(percent, filename=""):
    icon, title, desc = PROGRESS_DATA.get(
        percent,
        (
            "⚙️",
            "Processing...",
            "Please wait..."
        )
    )

    return f"""
╔══════════════════════════════╗
       {icon} RAFIM PDF PRO
╚══════════════════════════════╝

{icon} <b>{title}</b>

<code>{progress_bar(percent)}</code> <b>{percent}%</b>

📄 <b>File:</b> {filename[:45]}

━━━━━━━━━━━━━━━━━━━━
{desc}
━━━━━━━━━━━━━━━━━━━━

⚡ <i>Smart Processing Engine Active</i>
"""


async def progress_message(
    message,
    filename,
    stop_event=None
):
    for p in range(10, 101, 10):

        if stop_event and stop_event.is_set():
            break

        try:
            await message.edit_text(
                progress_text(
                    p,
                    filename
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        if p < 100:
            await asyncio.sleep(0.35)


# ============================================================
# TOOL COST
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
    "JPG → PDF": 1,
    "PNG → PDF": 1,
    "Multiple Images → PDF": 2,
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
}


# ============================================================
# PDF PROCESSOR
# ============================================================

def pdf_to_word(data):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    doc = Document()

    for page in pdf:
        text = page.get_text("text")

        if text.strip():
            doc.add_paragraph(text)

    out = io.BytesIO()

    doc.save(out)

    out.seek(0)

    return (
        out.getvalue(),
        "document.docx"
    )


def pdf_to_txt(data):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    text = []

    for i, page in enumerate(pdf, 1):
        text.append(
            f"\n--- PAGE {i} ---\n"
        )

        text.append(
            page.get_text("text")
        )

    return (
        "\n".join(text).encode("utf-8"),
        "document.txt"
    )


def pdf_to_images_zip(data, fmt="jpg"):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(
        zip_buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as z:

        for i, page in enumerate(pdf, 1):

            pix = page.get_pixmap(
                matrix=fitz.Matrix(
                    1.6,
                    1.6
                ),
                alpha=False
            )

            img = Image.frombytes(
                "RGB",
                [
                    pix.width,
                    pix.height
                ],
                pix.samples
            )

            b = io.BytesIO()

            if fmt.lower() == "png":
                img.save(
                    b,
                    "PNG"
                )

                name = f"page_{i}.png"

            else:
                img.save(
                    b,
                    "JPEG",
                    quality=90,
                    optimize=True
                )

                name = f"page_{i}.jpg"

            z.writestr(
                name,
                b.getvalue()
            )

    zip_buffer.seek(0)

    return (
        zip_buffer.getvalue(),
        "pdf_pages.zip"
    )


def compress_pdf(data, level="medium"):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    out = io.BytesIO()

    pdf.save(
        out,
        garbage=4,
        deflate=True,
        clean=True
    )

    return (
        out.getvalue(),
        "compressed.pdf"
    )


def merge_pdfs(datas):
    out = fitz.open()

    for data in datas:
        src = fitz.open(
            stream=data,
            filetype="pdf"
        )

        out.insert_pdf(src)
        src.close()

    b = io.BytesIO()

    out.save(b)
    out.close()

    return (
        b.getvalue(),
        "merged.pdf"
    )


def split_pdf(data):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(
        zip_buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as z:

        for i in range(len(pdf)):

            single = fitz.open()

            single.insert_pdf(
                pdf,
                from_page=i,
                to_page=i
            )

            b = io.BytesIO()

            single.save(b)
            single.close()

            z.writestr(
                f"page_{i + 1}.pdf",
                b.getvalue()
            )

    zip_buffer.seek(0)

    return (
        zip_buffer.getvalue(),
        "split_pages.zip"
    )


def extract_pages(
    data,
    start=1,
    end=None
):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    if end is None:
        end = start

    start = max(
        1,
        start
    )

    end = min(
        len(pdf),
        end
    )

    out = fitz.open()

    out.insert_pdf(
        pdf,
        from_page=start - 1,
        to_page=end - 1
    )

    b = io.BytesIO()

    out.save(b)
    out.close()

    return (
        b.getvalue(),
        f"pages_{start}-{end}.pdf"
    )


def rotate_pdf(data, angle=90):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    for page in pdf:
        page.set_rotation(
            (page.rotation + angle) % 360
        )

    b = io.BytesIO()

    pdf.save(b)
    pdf.close()

    return (
        b.getvalue(),
        "rotated.pdf"
    )


def resize_pdf_page(
    data,
    size="A4"
):
    sizes = {
        "A4": (
            595,
            842
        ),
        "A5": (
            420,
            595
        ),
        "LETTER": (
            612,
            792
        ),
    }

    w, h = sizes.get(
        size.upper(),
        sizes["A4"]
    )

    src = fitz.open(
        stream=data,
        filetype="pdf"
    )

    out = fitz.open()

    for page in src:
        new = out.new_page(
            width=w,
            height=h
        )

        new.show_pdf_page(
            fitz.Rect(
                0,
                0,
                w,
                h
            ),
            src,
            page.number
        )

    b = io.BytesIO()

    out.save(b)
    out.close()

    return (
        b.getvalue(),
        "resized_pages.pdf"
    )


def add_page_numbers(data):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    for i, page in enumerate(pdf, 1):
        page.insert_text(
            fitz.Point(
                page.rect.width / 2 - 10,
                page.rect.height - 25
            ),
            str(i),
            fontsize=10
        )

    b = io.BytesIO()

    pdf.save(b)
    pdf.close()

    return (
        b.getvalue(),
        "numbered.pdf"
    )


def add_watermark(
    data,
    text="RAFIM PDF PRO"
):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    for page in pdf:
        rect = page.rect

        page.insert_text(
            fitz.Point(
                rect.width / 2 - 80,
                rect.height / 2
            ),
            text,
            fontsize=24,
            rotate=45,
            color=(
                0.5,
                0.5,
                0.5
            ),
            overlay=True
        )

    b = io.BytesIO()

    pdf.save(b)
    pdf.close()

    return (
        b.getvalue(),
        "watermarked.pdf"
    )


def remove_metadata(data):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    pdf.set_metadata({})

    b = io.BytesIO()

    pdf.save(b)
    pdf.close()

    return (
        b.getvalue(),
        "clean_metadata.pdf"
    )


def pdf_info(data):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    meta = pdf.metadata or {}

    text = f"""
📊 PDF INFORMATION

📄 Pages: {len(pdf)}
📦 Size: {len(data) / 1024 / 1024:.2f} MB

Title: {meta.get("title") or "N/A"}
Author: {meta.get("author") or "N/A"}
Subject: {meta.get("subject") or "N/A"}
Creator: {meta.get("creator") or "N/A"}
Producer: {meta.get("producer") or "N/A"}
"""

    return text


def protect_pdf(
    data,
    password="123456"
):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    b = io.BytesIO()

    pdf.save(
        b,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=password,
        user_pw=password
    )

    pdf.close()

    return (
        b.getvalue(),
        "protected.pdf"
    )


def unlock_pdf(
    data,
    password
):
    pdf = fitz.open(
        stream=data,
        filetype="pdf"
    )

    if pdf.needs_pass:

        if not pdf.authenticate(password):
            raise ValueError(
                "Incorrect PDF password"
            )

    out = fitz.open()

    for page in pdf:
        out.insert_pdf(
            pdf,
            from_page=page.number,
            to_page=page.number
        )

    b = io.BytesIO()

    out.save(b)

    out.close()
    pdf.close()

    return (
        b.getvalue(),
        "unlocked.pdf"
    )


def image_to_pdf(data):
    img = Image.open(
        io.BytesIO(data)
    ).convert("RGB")

    b = io.BytesIO()

    img.save(
        b,
        "PDF",
        resolution=150
    )

    return (
        b.getvalue(),
        "image.pdf"
    )


def multiple_images_to_pdf(datas):
    images = []

    for data in datas:
        img = Image.open(
            io.BytesIO(data)
        ).convert("RGB")

        images.append(img)

    if not images:
        raise ValueError(
            "No images"
        )

    b = io.BytesIO()

    images[0].save(
        b,
        "PDF",
        save_all=True,
        append_images=images[1:]
    )

    return (
        b.getvalue(),
        "images.pdf"
    )


def pdf_to_xps(data):
    source = os.path.join(
        TEMP_DIR,
        f"{uuid.uuid4()}.pdf"
    )

    output = os.path.join(
        TEMP_DIR,
        f"{uuid.uuid4()}.xps"
    )

    with open(source, "wb") as f:
        f.write(data)

    try:
        subprocess.run(
            [
                "gs",
                "-sDEVICE=xps2",
                "-o",
                output,
                source
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120
        )

        if not os.path.exists(output):
            raise RuntimeError(
                "Ghostscript unavailable"
            )

        with open(
            output,
            "rb"
        ) as f:
            result = f.read()

        return (
            result,
            "document.xps"
        )

    finally:
        for p in [
            source,
            output
        ]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ============================================================
# IMAGE PROCESSOR
# ============================================================

def process_image(
    data,
    tool
):
    img = Image.open(
        io.BytesIO(data)
    )

    if tool == "Compress Image":
        img.thumbnail(
            (
                1920,
                1920
            )
        )

        out = io.BytesIO()

        img.convert("RGB").save(
            out,
            "JPEG",
            quality=70,
            optimize=True
        )

        return (
            out.getvalue(),
            "compressed.jpg"
        )

    if tool == "Resize Image":
        img.thumbnail(
            (
                1280,
                1280
            )
        )

        out = io.BytesIO()

        img.convert("RGB").save(
            out,
            "JPEG",
            quality=90
        )

        return (
            out.getvalue(),
            "resized.jpg"
        )

    if tool == "Custom Resize":
        img.thumbnail(
            (
                1280,
                1280
            )
        )

        out = io.BytesIO()

        img.convert("RGB").save(
            out,
            "JPEG",
            quality=90
        )

        return (
            out.getvalue(),
            "custom_resize.jpg"
        )

    if tool == "Image → WebP":
        out = io.BytesIO()

        img.save(
            out,
            "WEBP",
            quality=85
        )

        return (
            out.getvalue(),
            "image.webp"
        )

    if tool == "JPG ↔ PNG":
        out = io.BytesIO()

        if img.format == "PNG":
            img.convert("RGB").save(
                out,
                "JPEG",
                quality=92
            )

            return (
                out.getvalue(),
                "converted.jpg"
            )

        img.save(
            out,
            "PNG"
        )

        return (
            out.getvalue(),
            "converted.png"
        )

    if tool == "Convert PNG":
        out = io.BytesIO()

        img.save(
            out,
            "PNG"
        )

        return (
            out.getvalue(),
            "converted.png"
        )

    out = io.BytesIO()

    img.convert("RGB").save(
        out,
        "image.jpg",
        quality=92
    )

    return (
        out.getvalue(),
        "image.jpg"
    )


# ============================================================
# SEND FILE
# ============================================================

async def send_result(
    update,
    data,
    filename
):
    bio = io.BytesIO(data)
    bio.name = filename

    await update.effective_chat.send_document(
        document=bio,
        filename=filename
    )


# ============================================================
# FILE SIZE / CREDIT CHECK
# ============================================================

def max_file_mb(user_id):
    return (
        PREMIUM_FILE_LIMIT_MB
        if is_premium(user_id)
        else FREE_FILE_LIMIT_MB
    )


def check_file_size(
    user_id,
    size
):
    return size <= (
        max_file_mb(user_id)
        * 1024
        * 1024
    )


# ============================================================
# START / WELCOME
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    referred_by = None

    if context.args:
        arg = context.args[0].strip()

        if arg.startswith("R"):
            try:
                possible_id = int(
                    arg[1:]
                )

                if possible_id != user.id:
                    ref = get_user(
                        possible_id
                    )

                    if ref:
                        referred_by = possible_id

            except Exception:
                pass

    u, created = ensure_user(
        user,
        referred_by=referred_by
    )

    update_streak(
        user.id
    )

    if created:

        if referred_by:

            add_credits(
                referred_by,
                REFERRAL_REWARD,
                "Successful referral"
            )

            add_xp(
                referred_by,
                REFERRAL_XP
            )

            con = db()

            con.execute("""
                UPDATE users
                SET referral_count=referral_count+1,
                    referral_earned=referral_earned+?
                WHERE user_id=?
            """, (
                REFERRAL_REWARD,
                referred_by
            ))

            con.commit()
            con.close()

            try:
                await context.bot.send_message(
                    referred_by,
                    f"""🎯 <b>REFERRAL JOIN!</b>

👤 New User: {user.first_name}
🆔 ID: <code>{user.id}</code>

🎁 Reward: +{REFERRAL_REWARD} Credits
⭐ Referral XP: +{REFERRAL_XP}

🔥 Your referral system just got stronger!""",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

        try:
            con = db()

            total = con.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]

            con.close()

            await context.bot.send_message(
                ADMIN_ID,
                f"""🚨 <b>NEW USER DETECTED</b> 🚨

👤 <b>{user.first_name}</b>
🆔 <code>{user.id}</code>
🔗 @{user.username or "No username"}

📅 {datetime.now().strftime("%Y-%m-%d %H:%M")}

💳 Credits: {FREE_CREDITS}
💎 Premium: ❌
⭐ Level: 1
🔥 Streak: 1
👥 Referred By: {referred_by or "None"}

📊 Total Users: {total}""",
                parse_mode=ParseMode.HTML
            )

        except Exception:
            pass

    u = get_user(
        user.id
    )

    premium_text = (
        "✅"
        if is_premium(user.id)
        else "❌"
    )

    await update.message.reply_text(
        tr(
            user.id,
            "welcome",
            name=user.first_name or "User",
            credits=u["credits"],
            premium=premium_text,
            level=u["level"],
            streak=u["streak"],
            referrals=u["referral_count"]
        ),
        reply_markup=main_keyboard(
            user.id
        ),
        parse_mode=ParseMode.HTML
    )


# ============================================================
# BASIC COMMANDS
# ============================================================

async def menu(update, context):
    await update.message.reply_text(
        "🏠 <b>MAIN MENU</b>\n\n"
        "🔥 Choose your next action!",
        reply_markup=main_keyboard(
            update.effective_user.id
        ),
        parse_mode=ParseMode.HTML
    )


async def account(update, context):
    uid = update.effective_user.id
    u = get_user(uid)

    await update.message.reply_text(
        f"""👤 <b>YOUR ACCOUNT</b>

━━━━━━━━━━━━━━━━━━━━
🆔 ID: <code>{uid}</code>
👤 Name: {u["first_name"]}
🔗 Username: @{u["username"] or "none"}

💳 Credits: <b>{u["credits"]}</b>
💎 Premium: {"✅ ACTIVE" if is_premium(uid) else "❌ FREE"}

📅 Premium Until:
<code>{premium_expiry_text(uid)}</code>

⭐ XP: {u["xp"]}
🏆 Level: {u["level"]}
🔥 Streak: {u["streak"]}

👥 Referrals: {u["referral_count"]}
💰 Referral Earnings: {u["referral_earned"]}
━━━━━━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


async def bonus(update, context):
    uid = update.effective_user.id
    u = get_user(uid)

    today = date.today().isoformat()

    if u["last_bonus"] == today:
        await update.message.reply_text(
            "⏰ <b>DAILY BONUS ALREADY CLAIMED</b>\n\n"
            "🔥 Come back tomorrow for another reward!",
            parse_mode=ParseMode.HTML
        )
        return

    add_credits(
        uid,
        DAILY_BONUS,
        "Daily bonus"
    )

    add_xp(
        uid,
        10
    )

    con = db()

    con.execute(
        "UPDATE users SET last_bonus=? WHERE user_id=?",
        (
            today,
            uid
        )
    )

    con.commit()
    con.close()

    u = get_user(uid)

    await update.message.reply_text(
        f"""🎁 <b>DAILY DROP UNLOCKED!</b>

💰 +{DAILY_BONUS} Credits
⭐ +10 XP
🔥 Streak: {u["streak"]}

━━━━━━━━━━━━━━━━━━━━
💳 New Balance: {u["credits"]}
━━━━━━━━━━━━━━━━━━━━

🚀 KEEP COMING BACK!""",
        parse_mode=ParseMode.HTML
    )


async def refer(update, context):
    uid = update.effective_user.id
    u = get_user(uid)

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start={u['referral_code']}"
    )

    await update.message.reply_text(
        f"""╔══════════════════════════════╗
       👥 <b>REFERRAL ENGINE</b>
╚══════════════════════════════╝

🔥 SHARE → FRIEND JOINS → REWARD

🔗 <b>Your Referral Link:</b>
<code>{link}</code>

━━━━━━━━━━━━━━━━━━━━
👥 Total Referrals: {u["referral_count"]}
💰 Earned Credits: {u["referral_earned"]}
⭐ XP: {u["xp"]}
━━━━━━━━━━━━━━━━━━━━

🎯 MILESTONES

5  Referrals → 🎁 Bonus
10 Referrals → 🔥 Bonus
25 Referrals → 💎 Bonus
50 Referrals → 👑 Bonus

🚀 BUILD YOUR NETWORK!""",
        parse_mode=ParseMode.HTML
    )


async def referral_stats(update, context):
    await refer(
        update,
        context
    )


async def history_cmd(update, context):
    uid = update.effective_user.id

    con = db()

    rows = con.execute("""
        SELECT tool,status,filename,credits,created_at
        FROM history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 15
    """, (uid,)).fetchall()

    con.close()

    if not rows:
        await update.message.reply_text(
            "📜 <b>HISTORY EMPTY</b>\n\n"
            "Your processed files will appear here.",
            parse_mode=ParseMode.HTML
        )

        return

    text = (
        "📜 <b>RECENT HISTORY</b>\n\n"
    )

    for r in rows:

        icon = (
            "✅"
            if r["status"] == "success"
            else "❌"
        )

        text += (
            f"{icon} <b>{r['tool']}</b>\n"
            f"📄 {r['filename'][:35]}\n"
            f"💳 {r['credits']} credits\n"
            f"🕒 {r['created_at'][:16]}\n"
            f"━━━━━━━━━━━━━━\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


async def credit_history_cmd(
    update,
    context
):
    uid = update.effective_user.id

    con = db()

    rows = con.execute("""
        SELECT amount,reason,created_at
        FROM credit_history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 20
    """, (uid,)).fetchall()

    con.close()

    if not rows:
        await update.message.reply_text(
            "💳 Credit history is empty."
        )
        return

    text = (
        "💳 <b>CREDIT HISTORY</b>\n\n"
    )

    for r in rows:

        sign = (
            "+"
            if r["amount"] >= 0
            else ""
        )

        text += (
            f"{sign}{r['amount']} — "
            f"{r['reason']}\n"
            f"🕒 {r['created_at'][:16]}\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


# ============================================================
# PREMIUM USER MENU
# ============================================================

async def premium(update, context):
    uid = update.effective_user.id

    if is_premium(uid):
        await update.message.reply_text(
            f"""💎 <b>PREMIUM ACTIVE</b>

🎉 আপনার Premium বর্তমানে Active!

📅 Valid Until:
<code>{premium_expiry_text(uid)}</code>

🚀 Premium সুবিধা:
• 📦 Larger File Limit
• ⚡ Priority Processing
• 💎 Premium Access
• 🔥 Premium Badge
• 📚 Advanced Processing

👇 Premium status দেখতে পারেন:""",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📋 Premium Status",
                        callback_data="premium:status"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔄 Renew Premium",
                        callback_data="premium:menu"
                    )
                ]
            ]),
            parse_mode=ParseMode.HTML
        )

        return

    await update.message.reply_text(
        f"""╔══════════════════════════════╗
          💎 <b>PREMIUM POWER</b>
╚══════════════════════════════╝

🚀 FREE USER শুধু শুরু করেছে...
💎 PREMIUM USER পুরো POWER ব্যবহার করে!

━━━━━━━━━━━━━━━━━━━━
⚡ Priority Processing
📦 Larger File Limit
🎯 Premium Access
🔥 Premium Badge
📚 Advanced Processing
━━━━━━━━━━━━━━━━━━━━

💎 WEEKLY  → ৳{WEEKLY_PRICE}
👑 MONTHLY → ৳{MONTHLY_PRICE}

📱 Payment:
• bKash
• Nagad

👇 আপনার Plan নির্বাচন করুন:""",
        reply_markup=premium_plan_keyboard(),
        parse_mode=ParseMode.HTML
    )


async def premium_status_message(
    query
):
    uid = query.from_user.id
    u = get_user(uid)

    if is_premium(uid):
        text = f"""💎 <b>YOUR PREMIUM STATUS</b>

🟢 Status: <b>ACTIVE</b>

🆔 User ID:
<code>{uid}</code>

📅 Premium Until:
<code>{premium_expiry_text(uid)}</code>

📦 File Limit:
<b>{PREMIUM_FILE_LIMIT_MB} MB</b>

🚀 Premium is currently active."""
    else:
        text = f"""💎 <b>YOUR PREMIUM STATUS</b>

🔴 Status: <b>FREE</b>

📦 Free File Limit:
<b>{FREE_FILE_LIMIT_MB} MB</b>

💎 Weekly: ৳{WEEKLY_PRICE}
👑 Monthly: ৳{MONTHLY_PRICE}

👇 Upgrade করতে নিচের button ব্যবহার করুন."""

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💎 Upgrade / Renew",
                    callback_data="premium:menu"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode=ParseMode.HTML
    )


# ============================================================
# REDEEM
# ============================================================

async def redeem(update, context):
    context.user_data[
        "waiting_redeem"
    ] = True

    await update.message.reply_text(
        """🎟️ <b>REDEEM CENTER</b>

🔐 Send your redeem code now.

Example:
<code>WELCOME100</code>""",
        parse_mode=ParseMode.HTML
    )


async def handle_redeem_text(update):
    uid = update.effective_user.id

    code = update.message.text.strip().upper()

    con = db()

    row = con.execute(
        "SELECT * FROM redeem_codes WHERE code=?",
        (code,)
    ).fetchone()

    if not row:
        con.close()

        return await update.message.reply_text(
            "❌ <b>INVALID CODE</b>",
            parse_mode=ParseMode.HTML
        )

    if not row["enabled"]:
        con.close()

        return await update.message.reply_text(
            "⛔ This code is disabled."
        )

    if row["used_count"] >= row["max_uses"]:
        con.close()

        return await update.message.reply_text(
            "🚫 This code has reached its usage limit."
        )

    used = con.execute(
        "SELECT * FROM redemptions "
        "WHERE user_id=? AND code=?",
        (
            uid,
            code
        )
    ).fetchone()

    if used:
        con.close()

        return await update.message.reply_text(
            "⚠️ You have already used this code."
        )

    con.execute(
        "UPDATE redeem_codes "
        "SET used_count=used_count+1 "
        "WHERE code=?",
        (code,)
    )

    con.execute("""
        INSERT INTO redemptions(
            user_id,code,credits,created_at
        )
        VALUES(?,?,?,?)
    """, (
        uid,
        code,
        row["credits"],
        datetime.now().isoformat()
    ))

    con.commit()
    con.close()

    add_credits(
        uid,
        row["credits"],
        f"Redeem {code}"
    )

    await update.message.reply_text(
        f"""🎟️━━━━━━━━━━━━━━━━━━🎟️
       <b>CODE ACTIVATED!</b>
🎟️━━━━━━━━━━━━━━━━━━🎟️

💰 Reward: +{row["credits"]} Credits

🔥 YOUR BALANCE JUST GOT STRONGER!""",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# SETTINGS / LANGUAGE
# ============================================================

async def settings(update, context):
    uid = update.effective_user.id

    await update.message.reply_text(
        "⚙️ <b>SETTINGS CENTER</b>\n\n"
        "Customize your Rafim PDF Pro experience.",
        reply_markup=settings_keyboard(uid),
        parse_mode=ParseMode.HTML
    )


async def show_languages(query):
    await query.edit_message_text(
        "🌐 <b>SELECT YOUR LANGUAGE</b>\n\n"
        "Language will change the bot's menus, buttons and messages.",
        reply_markup=language_keyboard(),
        parse_mode=ParseMode.HTML
    )


# ============================================================
# SUPPORT
# ============================================================

async def support(update, context):
    await update.message.reply_text(
        f"""🆘 <b>SUPPORT CENTER</b>

Need help?

📩 Contact:
@{SUPPORT_USERNAME}

Or send your problem here and a support ticket will be created.""",
        parse_mode=ParseMode.HTML
    )

    context.user_data[
        "support_mode"
    ] = True


# ============================================================
# PDF / IMAGE MENU
# ============================================================

async def show_pdf_menu(update):
    await update.message.reply_text(
        """📕 <b>PDF POWER CENTER</b>

🔥 Choose a PDF operation:""",
        reply_markup=pdf_keyboard(
            update.effective_user.id
        ),
        parse_mode=ParseMode.HTML
    )


async def show_image_menu(update):
    await update.message.reply_text(
        """🖼️ <b>IMAGE POWER CENTER</b>

🔥 Choose an image operation:""",
        reply_markup=image_keyboard(
            update.effective_user.id
        ),
        parse_mode=ParseMode.HTML
    )


# ============================================================
# TOOL SELECTION
# ============================================================

async def select_tool(
    query,
    tool
):
    uid = query.from_user.id

    if tool not in TOOL_COST:
        return

    cost = TOOL_COST[tool]

    await query.edit_message_text(
        f"""⚡ <b>{tool}</b>

💳 Cost: {cost} Credits

📤 Send your file now.

━━━━━━━━━━━━━━━━━━━━
📦 Free Limit: {FREE_FILE_LIMIT_MB} MB
💎 Premium Limit: {PREMIUM_FILE_LIMIT_MB} MB
━━━━━━━━━━━━━━━━━━━━

🔥 RAFIM PROCESSING ENGINE READY!""",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# PREMIUM REQUEST CREATION
# ============================================================

async def create_premium_request(
    query,
    context,
    plan
):
    uid = query.from_user.id

    # Existing pending request check
    con = db()

    pending = con.execute("""
        SELECT *
        FROM premium_requests
        WHERE user_id=?
        AND status='pending'
        ORDER BY id DESC
        LIMIT 1
    """, (uid,)).fetchone()

    con.close()

    if pending:
        await query.edit_message_text(
            f"""⏳ <b>PREMIUM REQUEST ALREADY PENDING</b>

🆔 Request: #{pending["id"]}
📦 Plan: {pending["plan"].title()}
🔐 Transaction ID:
<code>{pending["transaction_id"]}</code>

⏳ Admin verification is still pending.

Please wait for the admin decision.""",
            parse_mode=ParseMode.HTML
        )
        return

    context.user_data[
        "premium_plan"
    ] = plan

    await query.edit_message_text(
        f"""💎 <b>{plan.title()} PREMIUM</b>

💰 Price:
<b>৳{WEEKLY_PRICE if plan == "weekly" else MONTHLY_PRICE}</b>

📱 Select your payment method:

👇 Choose bKash or Nagad:""",
        reply_markup=premium_payment_keyboard(plan),
        parse_mode=ParseMode.HTML
    )


# ============================================================
# CALLBACK
# ============================================================

async def callback_handler(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    uid = query.from_user.id

    if is_banned(uid):
        await query.answer(
            "🚫 Account restricted.",
            show_alert=True
        )
        return

    data = query.data

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    if data == "home":

        await query.message.edit_text(
            "🏠 <b>MAIN MENU</b>\n\n"
            "🔥 Welcome back!",
            parse_mode=ParseMode.HTML
        )

        await query.message.reply_text(
            "Choose an option:",
            reply_markup=main_keyboard(uid)
        )

        return

    # --------------------------------------------------------
    # LANGUAGE
    # --------------------------------------------------------

    if data == "settings:language":
        await show_languages(query)
        return

    if data.startswith("lang:"):

        lang = data.split(
            ":",
            1
        )[1]

        set_language(
            uid,
            lang
        )

        u = get_user(uid)

        await query.edit_message_text(
            f"✅ <b>{LANGUAGES.get(lang, 'English')}</b>\n\n"
            f"{tr(uid, 'saved')}",
            parse_mode=ParseMode.HTML
        )

        await query.message.reply_text(
            tr(
                uid,
                "welcome",
                name=query.from_user.first_name or "User",
                credits=u["credits"],
                premium="✅" if is_premium(uid) else "❌",
                level=u["level"],
                streak=u["streak"],
                referrals=u["referral_count"]
            ),
            reply_markup=main_keyboard(uid),
            parse_mode=ParseMode.HTML
        )

        return

    # --------------------------------------------------------
    # NOTIFICATIONS
    # --------------------------------------------------------

    if data == "settings:notifications":

        u = get_user(uid)

        new_value = (
            0
            if u["notifications"]
            else 1
        )

        con = db()

        con.execute(
            "UPDATE users SET notifications=? "
            "WHERE user_id=?",
            (
                new_value,
                uid
            )
        )

        con.commit()
        con.close()

        await query.edit_message_text(
            f"🔔 Notifications: "
            f"{'✅ ON' if new_value else '❌ OFF'}",
            reply_markup=settings_keyboard(uid)
        )

        return

    # ========================================================
    # PREMIUM MENU
    # ========================================================

    if data == "premium:menu":

        if is_premium(uid):
            await premium_status_message(
                query
            )
            return

        await query.edit_message_text(
            f"""💎 <b>PREMIUM POWER</b>

━━━━━━━━━━━━━━━━━━━━
⚡ Priority Processing
📦 Larger File Limit
🎯 Premium Access
🔥 Premium Badge
📚 Advanced Processing
━━━━━━━━━━━━━━━━━━━━

💎 Weekly: ৳{WEEKLY_PRICE}
👑 Monthly: ৳{MONTHLY_PRICE}

👇 Choose your plan:""",
            reply_markup=premium_plan_keyboard(),
            parse_mode=ParseMode.HTML
        )

        return

    # ========================================================
    # PREMIUM STATUS
    # ========================================================

    if data == "premium:status":

        await premium_status_message(
            query
        )

        return

    # ========================================================
    # PREMIUM PLAN
    # ========================================================

    if data == "premium:weekly":

        await create_premium_request(
            query,
            context,
            "weekly"
        )

        return

    if data == "premium:monthly":

        await create_premium_request(
            query,
            context,
            "monthly"
        )

        return

    # ========================================================
    # PAYMENT METHOD
    # ========================================================

    if data.startswith("payment:"):

        parts = data.split(":")

        if len(parts) != 3:
            return

        method = parts[1]
        plan = parts[2]

        if method == "bkash":
            number = BKASH_NUMBER
            method_name = "bKash"
        else:
            number = NAGAD_NUMBER
            method_name = "Nagad"

        price = (
            WEEKLY_PRICE
            if plan == "weekly"
            else MONTHLY_PRICE
        )

        context.user_data[
            "premium_plan"
        ] = plan

        context.user_data[
            "premium_payment_method"
        ] = method

        context.user_data[
            "premium_txn"
        ] = True

        await query.edit_message_text(
            f"""💎 <b>{plan.title()} PREMIUM</b>

📱 Payment Method:
<b>{method_name}</b>

💰 Amount:
<b>৳{price}</b>

━━━━━━━━━━━━━━━━━━━━

📲 Send Money to:
<code>{number}</code>

━━━━━━━━━━━━━━━━━━━━

⚠️ Payment করার পরে আপনার
<b>Transaction ID</b> পাঠান।

Example:
<code>TXN123456789</code>

👇 এখন Transaction ID পাঠান।""",
            parse_mode=ParseMode.HTML
        )

        return

    # ========================================================
    # ADMIN PREMIUM APPROVE / REJECT
    # ========================================================

    if data.startswith("premium_admin:"):

        if uid != ADMIN_ID:
            await query.answer(
                "⛔ Admin only.",
                show_alert=True
            )
            return

        parts = data.split(":")

        if len(parts) != 3:
            return

        action = parts[1]

        try:
            rid = int(parts[2])
        except Exception:
            await query.answer(
                "Invalid request ID.",
                show_alert=True
            )
            return

        con = db()

        row = con.execute(
            "SELECT * FROM premium_requests "
            "WHERE id=?",
            (rid,)
        ).fetchone()

        if not row:
            con.close()

            await query.answer(
                "❌ Request not found.",
                show_alert=True
            )

            return

        # Prevent duplicate decision
        if row["status"] != "pending":
            con.close()

            await query.answer(
                f"Already {row['status']}.",
                show_alert=True
            )

            try:
                await query.edit_message_reply_markup(
                    reply_markup=None
                )
            except Exception:
                pass

            return

        # ----------------------------------------------------
        # APPROVE
        # ----------------------------------------------------

        if action == "approve":

            days = (
                30
                if row["plan"] == "monthly"
                else 7
            )

            # If existing Premium is active,
            # extend from current expiry.
            user = get_user(
                row["user_id"]
            )

            base_date = datetime.now()

            if user and user["premium_until"]:
                try:
                    current_expiry = datetime.fromisoformat(
                        user["premium_until"]
                    )

                    if (
                        user["premium"]
                        and current_expiry > base_date
                    ):
                        base_date = current_expiry

                except Exception:
                    pass

            expiry = (
                base_date
                + timedelta(days=days)
            )

            reviewed_at = datetime.now().isoformat()

            con.execute("""
                UPDATE premium_requests
                SET status='approved',
                    reviewed_at=?
                WHERE id=?
                AND status='pending'
            """, (
                reviewed_at,
                rid
            ))

            con.execute("""
                UPDATE users
                SET premium=1,
                    premium_until=?
                WHERE user_id=?
            """, (
                expiry.isoformat(),
                row["user_id"]
            ))

            con.commit()
            con.close()

            await query.edit_message_text(
                f"""✅ <b>PREMIUM APPROVED</b>

🆔 Request: #{rid}
👤 User: <code>{row["user_id"]}</code>
📦 Plan: {row["plan"].title()}
🔐 TXN: <code>{row["transaction_id"]}</code>

💎 Premium: ACTIVE
📅 Until:
<code>{expiry.strftime("%Y-%m-%d %H:%M")}</code>

✅ User has been notified.""",
                parse_mode=ParseMode.HTML
            )

            try:
                await context.bot.send_message(
                    row["user_id"],
                    f"""🎉 <b>PREMIUM ACTIVATED!</b>

💎 Plan:
<b>{row["plan"].title()}</b>

🆔 Request:
<code>#{rid}</code>

📅 Premium Until:
<code>{expiry.strftime("%Y-%m-%d %H:%M")}</code>

📦 File Limit:
<b>{PREMIUM_FILE_LIMIT_MB} MB</b>

🚀 Welcome to RAFIM PDF PRO Premium!""",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "💎 Premium Status",
                                callback_data="premium:status"
                            )
                        ]
                    ])
                )
            except Exception:
                pass

            return

        # ----------------------------------------------------
        # REJECT
        # ----------------------------------------------------

        if action == "reject":

            reviewed_at = datetime.now().isoformat()

            con.execute("""
                UPDATE premium_requests
                SET status='rejected',
                    reviewed_at=?
                WHERE id=?
                AND status='pending'
            """, (
                reviewed_at,
                rid
            ))

            con.commit()
            con.close()

            await query.edit_message_text(
                f"""❌ <b>PREMIUM REQUEST REJECTED</b>

🆔 Request: #{rid}
👤 User: <code>{row["user_id"]}</code>
📦 Plan: {row["plan"].title()}
🔐 TXN: <code>{row["transaction_id"]}</code>

❌ User has been notified.""",
                parse_mode=ParseMode.HTML
            )

            try:
                await context.bot.send_message(
                    row["user_id"],
                    f"""❌ <b>PREMIUM REQUEST REJECTED</b>

🆔 Request:
<code>#{rid}</code>

📦 Plan:
{row["plan"].title()}

🔐 Transaction ID:
<code>{row["transaction_id"]}</code>

আপনার Premium request approve করা হয়নি।

Payment information সঠিক কিনা যাচাই করে আবার চেষ্টা করুন।""",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "💎 Try Again",
                                callback_data="premium:menu"
                            )
                        ]
                    ])
                )
            except Exception:
                pass

            return

    # ========================================================
    # MERGE
    # ========================================================

    if data == "merge_start":

        context.user_data[
            "merge_mode"
        ] = True

        context.user_data[
            "merge_files"
        ] = []

        await query.edit_message_text(
            """🔗 <b>MERGE PDF MODE</b>

Send multiple PDF files one by one.

When finished, send:
<code>/done</code>

🔥 All selected PDFs will be merged into one file.""",
            parse_mode=ParseMode.HTML
        )

        return

    # ========================================================
    # TOOLS
    # ========================================================

    if data.startswith("tool:"):

        tool = data.split(
            ":",
            1
        )[1]

        context.user_data[
            "selected_tool"
        ] = tool

        if tool == "Unlock PDF":
            context.user_data[
                "waiting_password"
            ] = True

        if tool == "Protect PDF":
            context.user_data[
                "waiting_password"
            ] = True

        if tool == "Add Watermark":
            context.user_data[
                "waiting_watermark"
            ] = True

        if tool == "Custom Resize":
            context.user_data[
                "waiting_resize"
            ] = True

        if tool == "Extract Pages":
            context.user_data[
                "waiting_pages"
            ] = True

        await query.edit_message_text(
            f"""⚡ <b>{tool}</b>

💳 Cost: {TOOL_COST.get(tool, 1)} Credits

📤 এখন আপনার ফাইল পাঠান।

🔥 RAFIM ENGINE READY!""",
            parse_mode=ParseMode.HTML
        )

        return


# ============================================================
# TEXT HANDLER
# ============================================================

async def text_handler(
    update,
    context
):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if is_banned(uid):
        await update.message.reply_text(
            tr(
                uid,
                "banned"
            )
        )
        return

    # --------------------------------------------------------
    # REDEEM
    # --------------------------------------------------------

    if context.user_data.get(
        "waiting_redeem"
    ):

        context.user_data[
            "waiting_redeem"
        ] = False

        await handle_redeem_text(
            update
        )

        return

    # --------------------------------------------------------
    # SUPPORT
    # --------------------------------------------------------

    if context.user_data.get(
        "support_mode"
    ):

        context.user_data[
            "support_mode"
        ] = False

        con = db()

        cur = con.execute("""
            INSERT INTO support_tickets(
                user_id,message,status,created_at
            )
            VALUES(?,?,?,?)
        """, (
            uid,
            text,
            "open",
            datetime.now().isoformat()
        ))

        ticket_id = cur.lastrowid

        con.commit()
        con.close()

        await update.message.reply_text(
            f"""🆘 <b>TICKET CREATED</b>

🎟️ Ticket ID: #{ticket_id}

✅ Your message has been sent to support.""",
            parse_mode=ParseMode.HTML
        )

        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"""🆘 <b>NEW SUPPORT TICKET</b>

🎟️ #{ticket_id}
🆔 {uid}

💬 {text}""",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # PREMIUM TRANSACTION ID
    # --------------------------------------------------------

    if context.user_data.get(
        "premium_txn"
    ):

        context.user_data[
            "premium_txn"
        ] = False

        plan = context.user_data.get(
            "premium_plan",
            "weekly"
        )

        payment_method = context.user_data.get(
            "premium_payment_method",
            "unknown"
        )

        # Prevent multiple pending requests
        con = db()

        existing = con.execute("""
            SELECT *
            FROM premium_requests
            WHERE user_id=?
            AND status='pending'
            LIMIT 1
        """, (uid,)).fetchone()

        if existing:
            con.close()

            await update.message.reply_text(
                f"""⏳ <b>REQUEST ALREADY PENDING</b>

🆔 Request: #{existing["id"]}

📦 Plan:
{existing["plan"].title()}

⏳ Admin verification is pending.

Please wait for the decision.""",
                parse_mode=ParseMode.HTML
            )

            return

        cur = con.execute("""
            INSERT INTO premium_requests(
                user_id,
                plan,
                transaction_id,
                status,
                created_at
            )
            VALUES(?,?,?,?,?)
        """, (
            uid,
            plan,
            text,
            "pending",
            datetime.now().isoformat()
        ))

        req_id = cur.lastrowid

        con.commit()
        con.close()

        price = (
            WEEKLY_PRICE
            if plan == "weekly"
            else MONTHLY_PRICE
        )

        await update.message.reply_text(
            f"""💎 <b>PREMIUM REQUEST RECEIVED</b>

🆔 Request:
<code>#{req_id}</code>

📦 Plan:
<b>{plan.title()}</b>

💰 Amount:
<b>৳{price}</b>

📱 Payment:
<b>{payment_method.upper()}</b>

🔐 Transaction:
<code>{text}</code>

⏳ Admin verification চলছে।

Approve হলে Premium automatically active হবে।""",
            parse_mode=ParseMode.HTML
        )

        # ----------------------------------------------------
        # ADMIN NOTIFICATION WITH BUTTONS
        # ----------------------------------------------------

        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"""💎 <b>NEW PREMIUM REQUEST</b>

━━━━━━━━━━━━━━━━━━━━

🆔 Request:
<code>#{req_id}</code>

👤 User:
<code>{uid}</code>

👤 Name:
{update.effective_user.first_name or "Unknown"}

🔗 Username:
@{update.effective_user.username or "none"}

📦 Plan:
<b>{plan.title()}</b>

💰 Price:
<b>৳{price}</b>

📱 Payment:
<b>{payment_method.upper()}</b>

🔐 Transaction ID:
<code>{text}</code>

📅 Submitted:
{datetime.now().strftime("%Y-%m-%d %H:%M")}

━━━━━━━━━━━━━━━━━━━━

👇 Admin action:""",
                parse_mode=ParseMode.HTML,
                reply_markup=admin_premium_request_keyboard(
                    req_id
                )
            )

        except Exception:
            pass

        return

    # --------------------------------------------------------
    # PASSWORD
    # --------------------------------------------------------

    if context.user_data.get(
        "waiting_password"
    ):

        context.user_data[
            "custom_password"
        ] = text

        context.user_data[
            "waiting_password"
        ] = False

        await update.message.reply_text(
            "🔐 Password saved. Now send the PDF."
        )

        return

    # --------------------------------------------------------
    # WATERMARK
    # --------------------------------------------------------

    if context.user_data.get(
        "waiting_watermark"
    ):

        context.user_data[
            "watermark"
        ] = text

        context.user_data[
            "waiting_watermark"
        ] = False

        await update.message.reply_text(
            "💧 Watermark saved. Now send the PDF."
        )

        return

    # --------------------------------------------------------
    # RESIZE
    # --------------------------------------------------------

    if context.user_data.get(
        "waiting_resize"
    ):

        context.user_data[
            "resize"
        ] = text

        context.user_data[
            "waiting_resize"
        ] = False

        await update.message.reply_text(
            "📐 Resize settings saved. "
            "Now send the image."
        )

        return

    # --------------------------------------------------------
    # PAGE RANGE
    # --------------------------------------------------------

    if context.user_data.get(
        "waiting_pages"
    ):

        m = re.match(
            r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$",
            text
        )

        if not m:
            await update.message.reply_text(
                "❌ Use format: <code>1-5</code>",
                parse_mode=ParseMode.HTML
            )
            return

        start_page = int(
            m.group(1)
        )

        end_page = int(
            m.group(2)
            or m.group(1)
        )

        context.user_data[
            "page_range"
        ] = (
            start_page,
            end_page
        )

        context.user_data[
            "waiting_pages"
        ] = False

        await update.message.reply_text(
            f"📑 Pages <b>{start_page}-{end_page}</b> selected.\n\n"
            "📤 Now send the PDF.",
            parse_mode=ParseMode.HTML
        )

        return

    # --------------------------------------------------------
    # MAIN MENU BUTTONS
    # --------------------------------------------------------

    if text == tr(uid, "pdf"):
        await show_pdf_menu(update)
        return

    if text == tr(uid, "image"):
        await show_image_menu(update)
        return

    if text == tr(uid, "premium"):
        await premium(
            update,
            context
        )
        return

    if text == tr(uid, "account"):
        await account(
            update,
            context
        )
        return

    if text == tr(uid, "bonus"):
        await bonus(
            update,
            context
        )
        return

    if text == tr(uid, "refer"):
        await refer(
            update,
            context
        )
        return

    if text == tr(uid, "redeem"):
        await redeem(
            update,
            context
        )
        return

    if text == tr(uid, "history"):
        await history_cmd(
            update,
            context
        )
        return

    if text == tr(uid, "support"):
        await support(
            update,
            context
        )
        return

    if text == tr(uid, "settings"):
        await settings(
            update,
            context
        )
        return

    await update.message.reply_text(
        "🤖 <b>COMMAND NOT RECOGNIZED</b>\n\n"
        "Use the buttons below.",
        reply_markup=main_keyboard(uid),
        parse_mode=ParseMode.HTML
    )


# ============================================================
# DOCUMENT HANDLER
# ============================================================

async def document_handler(
    update,
    context
):
    uid = update.effective_user.id

    if is_banned(uid):
        await update.message.reply_text(
            tr(
                uid,
                "banned"
            )
        )
        return

    doc = update.message.document

    if not doc:
        return

    filename = (
        doc.file_name
        or "file"
    )

    # --------------------------------------------------------
    # MERGE MODE
    # --------------------------------------------------------

    if context.user_data.get(
        "merge_mode"
    ):

        if not filename.lower().endswith(
            ".pdf"
        ):
            await update.message.reply_text(
                "❌ Merge mode accepts PDF files only."
            )
            return

        file = await doc.get_file()

        data = await file.download_as_bytearray()

        context.user_data[
            "merge_files"
        ].append(
            bytes(data)
        )

        count = len(
            context.user_data[
                "merge_files"
            ]
        )

        await update.message.reply_text(
            f"📎 PDF #{count} added.\n\n"
            "Send more PDFs or /done",
            parse_mode=ParseMode.HTML
        )

        return

    # --------------------------------------------------------
    # SIZE
    # --------------------------------------------------------

    size = doc.file_size or 0

    if not check_file_size(
        uid,
        size
    ):

        await update.message.reply_text(
            f"📦 File too large.\n\n"
            f"Your limit: "
            f"{max_file_mb(uid)} MB"
        )

        return

    # --------------------------------------------------------
    # TOOL
    # --------------------------------------------------------

    tool = context.user_data.get(
        "selected_tool"
    )

    if not tool:

        await update.message.reply_text(
            "📕 Please select a PDF/Image tool first."
        )

        return

    cost = TOOL_COST.get(
        tool,
        1
    )

    # Premium users don't consume credits
    if (
        not is_premium(uid)
        and get_user(uid)["credits"] < cost
    ):
        await update.message.reply_text(
            tr(
                uid,
                "no_credit"
            )
        )
        return

    status = await update.message.reply_text(
        progress_text(
            10,
            filename
        ),
        parse_mode=ParseMode.HTML
    )

    job_id = create_job(
        uid,
        tool,
        filename
    )

    try:

        file = await doc.get_file()

        await status.edit_text(
            progress_text(
                20,
                filename
            ),
            parse_mode=ParseMode.HTML
        )

        raw = bytes(
            await file.download_as_bytearray()
        )

        await status.edit_text(
            progress_text(
                30,
                filename
            ),
            parse_mode=ParseMode.HTML
        )

        await asyncio.sleep(
            0.25
        )

        if tool == "PDF → Word":
            result, out_name = pdf_to_word(raw)

        elif tool == "PDF → TXT":
            result, out_name = pdf_to_txt(raw)

        elif tool == "PDF → JPG":
            result, out_name = pdf_to_images_zip(
                raw,
                "jpg"
            )

        elif tool == "PDF → PNG":
            result, out_name = pdf_to_images_zip(
                raw,
                "png"
            )

        elif tool == "Compress PDF":
            result, out_name = compress_pdf(raw)

        elif tool == "Split PDF":
            result, out_name = split_pdf(raw)

        elif tool == "Extract Pages":

            start_page, end_page = (
                context.user_data.get(
                    "page_range",
                    (1, 1)
                )
            )

            result, out_name = extract_pages(
                raw,
                start_page,
                end_page
            )

        elif tool == "Rotate PDF":
            result, out_name = rotate_pdf(raw)

        elif tool == "PDF Page Size":
            result, out_name = resize_pdf_page(
                raw,
                "A4"
            )

        elif tool == "Add Page Numbers":
            result, out_name = add_page_numbers(raw)

        elif tool == "Add Watermark":

            watermark = context.user_data.get(
                "watermark",
                "RAFIM PDF PRO"
            )

            result, out_name = add_watermark(
                raw,
                watermark
            )

        elif tool == "Remove Metadata":
            result, out_name = remove_metadata(raw)

        elif tool == "PDF Info":

            info = pdf_info(raw)

            await status.edit_text(
                progress_text(
                    100,
                    filename
                ),
                parse_mode=ParseMode.HTML
            )

            await update.message.reply_text(
                info
            )

            finish_job(
                job_id,
                "success"
            )

            log_history(
                uid,
                tool,
                "success",
                filename,
                0
            )

            return

        elif tool == "Protect PDF":

            password = context.user_data.get(
                "custom_password",
                "123456"
            )

            result, out_name = protect_pdf(
                raw,
                password
            )

        elif tool == "Unlock PDF":

            password = context.user_data.get(
                "custom_password",
                ""
            )

            if not password:
                raise ValueError(
                    "Send the PDF password first."
                )

            result, out_name = unlock_pdf(
                raw,
                password
            )

        elif tool == "PDF → XPS":

            result, out_name = pdf_to_xps(
                raw
            )

        elif tool in [
            "JPG → PDF",
            "PNG → PDF"
        ]:

            result, out_name = image_to_pdf(
                raw
            )

        else:

            result, out_name = process_image(
                raw,
                tool
            )

        await status.edit_text(
            progress_text(
                100,
                filename
            ),
            parse_mode=ParseMode.HTML
        )

        if not is_premium(uid):

            remove_credits(
                uid,
                cost,
                f"Used {tool}"
            )

        add_xp(
            uid,
            XP_SUCCESS
        )

        log_history(
            uid,
            tool,
            "success",
            filename,
            cost
        )

        finish_job(
            job_id,
            "success"
        )

        await asyncio.sleep(
            0.3
        )

        await status.edit_text(
            f"""🎉 <b>PROCESSING COMPLETE!</b>

━━━━━━━━━━━━━━━━━━━━
📄 <b>Input:</b> {filename[:40]}
📦 <b>Output:</b> {out_name}
💳 <b>Cost:</b> {cost} Credits
⭐ <b>XP:</b> +{XP_SUCCESS}
━━━━━━━━━━━━━━━━━━━━

🔥 Your file is ready!
📥 Sending output now...""",
            parse_mode=ParseMode.HTML
        )

        await send_result(
            update,
            result,
            out_name
        )

    except Exception as e:

        finish_job(
            job_id,
            "failed"
        )

        log_history(
            uid,
            tool,
            "failed",
            filename,
            0
        )

        try:
            await status.edit_text(
                f"""🚨 <b>PROCESS INTERRUPTED</b>

😵 Something didn't go as planned.

🔍 Reason:
<code>{str(e)[:500]}</code>

━━━━━━━━━━━━━━━━━━━━
💡 Your credits were NOT charged.

🔄 Please try again.
━━━━━━━━━━━━━━━━━━━━""",
                parse_mode=ParseMode.HTML
            )

        except Exception:
            pass

    finally:

        context.user_data.pop(
            "selected_tool",
            None
        )


# ============================================================
# PHOTO HANDLER
# ============================================================

async def photo_handler(
    update,
    context
):
    uid = update.effective_user.id

    if is_banned(uid):
        return

    photo = update.message.photo[-1]

    tool = context.user_data.get(
        "selected_tool"
    )

    if not tool:

        await update.message.reply_text(
            "🖼️ Select an Image Tool first."
        )

        return

    cost = TOOL_COST.get(
        tool,
        1
    )

    u = get_user(uid)

    if (
        not is_premium(uid)
        and u["credits"] < cost
    ):

        await update.message.reply_text(
            tr(
                uid,
                "no_credit"
            )
        )

        return

    status = await update.message.reply_text(
        progress_text(
            10,
            "image.jpg"
        ),
        parse_mode=ParseMode.HTML
    )

    job_id = create_job(
        uid,
        tool,
        "image.jpg"
    )

    try:

        file = await photo.get_file()

        await status.edit_text(
            progress_text(
                20,
                "image.jpg"
            ),
            parse_mode=ParseMode.HTML
        )

        raw = bytes(
            await file.download_as_bytearray()
        )

        await status.edit_text(
            progress_text(
                30,
                "image.jpg"
            ),
            parse_mode=ParseMode.HTML
        )

        if tool in [
            "JPG → PDF",
            "PNG → PDF"
        ]:

            result, filename = image_to_pdf(
                raw
            )

        elif tool == "Multiple Images → PDF":

            context.user_data.setdefault(
                "image_batch",
                []
            )

            context.user_data[
                "image_batch"
            ].append(raw)

            await status.edit_text(
                "📚 <b>IMAGE BATCH MODE</b>\n\n"
                f"🖼️ Images collected: "
                f"{len(context.user_data['image_batch'])}\n\n"
                "Send more images or /doneimages",
                parse_mode=ParseMode.HTML
            )

            finish_job(
                job_id,
                "waiting"
            )

            return

        else:

            result, filename = process_image(
                raw,
                tool
            )

        await status.edit_text(
            progress_text(
                100,
                "image.jpg"
            ),
            parse_mode=ParseMode.HTML
        )

        if not is_premium(uid):

            remove_credits(
                uid,
                cost,
                f"Used {tool}"
            )

        add_xp(
            uid,
            XP_SUCCESS
        )

        log_history(
            uid,
            tool,
            "success",
            "image.jpg",
            cost
        )

        finish_job(
            job_id,
            "success"
        )

        await send_result(
            update,
            result,
            filename
        )

    except Exception as e:

        finish_job(
            job_id,
            "failed"
        )

        log_history(
            uid,
            tool,
            "failed",
            "image.jpg",
            0
        )

        await status.edit_text(
            f"""🚨 <b>IMAGE PROCESSING FAILED</b>

❌ {str(e)[:400]}

💳 Your credits were not charged.""",
            parse_mode=ParseMode.HTML
        )


# ============================================================
# MERGE DONE
# ============================================================

async def done_command(
    update,
    context
):
    uid = update.effective_user.id

    files = context.user_data.get(
        "merge_files",
        []
    )

    if len(files) < 2:

        await update.message.reply_text(
            "❌ Please send at least 2 PDF files."
        )

        return

    cost = TOOL_COST[
        "Merge PDF"
    ]

    if (
        not is_premium(uid)
        and get_user(uid)["credits"] < cost
    ):

        await update.message.reply_text(
            tr(
                uid,
                "no_credit"
            )
        )

        return

    status = await update.message.reply_text(
        progress_text(
            10,
            "merging PDFs"
        ),
        parse_mode=ParseMode.HTML
    )

    try:

        await status.edit_text(
            progress_text(
                40,
                "merging PDFs"
            ),
            parse_mode=ParseMode.HTML
        )

        result, filename = merge_pdfs(
            files
        )

        await status.edit_text(
            progress_text(
                100,
                "merged.pdf"
            ),
            parse_mode=ParseMode.HTML
        )

        if not is_premium(uid):

            remove_credits(
                uid,
                cost,
                "Merge PDF"
            )

        add_xp(
            uid,
            XP_SUCCESS
        )

        log_history(
            uid,
            "Merge PDF",
            "success",
            filename,
            cost
        )

        await send_result(
            update,
            result,
            filename
        )

    except Exception as e:

        await status.edit_text(
            f"🚨 Merge failed:\n"
            f"<code>{str(e)[:400]}</code>",
            parse_mode=ParseMode.HTML
        )

    finally:

        context.user_data.pop(
            "merge_mode",
            None
        )

        context.user_data.pop(
            "merge_files",
            None
        )


async def done_images(
    update,
    context
):
    uid = update.effective_user.id

    files = context.user_data.get(
        "image_batch",
        []
    )

    if not files:

        await update.message.reply_text(
            "❌ No images collected."
        )

        return

    result, filename = (
        multiple_images_to_pdf(
            files
        )
    )

    cost = TOOL_COST[
        "Multiple Images → PDF"
    ]

    if not is_premium(uid):

        if get_user(uid)["credits"] < cost:

            await update.message.reply_text(
                tr(
                    uid,
                    "no_credit"
                )
            )

            return

        remove_credits(
            uid,
            cost,
            "Multiple Images PDF"
        )

    add_xp(
        uid,
        XP_SUCCESS
    )

    log_history(
        uid,
        "Multiple Images → PDF",
        "success",
        filename,
        cost
    )

    await update.message.reply_text(
        "🎉 <b>IMAGE BATCH COMPLETE!</b>",
        parse_mode=ParseMode.HTML
    )

    await send_result(
        update,
        result,
        filename
    )

    context.user_data.pop(
        "image_batch",
        None
    )


# ============================================================
# ADMIN HELPERS
# ============================================================

def admin_only(func):

    async def wrapper(
        update,
        context
    ):

        if update.effective_user.id != ADMIN_ID:

            await update.message.reply_text(
                "⛔ Admin only."
            )

            return

        return await func(
            update,
            context
        )

    return wrapper


# ============================================================
# ADMIN PANEL
# ============================================================

@admin_only
async def admin_cmd(
    update,
    context
):
    await update.message.reply_text(
        """👑 <b>RAFIM ADMIN CENTER</b>

━━━━━━━━━━━━━━━━━━━━

👤 User:
/userinfo USER_ID
/searchuser USER_ID
/premiumusers

📊 Statistics:
/stats
/dailystats
/refstats
/leaderboard

💳 Credits:
/addcredits USER_ID AMOUNT
/removecredits USER_ID AMOUNT

💎 Premium:
/addpremium USER_ID DAYS
/premiumrequests
/approvepremium ID
/rejectpremium ID

🎟️ Redeem:
/createcode CODE CREDITS USES
/codes
/disablecode CODE

🚫 Security:
/ban USER_ID
/unban USER_ID

📢 Broadcast:
/broadcast
/broadcastpremium
/broadcastfree
/broadcaststatus
/cancelbroadcast

⚙️ Settings:
/adminsettings

━━━━━━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


@admin_only
async def stats_cmd(
    update,
    context
):
    con = db()

    users = con.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    premium_count = con.execute(
        "SELECT COUNT(*) FROM users "
        "WHERE premium=1"
    ).fetchone()[0]

    banned = con.execute(
        "SELECT COUNT(*) FROM users "
        "WHERE banned=1"
    ).fetchone()[0]

    jobs = con.execute(
        "SELECT COUNT(*) FROM history"
    ).fetchone()[0]

    success = con.execute(
        "SELECT COUNT(*) FROM history "
        "WHERE status='success'"
    ).fetchone()[0]

    failed = con.execute(
        "SELECT COUNT(*) FROM history "
        "WHERE status='failed'"
    ).fetchone()[0]

    pending = con.execute(
        "SELECT COUNT(*) FROM premium_requests "
        "WHERE status='pending'"
    ).fetchone()[0]

    con.close()

    await update.message.reply_text(
        f"""📊 <b>DETAILED ADMIN STATISTICS</b>

👥 Total Users: {users}
💎 Premium Users: {premium_count}
⏳ Pending Premium: {pending}
🚫 Banned Users: {banned}

⚙️ Total Jobs: {jobs}
✅ Successful: {success}
❌ Failed: {failed}

🔥 RAFIM PDF PRO ENGINE""",
        parse_mode=ParseMode.HTML
    )


@admin_only
async def daily_stats(
    update,
    context
):
    today = date.today().isoformat()

    con = db()

    new_users = con.execute(
        "SELECT COUNT(*) FROM users "
        "WHERE joined_at LIKE ?",
        (
            today + "%",
        )
    ).fetchone()[0]

    jobs = con.execute(
        "SELECT COUNT(*) FROM history "
        "WHERE created_at LIKE ?",
        (
            today + "%",
        )
    ).fetchone()[0]

    successful = con.execute(
        "SELECT COUNT(*) FROM history "
        "WHERE status='success' "
        "AND created_at LIKE ?",
        (
            today + "%",
        )
    ).fetchone()[0]

    con.close()

    await update.message.reply_text(
        f"""📈 <b>DAILY STATISTICS</b>

📅 {today}

👥 New Users: {new_users}
⚙️ Jobs: {jobs}
✅ Successful Jobs: {successful}

🚀 Daily engine report complete.""",
        parse_mode=ParseMode.HTML
    )


@admin_only
async def userinfo(
    update,
    context
):
    if not context.args:

        await update.message.reply_text(
            "Use: /userinfo USER_ID"
        )

        return

    try:
        uid = int(
            context.args[0]
        )
    except Exception:

        await update.message.reply_text(
            "Invalid user ID."
        )

        return

    u = get_user(uid)

    if not u:

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    await update.message.reply_text(
        f"""👤 <b>USER INFORMATION</b>

🆔 <code>{uid}</code>
👤 {u["first_name"]}
🔗 @{u["username"] or "none"}

💳 Credits: {u["credits"]}

💎 Premium:
{"✅ ACTIVE" if is_premium(uid) else "❌ FREE"}

📅 Premium Until:
<code>{premium_expiry_text(uid)}</code>

⭐ XP: {u["xp"]}
🏆 Level: {u["level"]}
🔥 Streak: {u["streak"]}

👥 Referrals: {u["referral_count"]}
💰 Referral Earnings: {u["referral_earned"]}

🌐 Language: {u["language"]}
🚫 Banned: {u["banned"]}""",
        parse_mode=ParseMode.HTML
    )


@admin_only
async def premiumusers_cmd(
    update,
    context
):
    con = db()

    rows = con.execute("""
        SELECT user_id,
               first_name,
               username,
               premium_until
        FROM users
        WHERE premium=1
        ORDER BY premium_until ASC
    """).fetchall()

    con.close()

    if not rows:

        await update.message.reply_text(
            "💎 No active Premium users."
        )

        return

    text = (
        "💎 <b>ACTIVE PREMIUM USERS</b>\n\n"
    )

    for i, r in enumerate(
        rows,
        1
    ):

        text += (
            f"{i}. "
            f"<b>{r['first_name'] or 'User'}</b>\n"
            f"🆔 <code>{r['user_id']}</code>\n"
            f"🔗 @{r['username'] or 'none'}\n"
            f"📅 Until: "
            f"<code>{r['premium_until'][:16] if r['premium_until'] else 'N/A'}</code>\n"
            f"━━━━━━━━━━━━━━\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


@admin_only
async def addcredits_cmd(
    update,
    context
):
    if len(context.args) < 2:

        await update.message.reply_text(
            "Use: /addcredits USER_ID AMOUNT"
        )

        return

    uid = int(
        context.args[0]
    )

    amount = int(
        context.args[1]
    )

    if not get_user(uid):

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    add_credits(
        uid,
        amount,
        "Admin credit"
    )

    await update.message.reply_text(
        f"✅ Added {amount} credits to {uid}."
    )


@admin_only
async def removecredits_cmd(
    update,
    context
):
    if len(context.args) < 2:

        await update.message.reply_text(
            "Use: /removecredits USER_ID AMOUNT"
        )

        return

    uid = int(
        context.args[0]
    )

    amount = int(
        context.args[1]
    )

    ok = remove_credits(
        uid,
        amount,
        "Admin deduction"
    )

    await update.message.reply_text(
        "✅ Credits removed."
        if ok
        else
        "❌ Insufficient credits."
    )


# ============================================================
# ADMIN MANUAL PREMIUM
# ============================================================

@admin_only
async def addpremium_cmd(
    update,
    context
):
    if len(context.args) < 2:

        await update.message.reply_text(
            "Use: /addpremium USER_ID DAYS"
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
            "❌ Invalid USER_ID or DAYS."
        )

        return

    user = get_user(uid)

    if not user:

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    base_date = datetime.now()

    if user["premium_until"]:

        try:
            old_expiry = datetime.fromisoformat(
                user["premium_until"]
            )

            if (
                user["premium"]
                and old_expiry > base_date
            ):
                base_date = old_expiry

        except Exception:
            pass

    expiry = (
        base_date
        + timedelta(days=days)
    )

    con = db()

    con.execute("""
        UPDATE users
        SET premium=1,
            premium_until=?
        WHERE user_id=?
    """, (
        expiry.isoformat(),
        uid
    ))

    con.commit()
    con.close()

    await update.message.reply_text(
        f"""💎 <b>PREMIUM ACTIVATED</b>

👤 User:
<code>{uid}</code>

⏱️ Added:
<b>{days} days</b>

📅 Premium Until:
<code>{expiry.strftime("%Y-%m-%d %H:%M")}</code>""",
        parse_mode=ParseMode.HTML
    )

    try:
        await context.bot.send_message(
            uid,
            f"""🎉 <b>PREMIUM ACTIVATED!</b>

👑 Admin has activated Premium for you.

⏱️ Duration:
<b>{days} days</b>

📅 Valid Until:
<code>{expiry.strftime("%Y-%m-%d %H:%M")}</code>

🚀 Enjoy RAFIM PDF PRO Premium!""",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ============================================================
# PREMIUM REQUEST ADMIN
# ============================================================

@admin_only
async def premiumrequests_cmd(
    update,
    context
):
    con = db()

    rows = con.execute("""
        SELECT *
        FROM premium_requests
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    con.close()

    if not rows:

        await update.message.reply_text(
            "💎 No pending premium requests."
        )

        return

    for r in rows:

        price = (
            WEEKLY_PRICE
            if r["plan"] == "weekly"
            else MONTHLY_PRICE
        )

        await update.message.reply_text(
            f"""💎 <b>PENDING PREMIUM REQUEST</b>

🆔 Request:
<code>#{r["id"]}</code>

👤 User:
<code>{r["user_id"]}</code>

📦 Plan:
<b>{r["plan"].title()}</b>

💰 Price:
<b>৳{price}</b>

🔐 Transaction:
<code>{r["transaction_id"]}</code>

📅 Created:
{r["created_at"][:16]}

👇 Choose action:""",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_premium_request_keyboard(
                r["id"]
            )
        )


@admin_only
async def approvepremium_cmd(
    update,
    context
):
    if not context.args:

        await update.message.reply_text(
            "Use: /approvepremium REQUEST_ID"
        )

        return

    try:
        rid = int(
            context.args[0]
        )
    except Exception:

        await update.message.reply_text(
            "❌ Invalid request ID."
        )

        return

    con = db()

    row = con.execute(
        "SELECT * FROM premium_requests "
        "WHERE id=?",
        (rid,)
    ).fetchone()

    if not row:

        con.close()

        await update.message.reply_text(
            "❌ Request not found."
        )

        return

    if row["status"] != "pending":

        con.close()

        await update.message.reply_text(
            f"⚠️ Request #{rid} is already "
            f"<b>{row['status']}</b>.",
            parse_mode=ParseMode.HTML
        )

        return

    days = (
        30
        if row["plan"] == "monthly"
        else 7
    )

    user = get_user(
        row["user_id"]
    )

    base_date = datetime.now()

    if user and user["premium_until"]:

        try:
            current_expiry = datetime.fromisoformat(
                user["premium_until"]
            )

            if (
                user["premium"]
                and current_expiry > base_date
            ):
                base_date = current_expiry

        except Exception:
            pass

    expiry = (
        base_date
        + timedelta(days=days)
    )

    reviewed_at = datetime.now().isoformat()

    con.execute("""
        UPDATE premium_requests
        SET status='approved',
            reviewed_at=?
        WHERE id=?
        AND status='pending'
    """, (
        reviewed_at,
        rid
    ))

    con.execute("""
        UPDATE users
        SET premium=1,
            premium_until=?
        WHERE user_id=?
    """, (
        expiry.isoformat(),
        row["user_id"]
    ))

    con.commit()
    con.close()

    await update.message.reply_text(
        f"""✅ <b>PREMIUM APPROVED</b>

🆔 Request: #{rid}
👤 User: <code>{row["user_id"]}</code>
📦 Plan: {row["plan"].title()}

📅 Premium Until:
<code>{expiry.strftime("%Y-%m-%d %H:%M")}</code>

🚀 User has been notified.""",
        parse_mode=ParseMode.HTML
    )

    try:
        await context.bot.send_message(
            row["user_id"],
            f"""🎉 <b>PREMIUM ACTIVATED!</b>

💎 Plan:
<b>{row["plan"].title()}</b>

📅 Valid Until:
<code>{expiry.strftime("%Y-%m-%d %H:%M")}</code>

🚀 Welcome to Premium Power!""",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


@admin_only
async def rejectpremium_cmd(
    update,
    context
):
    if not context.args:

        await update.message.reply_text(
            "Use: /rejectpremium REQUEST_ID"
        )

        return

    try:
        rid = int(
            context.args[0]
        )
    except Exception:

        await update.message.reply_text(
            "❌ Invalid request ID."
        )

        return

    con = db()

    row = con.execute(
        "SELECT * FROM premium_requests "
        "WHERE id=?",
        (rid,)
    ).fetchone()

    if not row:

        con.close()

        await update.message.reply_text(
            "❌ Request not found."
        )

        return

    if row["status"] != "pending":

        con.close()

        await update.message.reply_text(
            f"⚠️ Request #{rid} is already "
            f"<b>{row['status']}</b>.",
            parse_mode=ParseMode.HTML
        )

        return

    con.execute("""
        UPDATE premium_requests
        SET status='rejected',
            reviewed_at=?
        WHERE id=?
        AND status='pending'
    """, (
        datetime.now().isoformat(),
        rid
    ))

    con.commit()
    con.close()

    await update.message.reply_text(
        f"""❌ <b>PREMIUM REQUEST REJECTED</b>

🆔 Request: #{rid}
👤 User: <code>{row["user_id"]}</code>

❌ User has been notified.""",
        parse_mode=ParseMode.HTML
    )

    try:
        await context.bot.send_message(
            row["user_id"],
            f"""❌ <b>PREMIUM REQUEST REJECTED</b>

🆔 Request:
<code>#{rid}</code>

📦 Plan:
{row["plan"].title()}

আপনার Premium request approve করা হয়নি।

সঠিক payment information দিয়ে আবার চেষ্টা করতে পারেন।""",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ============================================================
# REDEEM ADMIN
# ============================================================

@admin_only
async def createcode_cmd(
    update,
    context
):
    if len(context.args) < 3:

        await update.message.reply_text(
            "Use: /createcode CODE CREDITS USES"
        )

        return

    code = context.args[0].upper()
    credits = int(context.args[1])
    uses = int(context.args[2])

    con = db()

    try:

        con.execute("""
            INSERT INTO redeem_codes(
                code,credits,max_uses,created_at
            )
            VALUES(?,?,?,?)
        """, (
            code,
            credits,
            uses,
            datetime.now().isoformat()
        ))

        con.commit()

        await update.message.reply_text(
            f"""🎟️ <b>CODE CREATED</b>

🔐 {code}
💰 Credits: {credits}
👥 Uses: {uses}""",
            parse_mode=ParseMode.HTML
        )

    except sqlite3.IntegrityError:

        await update.message.reply_text(
            "❌ Code already exists."
        )

    finally:
        con.close()


@admin_only
async def codes_cmd(
    update,
    context
):
    con = db()

    rows = con.execute(
        "SELECT * FROM redeem_codes "
        "ORDER BY created_at DESC"
    ).fetchall()

    con.close()

    if not rows:

        await update.message.reply_text(
            "No redeem codes."
        )

        return

    text = (
        "🎟️ <b>REDEEM CODES</b>\n\n"
    )

    for r in rows:

        text += (
            f"🔐 {r['code']}\n"
            f"💰 {r['credits']}\n"
            f"👥 {r['used_count']}/{r['max_uses']}\n"
            f"Status: "
            f"{'✅' if r['enabled'] else '❌'}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


@admin_only
async def disablecode_cmd(
    update,
    context
):
    if not context.args:

        await update.message.reply_text(
            "Use: /disablecode CODE"
        )

        return

    code = context.args[0].upper()

    con = db()

    con.execute(
        "UPDATE redeem_codes "
        "SET enabled=0 "
        "WHERE code=?",
        (code,)
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        f"⛔ Code {code} disabled."
    )


# ============================================================
# BAN / UNBAN
# ============================================================

@admin_only
async def ban_cmd(
    update,
    context
):
    if not context.args:

        return await update.message.reply_text(
            "Use: /ban USER_ID"
        )

    uid = int(
        context.args[0]
    )

    con = db()

    con.execute(
        "UPDATE users SET banned=1 "
        "WHERE user_id=?",
        (uid,)
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        f"🚫 User {uid} banned."
    )


@admin_only
async def unban_cmd(
    update,
    context
):
    if not context.args:

        return await update.message.reply_text(
            "Use: /unban USER_ID"
        )

    uid = int(
        context.args[0]
    )

    con = db()

    con.execute(
        "UPDATE users SET banned=0 "
        "WHERE user_id=?",
        (uid,)
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        f"✅ User {uid} unbanned."
    )


# ============================================================
# LEADERBOARDS
# ============================================================

@admin_only
async def leaderboard_cmd(
    update,
    context
):
    con = db()

    rows = con.execute("""
        SELECT first_name,
               username,
               referral_count
        FROM users
        ORDER BY referral_count DESC
        LIMIT 10
    """).fetchall()

    con.close()

    text = (
        "🏆 <b>REFERRAL LEADERBOARD</b>\n\n"
    )

    for i, r in enumerate(
        rows,
        1
    ):

        text += (
            f"{i}. {r['first_name']} — "
            f"{r['referral_count']} referrals\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


@admin_only
async def refstats_cmd(
    update,
    context
):
    con = db()

    row = con.execute("""
        SELECT
            SUM(referral_count),
            SUM(referral_earned)
        FROM users
    """).fetchone()

    con.close()

    await update.message.reply_text(
        f"""👥 <b>REFERRAL STATISTICS</b>

👥 Total Successful Referrals:
{row[0] or 0}

💰 Total Referral Rewards:
{row[1] or 0} Credits""",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# BROADCAST
# ============================================================

async def run_broadcast(
    bot,
    mode,
    message,
    admin_id
):
    con = db()

    if mode == "premium":

        rows = con.execute(
            "SELECT user_id FROM users "
            "WHERE premium=1 AND banned=0"
        ).fetchall()

    elif mode == "free":

        rows = con.execute(
            "SELECT user_id FROM users "
            "WHERE premium=0 AND banned=0"
        ).fetchall()

    else:

        rows = con.execute(
            "SELECT user_id FROM users "
            "WHERE banned=0"
        ).fetchall()

    cur = con.execute("""
        INSERT INTO broadcast_jobs(
            admin_id,mode,message,total,status,created_at
        )
        VALUES(?,?,?,?,?,?)
    """, (
        admin_id,
        mode,
        message,
        len(rows),
        "running",
        datetime.now().isoformat()
    ))

    job_id = cur.lastrowid

    con.commit()
    con.close()

    sent = 0
    failed = 0

    for r in rows:

        try:

            await bot.send_message(
                r["user_id"],
                message,
                parse_mode=ParseMode.HTML
            )

            sent += 1

        except Exception:

            failed += 1

        await asyncio.sleep(
            0.05
        )

        con = db()

        con.execute("""
            UPDATE broadcast_jobs
            SET sent=?,failed=?
            WHERE id=?
        """, (
            sent,
            failed,
            job_id
        ))

        con.commit()
        con.close()

    con = db()

    con.execute("""
        UPDATE broadcast_jobs
        SET status='completed',
            finished_at=?
        WHERE id=?
    """, (
        datetime.now().isoformat(),
        job_id
    ))

    con.commit()
    con.close()


@admin_only
async def broadcast(
    update,
    context
):
    context.user_data[
        "broadcast_mode"
    ] = "all"

    await update.message.reply_text(
        """📢 <b>BROADCAST CENTER</b>

Send the message you want to broadcast.

🔥 It will be sent to all non-banned users.""",
        parse_mode=ParseMode.HTML
    )


@admin_only
async def broadcastpremium(
    update,
    context
):
    context.user_data[
        "broadcast_mode"
    ] = "premium"

    await update.message.reply_text(
        "💎 Send the Premium broadcast message."
    )


@admin_only
async def broadcastfree(
    update,
    context
):
    context.user_data[
        "broadcast_mode"
    ] = "free"

    await update.message.reply_text(
        "👤 Send the Free User broadcast message."
    )


@admin_only
async def broadcaststatus(
    update,
    context
):
    con = db()

    row = con.execute("""
        SELECT *
        FROM broadcast_jobs
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    con.close()

    if not row:

        await update.message.reply_text(
            "📢 No broadcast jobs yet."
        )

        return

    await update.message.reply_text(
        f"""📊 <b>BROADCAST STATUS</b>

🆔 Job: #{row['id']}
📡 Mode: {row['mode']}
📦 Total: {row['total']}
✅ Sent: {row['sent']}
❌ Failed: {row['failed']}
⚙️ Status: {row['status']}""",
        parse_mode=ParseMode.HTML
    )


@admin_only
async def cancelbroadcast(
    update,
    context
):
    con = db()

    con.execute("""
        UPDATE broadcast_jobs
        SET status='cancelled'
        WHERE status='running'
    """)

    con.commit()
    con.close()

    await update.message.reply_text(
        "⏹️ Active broadcast marked as cancelled."
    )


# ============================================================
# BROADCAST TEXT HANDLER
# ============================================================

async def broadcast_text_handler(
    update,
    context
):
    uid = update.effective_user.id

    if uid != ADMIN_ID:
        return

    mode = context.user_data.get(
        "broadcast_mode"
    )

    if not mode:
        return

    context.user_data.pop(
        "broadcast_mode",
        None
    )

    await update.message.reply_text(
        "📡 <b>BROADCAST STARTED!</b>",
        parse_mode=ParseMode.HTML
    )

    asyncio.create_task(
        run_broadcast(
            context.bot,
            mode,
            update.message.text,
            uid
        )
    )


# ============================================================
# ADMIN SETTINGS
# ============================================================

@admin_only
async def adminsettings(
    update,
    context
):
    await update.message.reply_text(
        f"""⚙️ <b>ADMIN SETTINGS</b>

💰 Referral Reward: {REFERRAL_REWARD}
🎁 Daily Bonus: {DAILY_BONUS}
⭐ XP Success: {XP_SUCCESS}

💎 Weekly Premium: ৳{WEEKLY_PRICE}
👑 Monthly Premium: ৳{MONTHLY_PRICE}

📱 bKash:
<code>{BKASH_NUMBER}</code>

📱 Nagad:
<code>{NAGAD_NUMBER}</code>

📦 Free File Limit:
{FREE_FILE_LIMIT_MB} MB

📦 Premium File Limit:
{PREMIUM_FILE_LIMIT_MB} MB

🌐 Languages: {len(LANGUAGES)}
🛠️ PDF Tools: Active
🖼️ Image Tools: Active
👥 Referral System: Active
💎 Premium System: Active
🎟️ Redeem System: Active
📢 Broadcast: Active
🔥 XP System: Active
📊 Statistics: Active""",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# HELP / ABOUT / STATUS
# ============================================================

async def help_cmd(
    update,
    context
):
    await update.message.reply_text(
        """❓ <b>RAFIM PDF PRO HELP</b>

📕 PDF Tools
🖼️ Image Tools
💎 Premium
👥 Referral
🎁 Daily Bonus
🎟️ Redeem
📜 History
⭐ XP & Level
🔥 Daily Streak
🌐 Multi-language
🆘 Support

📤 Send a file after selecting a tool.

🔥 Fast. Smart. Powerful.""",
        parse_mode=ParseMode.HTML
    )


async def about_cmd(
    update,
    context
):
    await update.message.reply_text(
        """ℹ️ <b>RAFIM PDF PRO</b>

🚀 Professional Telegram file-processing system.

📕 PDF Processing
🖼️ Image Processing
💎 Premium
👥 Referral
🎁 Rewards
🎟️ Redeem
📊 Admin System
🌐 Multi-language

⚡ Built for fast file processing.""",
        parse_mode=ParseMode.HTML
    )


async def status_cmd(
    update,
    context
):
    await update.message.reply_text(
        """🟢 <b>SYSTEM ONLINE</b>

🤖 Bot: ONLINE
📦 PDF Engine: ONLINE
🖼️ Image Engine: ONLINE
💾 Database: ONLINE
🌐 Language Engine: ONLINE
👥 Referral Engine: ONLINE
💎 Premium Engine: ONLINE
📢 Broadcast Engine: ONLINE

🔥 RAFIM PDF PRO IS READY!""",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# COMMAND SETUP
# ============================================================

async def setup_commands(app):

    await app.bot.set_my_commands([
        (
            "start",
            "Start bot"
        ),
        (
            "menu",
            "Main menu"
        ),
        (
            "premium",
            "Premium"
        ),
        (
            "account",
            "My account"
        ),
        (
            "bonus",
            "Daily bonus"
        ),
        (
            "refer",
            "Refer & Earn"
        ),
        (
            "redeem",
            "Redeem code"
        ),
        (
            "history",
            "History"
        ),
        (
            "help",
            "Help"
        ),
        (
            "about",
            "About"
        ),
        (
            "status",
            "Status"
        ),
        (
            "admin",
            "Admin panel"
        ),
    ])


# ============================================================
# MAIN
# ============================================================

async def post_init(application):
    await setup_commands(
        application
    )

    # Start automatic Premium expiry watcher
    application.create_task(
        premium_expiry_watcher(
            application
        )
    )


def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ========================================================
    # COMMANDS
    # ========================================================

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
            premium
        )
    )

    application.add_handler(
        CommandHandler(
            "account",
            account
        )
    )

    application.add_handler(
        CommandHandler(
            "bonus",
            bonus
        )
    )

    application.add_handler(
        CommandHandler(
            "refer",
            refer
        )
    )

    application.add_handler(
        CommandHandler(
            "referrals",
            referral_stats
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
            history_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "credits",
            credit_history_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "about",
            about_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_cmd
        )
    )

    # ========================================================
    # MERGE
    # ========================================================

    application.add_handler(
        CommandHandler(
            "done",
            done_command
        )
    )

    application.add_handler(
        CommandHandler(
            "doneimages",
            done_images
        )
    )

    # ========================================================
    # ADMIN
    # ========================================================

    application.add_handler(
        CommandHandler(
            "admin",
            admin_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "userinfo",
            userinfo
        )
    )

    application.add_handler(
        CommandHandler(
            "searchuser",
            userinfo
        )
    )

    application.add_handler(
        CommandHandler(
            "premiumusers",
            premiumusers_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "dailystats",
            daily_stats
        )
    )

    application.add_handler(
        CommandHandler(
            "refstats",
            refstats_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "leaderboard",
            leaderboard_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "addcredits",
            addcredits_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "removecredits",
            removecredits_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "addpremium",
            addpremium_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "premiumrequests",
            premiumrequests_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "approvepremium",
            approvepremium_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "rejectpremium",
            rejectpremium_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "createcode",
            createcode_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "codes",
            codes_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "disablecode",
            disablecode_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            ban_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            unban_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcastpremium",
            broadcastpremium
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcastfree",
            broadcastfree
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcaststatus",
            broadcaststatus
        )
    )

    application.add_handler(
        CommandHandler(
            "cancelbroadcast",
            cancelbroadcast
        )
    )

    application.add_handler(
        CommandHandler(
            "adminsettings",
            adminsettings
        )
    )

    # ========================================================
    # CALLBACK
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # ========================================================
    # FILES
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler
        )
    )

    # ========================================================
    # BROADCAST
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.User(ADMIN_ID),
            broadcast_text_handler
        ),
        group=1
    )

    # ========================================================
    # NORMAL TEXT
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_handler
        )
    )

    print(
        "==================================="
    )
    print(
        " RAFIM PDF PRO"
    )
    print(
        " BOT STARTED"
    )
    print(
        " MULTI-LANGUAGE ENGINE: ON"
    )
    print(
        " PDF ENGINE: ON"
    )
    print(
        " IMAGE ENGINE: ON"
    )
    print(
        " REFERRAL ENGINE: ON"
    )
    print(
        " PREMIUM ENGINE: ON"
    )
    print(
        " PREMIUM APPROVE/REJECT: ON"
    )
    print(
        " PREMIUM EXPIRY WATCHER: ON"
    )
    print(
        " ADMIN ENGINE: ON"
    )
    print(
        "==================================="
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
