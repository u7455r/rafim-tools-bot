# bot.py
# ============================================================
# RAFIM TOOLS BOT
# API-Free Utility + Premium + Credits + Referral + Redeem
# Audio / Video / FFmpeg removed
#
# Render Environment Variables ONLY:
# BOT_TOKEN
# ADMIN_ID
# SUPPORT_USERNAME
# ============================================================

import os
import io
import re
import ast
import json
import base64
import uuid
import math
import random
import string
import shutil
import sqlite3
import asyncio
import secrets
import hashlib
import tempfile
import subprocess
import time
from collections import deque
from datetime import datetime, date, timedelta
from functools import wraps
from urllib.parse import quote, unquote

import fitz
import qrcode
import yt_dlp

from PIL import Image, ImageOps, ImageEnhance, ImageDraw, ImageFont
from docx import Document
from flask import Flask

from cryptography.fernet import Fernet

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ApplicationHandlerStop,
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip())
except Exception:
    ADMIN_ID = 0

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "rafimhossen").strip().lstrip("@")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

if ADMIN_ID <= 0:
    raise RuntimeError("ADMIN_ID environment variable is missing or invalid.")

DB_FILE = "rafim_tools.db"
TEMP_DIR = "tmp_files"

os.makedirs(TEMP_DIR, exist_ok=True)

# সব Default value bot.py-এর ভিতরে
FREE_CREDITS = 10
DAILY_BONUS = 3
REFERRAL_REWARD = 5
REFERRAL_XP = 20
XP_SUCCESS = 5

FREE_FILE_LIMIT_MB = 20
PREMIUM_FILE_LIMIT_MB = 100

WEEKLY_PRICE = 50
MONTHLY_PRICE = 150

# Payment number code-এর ভিতরে রাখা হয়েছে।
# নিজের নম্বর চাইলে শুধু এখানেই পরিবর্তন করবে।
NAGAD_NUMBER = "01726836941"


# ============================================================
# FLASK HEALTH SERVER FOR RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Rafim Tools Bot is Running ✅"


@app.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# ============================================================
# DATABASE
# ============================================================

DB_LOCK = asyncio.Lock()


def db():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            language TEXT DEFAULT 'bn',
            credits INTEGER DEFAULT 10,
            xp INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_daily TEXT DEFAULT '',
            last_seen TEXT DEFAULT '',
            referred_by INTEGER DEFAULT 0,
            referral_count INTEGER DEFAULT 0,
            premium INTEGER DEFAULT 0,
            premium_until TEXT DEFAULT '',
            banned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tool TEXT,
            status TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS credit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            credits INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            user_id INTEGER,
            created_at TEXT,
            UNIQUE(code, user_id)
        );

        CREATE TABLE IF NOT EXISTS premium_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS broadcast_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            target TEXT,
            message TEXT,
            status TEXT DEFAULT 'running',
            total INTEGER DEFAULT 0,
            sent INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS broadcast_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            user_id INTEGER,
            error TEXT DEFAULT '',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            notifications INTEGER DEFAULT 1,
            compact INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS admin_settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS downloader_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            url TEXT,
            title TEXT DEFAULT '',
            kind TEXT DEFAULT 'video',
            quality TEXT DEFAULT '',
            filename TEXT DEFAULT '',
            status TEXT DEFAULT 'queued',
            error TEXT DEFAULT '',
            created_at TEXT,
            completed_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS downloader_jobs (
            job_id TEXT PRIMARY KEY,
            user_id INTEGER,
            url TEXT,
            title TEXT DEFAULT '',
            kind TEXT DEFAULT 'video',
            quality TEXT DEFAULT '',
            status TEXT DEFAULT 'queued',
            progress REAL DEFAULT 0,
            downloaded INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0,
            speed REAL DEFAULT 0,
            eta INTEGER DEFAULT 0,
            filename TEXT DEFAULT '',
            error TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS direct_chat_sessions (
            admin_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )

    conn.commit()
    conn.close()


# ============================================================
# COMMON
# ============================================================

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return date.today().isoformat()


def fmt_num(n):
    return f"{int(n):,}"


def is_admin(user_id):
    return int(user_id) == ADMIN_ID


def get_user(user_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    return row


def ensure_user(tg_user, referral_id=0):
    uid = tg_user.id
    existing = get_user(uid)

    conn = db()

    if not existing:
        referred_by = 0

        if referral_id and referral_id != uid:
            ref_user = conn.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (referral_id,),
            ).fetchone()

            if ref_user:
                referred_by = referral_id

        conn.execute(
            """
            INSERT INTO users
            (user_id, username, first_name, language, credits,
             xp, streak, last_daily, last_seen, referred_by,
             referral_count, premium, premium_until, banned,
             created_at, updated_at)
            VALUES (?, ?, ?, 'bn', ?, 0, 0, '', ?, ?, 0, 0, '', 0, ?, ?)
            """,
            (
                uid,
                tg_user.username or "",
                tg_user.first_name or "",
                FREE_CREDITS,
                now(),
                referred_by,
                now(),
                now(),
            ),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO user_settings(user_id)
            VALUES (?)
            """,
            (uid,),
        )

        if referred_by:
            conn.execute(
                """
                UPDATE users
                SET referral_count=referral_count+1
                WHERE user_id=?
                """,
                (referred_by,),
            )

            conn.execute(
                """
                UPDATE users
                SET credits=credits+?, xp=xp+?
                WHERE user_id=?
                """,
                (
                    REFERRAL_REWARD,
                    REFERRAL_XP,
                    referred_by,
                ),
            )

            conn.execute(
                """
                INSERT INTO credit_history
                (user_id, amount, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    referred_by,
                    REFERRAL_REWARD,
                    "Referral Bonus",
                    now(),
                ),
            )

    else:
        conn.execute(
            """
            UPDATE users
            SET username=?, first_name=?, last_seen=?, updated_at=?
            WHERE user_id=?
            """,
            (
                tg_user.username or "",
                tg_user.first_name or "",
                now(),
                now(),
                uid,
            ),
        )

    conn.commit()
    conn.close()


def add_credits(user_id, amount, reason="Admin"):
    conn = db()

    conn.execute(
        "UPDATE users SET credits=credits+? WHERE user_id=?",
        (amount, user_id),
    )

    conn.execute(
        """
        INSERT INTO credit_history
        (user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, amount, reason, now()),
    )

    conn.commit()
    conn.close()


def remove_credits(user_id, amount):
    conn = db()
    conn.execute(
        """
        UPDATE users
        SET credits=MAX(0, credits-?)
        WHERE user_id=?
        """,
        (amount, user_id),
    )
    conn.commit()
    conn.close()


def get_credits(user_id):
    row = get_user(user_id)
    return int(row["credits"]) if row else 0


def add_history(user_id, tool, status="SUCCESS"):
    conn = db()
    conn.execute(
        """
        INSERT INTO history(user_id, tool, status, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, tool, status, now()),
    )
    conn.commit()
    conn.close()


def add_xp(user_id, amount=XP_SUCCESS):
    conn = db()
    conn.execute(
        "UPDATE users SET xp=xp+? WHERE user_id=?",
        (amount, user_id),
    )
    conn.commit()
    conn.close()


def level_from_xp(xp):
    return max(1, int(xp // 100) + 1)


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
        return datetime.fromisoformat(until) > datetime.now()
    except Exception:
        return False


def set_premium(user_id, days):
    until = datetime.now() + timedelta(days=days)

    conn = db()
    conn.execute(
        """
        UPDATE users
        SET premium=1, premium_until=?
        WHERE user_id=?
        """,
        (until.isoformat(sep=" "), user_id),
    )
    conn.commit()
    conn.close()


def ban_user(user_id):
    conn = db()
    conn.execute(
        "UPDATE users SET banned=1 WHERE user_id=?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def unban_user(user_id):
    conn = db()
    conn.execute(
        "UPDATE users SET banned=0 WHERE user_id=?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def is_banned(user_id):
    row = get_user(user_id)
    return bool(row and row["banned"])


# ============================================================
# DAILY / STREAK
# ============================================================

def process_daily(user_id):
    conn = db()

    row = conn.execute(
        "SELECT last_daily, streak FROM users WHERE user_id=?",
        (user_id,),
    ).fetchone()

    if not row:
        conn.close()
        return False, 0, 0

    last = row["last_daily"]
    streak = int(row["streak"] or 0)

    if last == today():
        conn.close()
        return False, streak, 0

    if last:
        try:
            d = date.fromisoformat(last)
            if d == date.today() - timedelta(days=1):
                streak += 1
            else:
                streak = 1
        except Exception:
            streak = 1
    else:
        streak = 1

    conn.execute(
        """
        UPDATE users
        SET credits=credits+?,
            streak=?,
            last_daily=?
        WHERE user_id=?
        """,
        (
            DAILY_BONUS,
            streak,
            today(),
            user_id,
        ),
    )

    conn.execute(
        """
        INSERT INTO credit_history
        (user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            DAILY_BONUS,
            "Daily Bonus",
            now(),
        ),
    )

    conn.commit()
    conn.close()

    return True, streak, DAILY_BONUS


# ============================================================
# TEXT
# ============================================================

TEXTS = {
    "bn": {
        "welcome": "🌟 <b>Rafim Tools Bot</b>\n\nআপনার All-in-One Utility Bot-এ স্বাগতম।",
        "banned": "🚫 আপনার অ্যাকাউন্টটি বর্তমানে বন্ধ করা হয়েছে।",
        "main": "🏠 <b>Main Menu</b>\n\nপ্রয়োজনীয় একটি অপশন নির্বাচন করুন।",
        "success": "✅ <b>SUCCESS</b>",
        "error": "❌ <b>ERROR</b>",
        "retry": "🔄 Retry",
    },
    "en": {
        "welcome": "🌟 <b>Rafim Tools Bot</b>\n\nWelcome to your All-in-One Utility Bot.",
        "banned": "🚫 Your account is currently blocked.",
        "main": "🏠 <b>Main Menu</b>\n\nChoose an option.",
        "success": "✅ <b>SUCCESS</b>",
        "error": "❌ <b>ERROR</b>",
        "retry": "🔄 Retry",
    },
    "hi": {
        "welcome": "🌟 <b>Rafim Tools Bot</b>\n\nआपके All-in-One Utility Bot में स्वागत है।",
        "banned": "🚫 आपका अकाउंट अभी ब्लॉक है।",
        "main": "🏠 <b>Main Menu</b>\n\nएक विकल्प चुनें।",
        "success": "✅ <b>SUCCESS</b>",
        "error": "❌ <b>ERROR</b>",
        "retry": "🔄 Retry",
    },
}


def lang(user_id):
    row = get_user(user_id)
    return row["language"] if row and row["language"] in TEXTS else "bn"


def tr(user_id, key):
    l = lang(user_id)
    return TEXTS.get(l, TEXTS["bn"]).get(key, key)


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📕 PDF Tools", "🖼️ Image Tools"],
            ["📝 Text Tools", "🧮 Utility Tools"],
            ["📥 Video Downloader", "💎 Premium"],
            ["🎁 Daily Bonus", "👥 Referral"],
            ["🎟️ Redeem", "📜 History"],
            ["🆘 Support", "⚙️ Settings"],
            ["🏠 Main Menu"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👥 Users", callback_data="admin:users"),
                InlineKeyboardButton("📊 Statistics", callback_data="admin:stats"),
            ],
            [
                InlineKeyboardButton("💎 Premium Requests", callback_data="admin:premium"),
                InlineKeyboardButton("🎟️ Redeem", callback_data="admin:redeem"),
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast"),
                InlineKeyboardButton("🚫 Ban/Unban", callback_data="admin:ban"),
            ],
            [
                InlineKeyboardButton("🎫 Tickets", callback_data="admin:tickets"),
                InlineKeyboardButton("⚙️ Settings", callback_data="admin:settings"),
            ],
            [
                InlineKeyboardButton("🏠 Main Menu", callback_data="main"),
            ],
        ]
    )


PDF_TOOLS = {
    "pdf_word": "📄 PDF → Word",
    "pdf_text": "📝 PDF → Text",
    "pdf_images": "🖼️ PDF → Images",
    "pdf_compress": "🗜️ PDF Compress",
    "pdf_merge": "🔗 PDF Merge",
    "pdf_split": "✂️ PDF Split",
    "pdf_extract": "📑 Page Extract",
    "pdf_rotate": "🔄 Rotate PDF",
    "pdf_resize": "📐 Page Size",
    "pdf_numbers": "🔢 Page Numbers",
    "pdf_watermark": "💧 Watermark",
    "pdf_metadata": "🧹 Remove Metadata",
    "pdf_info": "ℹ️ PDF Info",
    "pdf_protect": "🔐 PDF Password",
    "pdf_unlock": "🔓 Unlock PDF",
    "pdf_xps": "📦 PDF → XPS",
}


IMAGE_TOOLS = {
    "img_compress": "🗜️ Compress",
    "img_resize": "📏 Resize",
    "img_crop": "✂️ Crop",
    "img_jpg": "🟨 JPG",
    "img_png": "🟦 PNG",
    "img_webp": "🟩 WebP",
    "img_pdf": "📄 Image → PDF",
    "img_multi_pdf": "📚 Images → PDF",
    "img_watermark": "💧 Watermark",
    "img_enhance": "✨ Enhance",
    "img_gray": "⚫ Grayscale",
    "img_rotate": "🔄 Rotate",
    "img_flip": "↔️ Flip",
}


TEXT_TOOLS = {
    "word_count": "🔢 Word/Character Count",
    "upper": "🔠 UPPERCASE",
    "lower": "🔡 lowercase",
    "title": "🔤 Title Case",
    "clean": "🧹 Text Cleaner",
    "json": "📋 JSON Formatter",
    "url_encode": "🔗 URL Encode",
    "url_decode": "🔓 URL Decode",
    "base64_encode": "🔐 Base64 Encode",
    "base64_decode": "🔓 Base64 Decode",
    "encrypt": "🔒 Text Encrypt",
    "decrypt": "🔓 Text Decrypt",
}


UTILITY_TOOLS = {
    "calculator": "🧮 Calculator",
    "unit": "📏 Unit Converter",
    "date_calc": "📅 Date Calculator",
    "random": "🎲 Random Generator",
    "uuid": "🆔 UUID Generator",
    "password": "🔑 Password Generator",
    "qr": "🔳 QR Generator",
}


def grid_buttons(items, prefix="tool", width=2):
    arr = list(items.items())
    rows = []

    for i in range(0, len(arr), width):
        row = []

        for code, label in arr[i:i + width]:
            row.append(
                InlineKeyboardButton(
                    label,
                    callback_data=f"{prefix}:{code}",
                )
            )

        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="main",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


def back_keyboard(target="main"):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=target,
                ),
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="main",
                ),
            ]
        ]
    )



# ============================================================
# DOWNLOADER SYSTEM (yt-dlp, API-FREE)
# ============================================================

DL_QUEUE = None
DL_QUEUE_WORKER_STARTED = False
DL_JOBS = {}
DL_URL_CACHE = {}
DL_LAST_UPDATE = {}
DL_QUEUE_LOCK = asyncio.Lock()


def dl_size(value):
    try:
        value = float(value or 0)
    except Exception:
        value = 0
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while value >= 1024 and i < len(units) - 1:
        value /= 1024
        i += 1
    return f"{value:.1f} {units[i]}"


def dl_speed(value):
    return f"{dl_size(value)}/s" if value else "—"


def dl_eta(seconds):
    try:
        seconds = int(seconds or 0)
    except Exception:
        seconds = 0
    if seconds <= 0:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def dl_bar(percent, width=18):
    try:
        percent = max(0, min(100, float(percent)))
    except Exception:
        percent = 0
    filled = int(width * percent / 100)
    return "█" * filled + "░" * (width - filled)


def dl_clean_title(title):
    title = re.sub(r"[\x00-\x1f<>:]", " ", str(title or "Unknown"))
    return re.sub(r"\s+", " ", title).strip()[:180] or "Downloaded file"


def dl_duration(seconds):
    try:
        seconds = int(seconds or 0)
    except Exception:
        return "N/A"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def dl_is_url(text):
    return bool(re.match(r"^https?://[^\s]+$", text.strip(), re.I))


def dl_extract(url):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 20,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def dl_quality_list(info):
    heights = set()
    for f in info.get("formats") or []:
        h = f.get("height")
        if h:
            try:
                h = int(h)
                if h >= 144:
                    heights.add(h)
            except Exception:
                pass
    if not heights and info.get("height"):
        heights.add(int(info["height"]))
    return sorted(heights, reverse=True)[:8]


def dl_history_add(user_id, url, title, kind, quality, filename, status, error=""):
    conn = db()
    conn.execute(
        """INSERT INTO downloader_history
        (user_id,url,title,kind,quality,filename,status,error,created_at,completed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (user_id, url, title, kind, quality, filename, status, error, now(), now() if status in ("success", "failed", "cancelled") else "")
    )
    conn.commit()
    conn.close()


def dl_job_db(job):
    conn = db()
    conn.execute(
        """INSERT OR REPLACE INTO downloader_jobs
        (job_id,user_id,url,title,kind,quality,status,progress,downloaded,total,speed,eta,filename,error,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job["id"], job["user_id"], job["url"], job.get("title", ""), job["kind"], job.get("quality", ""),
         job["status"], job.get("progress", 0), job.get("downloaded", 0), job.get("total", 0), job.get("speed", 0),
         job.get("eta", 0), job.get("filename", ""), job.get("error", ""), job["created_at"], now())
    )
    conn.commit()
    conn.close()


def dl_stats(user_id=None):
    conn = db()
    where = "WHERE user_id=?" if user_id else ""
    args = (user_id,) if user_id else ()
    row = conn.execute(
        f"SELECT COUNT(*) total, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) success, "
        f"SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed, "
        f"SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) cancelled FROM downloader_history {where}", args
    ).fetchone()
    conn.close()
    return {"total": row[0] or 0, "success": row[1] or 0, "failed": row[2] or 0, "cancelled": row[3] or 0}


def dl_recent_history(user_id, limit=10):
    conn = db()
    rows = conn.execute(
        "SELECT id,title,kind,quality,status,created_at FROM downloader_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return rows


async def downloader_menu(update, context):
    await update.message.reply_text(
        "📥 <b>VIDEO DOWNLOADER</b>\n\n"
        "🔗 YouTube, Facebook, Instagram, TikTok এবং yt-dlp-supported public URLs দিন।\n"
        "🖼️ Link দিলে আগে Title + Thumbnail + Duration + Quality দেখাবে।\n"
        "🎵 Audio download-ও আছে।\n\n"
        "👉 এখন একটি video URL পাঠান।\n"
        "🛑 বন্ধ করতে /cancel লিখুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 Download History", callback_data="dl:history")], [InlineKeyboardButton("📊 My Downloader Stats", callback_data="dl:stats")]])
    )
    context.user_data["downloader_waiting_url"] = True


async def downloader_show_info(update, context, url):
    uid = update.effective_user.id
    msg = await update.message.reply_text("🔎 <b>Link checking...</b>", parse_mode=ParseMode.HTML)
    try:
        info = await asyncio.to_thread(dl_extract, url)
        title = dl_clean_title(info.get("title"))
        duration = dl_duration(info.get("duration"))
        thumb = info.get("thumbnail") or ""
        heights = dl_quality_list(info)
        job_id = uuid.uuid4().hex[:10]
        DL_URL_CACHE[job_id] = {"url": url, "info": info, "user_id": uid, "title": title}
        buttons = []
        row = []
        for h in heights:
            row.append(InlineKeyboardButton(f"🎞️ {h}p", callback_data=f"dlq:{job_id}:{h}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("🎵 Audio", callback_data=f"dla:{job_id}")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"dlcancel:{job_id}")])
        caption = (
            f"🎬 <b>{title}</b>\n\n"
            f"⏱ Duration: <b>{duration}</b>\n"
            f"🌐 Site: <b>{info.get('extractor_key') or info.get('extractor') or 'Unknown'}</b>\n\n"
            "🎞️ Quality নির্বাচন করুন:"
        )
        try:
            if thumb:
                await msg.delete()
                await update.message.reply_photo(thumb, caption=caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await msg.edit_text(caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            await msg.edit_text(caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await msg.edit_text(
            "❌ <b>ERROR</b>\n\nএই URL থেকে তথ্য পাওয়া যায়নি।\n\n"
            f"<code>{str(e)[:500]}</code>\n\n🔄 অন্য একটি public URL চেষ্টা করুন।",
            parse_mode=ParseMode.HTML,
        )
    finally:
        context.user_data.pop("downloader_waiting_url", None)


def dl_make_job(uid, cache, kind, quality):
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "user_id": uid, "url": cache["url"], "title": cache.get("title", "Downloaded file"),
        "kind": kind, "quality": str(quality), "status": "queued", "progress": 0, "downloaded": 0,
        "total": 0, "speed": 0, "eta": 0, "filename": "", "error": "", "created_at": now(),
        "message": None, "cancel": __import__("threading").Event(), "retry": 0,
    }
    DL_JOBS[job_id] = job
    dl_job_db(job)
    return job


def dl_progress_hook(job, loop):
    def hook(d):
        job["status"] = d.get("status", job["status"])
        job["downloaded"] = int(d.get("downloaded_bytes") or 0)
        job["total"] = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
        job["speed"] = float(d.get("speed") or 0)
        job["eta"] = int(d.get("eta") or 0)
        if job["total"]:
            job["progress"] = min(100, job["downloaded"] * 100 / job["total"])
        if d.get("filename"):
            job["filename"] = os.path.basename(d["filename"])
        if job["cancel"].is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
        ts = time.monotonic()
        if ts - DL_LAST_UPDATE.get(job["id"], 0) >= 1.2:
            DL_LAST_UPDATE[job["id"]] = ts
            if job.get("message"):
                asyncio.run_coroutine_threadsafe(downloader_update_progress(job), loop)
    return hook


async def downloader_update_progress(job):
    msg = job.get("message")
    if not msg:
        return
    p = job.get("progress", 0)
    text = (
        f"📥 <b>Downloading...</b>\n\n"
        f"🎬 {dl_clean_title(job.get('title'))}\n"
        f"📊 <code>{dl_bar(p)}</code> <b>{p:.1f}%</b>\n"
        f"⚡ Speed: <b>{dl_speed(job.get('speed'))}</b>\n"
        f"📦 Downloaded: <b>{dl_size(job.get('downloaded'))}</b> / <b>{dl_size(job.get('total')) if job.get('total') else 'Unknown'}</b>\n"
        f"⏱ ETA: <b>{dl_eta(job.get('eta'))}</b>\n\n"
        "🛑 চাইলে নিচের Cancel চাপুন।"
    )
    try:
        await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"dlcancel:{job['id']}")]]))
    except Exception:
        pass


async def downloader_worker(application):
    global DL_QUEUE, DL_QUEUE_WORKER_STARTED
    if DL_QUEUE is None:
        DL_QUEUE = asyncio.Queue()
    if DL_QUEUE_WORKER_STARTED:
        return
    DL_QUEUE_WORKER_STARTED = True
    while True:
        job = await DL_QUEUE.get()
        try:
            await downloader_run_job(application, job)
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            dl_job_db(job)
        finally:
            DL_QUEUE.task_done()


async def downloader_run_job(application, job):
    uid = job["user_id"]
    try:
        job["status"] = "downloading"
        dl_job_db(job)
        outdir = os.path.join(TEMP_DIR, "downloader", job["id"])
        os.makedirs(outdir, exist_ok=True)
        loop = asyncio.get_running_loop()
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "outtmpl": os.path.join(outdir, "%(title).150B-%(id)s.%(ext)s"),
            "progress_hooks": [dl_progress_hook(job, loop)],
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "continuedl": True,
        }
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                ffmpeg_path = None
        if ffmpeg_path:
            opts["ffmpeg_location"] = ffmpeg_path
        if job["kind"] == "audio":
            opts.update({"format": "bestaudio/best"})
            if ffmpeg_path:
                opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        else:
            h = int(job["quality"])
            if ffmpeg_path:
                fmt = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best[height<={h}]/best"
                opts["merge_output_format"] = "mp4"
            else:
                fmt = f"best[height<={h}]/best"
            opts["format"] = fmt
        def run():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(job["url"], download=True)
        info = await asyncio.to_thread(run)
        if job["cancel"].is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
        files = [os.path.join(outdir, x) for x in os.listdir(outdir) if os.path.isfile(os.path.join(outdir, x))]
        if not files:
            raise RuntimeError("Downloaded file was not created.")
        path = max(files, key=os.path.getsize)
        size = os.path.getsize(path)
        premium = is_premium(uid)
        ok, limit = check_file_size(size, premium)
        if not ok:
            raise RuntimeError(f"File size {dl_size(size)} exceeds your {limit} MB limit.")
        job["filename"] = os.path.basename(path)
        job["progress"] = 100
        job["status"] = "success"
        job["downloaded"] = size
        job["total"] = size
        dl_job_db(job)
        dl_history_add(uid, job["url"], job["title"], job["kind"], job["quality"], job["filename"], "success")
        caption = f"✅ <b>DOWNLOAD SUCCESS</b>\n\n🎬 {dl_clean_title(job['title'])}\n📦 {dl_size(size)}\n🎞️ {job['quality'] if job['kind']=='video' else 'Audio'}"
        with open(path, "rb") as f:
            if job["kind"] == "audio" and path.lower().endswith((".mp3", ".m4a", ".aac", ".ogg")):
                await application.bot.send_audio(uid, audio=f, caption=caption, parse_mode=ParseMode.HTML, title=job["title"][:100])
            elif job["kind"] == "audio":
                await application.bot.send_document(uid, document=f, caption=caption, parse_mode=ParseMode.HTML)
            else:
                await application.bot.send_video(uid, video=f, caption=caption, parse_mode=ParseMode.HTML, supports_streaming=True)
    except yt_dlp.utils.DownloadCancelled:
        job["status"] = "cancelled"
        job["error"] = "Cancelled by user"
        dl_job_db(job)
        dl_history_add(uid, job["url"], job["title"], job["kind"], job["quality"], job.get("filename", ""), "cancelled", "Cancelled by user")
        try:
            await application.bot.send_message(uid, "🛑 <b>Download Cancelled</b>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        dl_job_db(job)
        dl_history_add(uid, job["url"], job["title"], job["kind"], job["quality"], job.get("filename", ""), "failed", str(e)[:1000])
        try:
            await application.bot.send_message(uid, f"❌ <b>DOWNLOAD ERROR</b>\n\n<code>{str(e)[:1200]}</code>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry", callback_data=f"dlretry:{job['id']}")]]))
        except Exception:
            pass
    finally:
        try:
            shutil.rmtree(outdir, ignore_errors=True)
        except Exception:
            pass


async def downloader_enqueue(update, context, job):
    global DL_QUEUE
    if DL_QUEUE is None:
        DL_QUEUE = asyncio.Queue()
    waiting = DL_QUEUE.qsize()
    job["queue_position"] = waiting + 1
    await DL_QUEUE.put(job)
    await update.effective_message.reply_text(
        f"📋 <b>Added to Queue</b>\n\n🆔 <code>{job['id']}</code>\n🎬 {dl_clean_title(job['title'])}\n📍 Queue Position: <b>{waiting + 1}</b>",
        parse_mode=ParseMode.HTML,
    )


async def downloader_history_message(update, user_id):
    rows = dl_recent_history(user_id, 10)
    stats = dl_stats(user_id)
    if not rows:
        text = "📜 <b>Download History</b>\n\nকোনো download history নেই।"
    else:
        items = []
        for r in rows:
            icon = "✅" if r[4] == "success" else ("🛑" if r[4] == "cancelled" else "❌")
            items.append(f"{icon} <b>{dl_clean_title(r[1])[:60]}</b>\n   🎞️ {r[2]} {r[3]} • {r[5]}")
        text = "📜 <b>Download History</b>\n\n" + "\n\n".join(items)
    text += f"\n\n📊 Total: <b>{stats['total']}</b> • ✅ {stats['success']} • ❌ {stats['failed']} • 🛑 {stats['cancelled']}"
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📥 Downloader", callback_data="dl:menu")]]))


async def downloader_admin_stats(update, context):
    if not is_admin(update.effective_user.id):
        return
    stats = dl_stats()
    conn = db()
    active = conn.execute("SELECT COUNT(*) FROM downloader_jobs WHERE status IN ('queued','downloading')").fetchone()[0]
    conn.close()
    await update.effective_message.reply_text(
        "📊 <b>DOWNLOADER STATISTICS</b>\n\n"
        f"📥 Total: <b>{stats['total']}</b>\n"
        f"✅ Success: <b>{stats['success']}</b>\n"
        f"❌ Failed: <b>{stats['failed']}</b>\n"
        f"🛑 Cancelled: <b>{stats['cancelled']}</b>\n"
        f"⏳ Active/Queue: <b>{active}</b>", parse_mode=ParseMode.HTML)


async def admin_direct_chat_start(update, context):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("💬 ব্যবহার: /chat USER_ID")
        return
    try:
        target = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ Invalid USER_ID")
        return
    if not get_user(target):
        await update.message.reply_text("❌ এই USER_ID database-এ নেই।")
        return
    conn = db()
    conn.execute("INSERT OR REPLACE INTO direct_chat_sessions(admin_id,user_id,active,created_at,updated_at) VALUES(?,?,?,?,?)", (ADMIN_ID,target,1,now(),now()))
    conn.commit(); conn.close()
    context.user_data["direct_chat_target"] = target
    await update.message.reply_text(f"💬 <b>Direct Chat Active</b>\n\n👤 User ID: <code>{target}</code>\n\nএখন তোমার পাঠানো text ওই user-এর কাছে যাবে। বন্ধ করতে /endchat", parse_mode=ParseMode.HTML)


async def admin_direct_chat_end(update, context):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.pop("direct_chat_target", None)
    conn = db(); conn.execute("UPDATE direct_chat_sessions SET active=0,updated_at=? WHERE admin_id=?", (now(),ADMIN_ID)); conn.commit(); conn.close()
    await update.message.reply_text("🛑 Direct Chat বন্ধ হয়েছে।")


async def admin_direct_chat_text(update, context):
    if update.effective_user.id != ADMIN_ID or not update.message or not update.message.text:
        return False
    if context.user_data.get("broadcast_mode"):
        return False
    target = context.user_data.get("direct_chat_target")
    if not target:
        return False
    try:
        await context.bot.send_message(target, f"💬 <b>Admin Message</b>\n\n{update.message.text}", parse_mode=ParseMode.HTML)
        await update.message.reply_text("✅ Message sent.")
    except Exception as e:
        await update.message.reply_text(f"❌ Send failed: {str(e)[:500]}")
    raise ApplicationHandlerStop


async def user_direct_chat_reply(update, context):
    if not update.message or not update.message.text or update.effective_user.id == ADMIN_ID:
        return False
    conn = db()
    row = conn.execute("SELECT admin_id FROM direct_chat_sessions WHERE user_id=? AND active=1", (update.effective_user.id,)).fetchone()
    conn.close()
    if not row:
        return False
    try:
        await context.bot.send_message(ADMIN_ID, f"↩️ <b>User Reply</b>\n\n👤 ID: <code>{update.effective_user.id}</code>\n👤 @{update.effective_user.username or 'N/A'}\n\n{update.message.text}", parse_mode=ParseMode.HTML)
        await update.message.reply_text("✅ আপনার মেসেজ Admin-এর কাছে পাঠানো হয়েছে।")
    except Exception:
        pass
    raise ApplicationHandlerStop


# ============================================================
# CALLBACK SAFE HELPERS
# ============================================================

async def safe_answer(query, text=None, alert=False):
    try:
        await query.answer(text, show_alert=alert)
    except Exception:
        pass


async def safe_edit(query, text, reply_markup=None):
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except Exception:
        try:
            await query.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except Exception:
            pass


# ============================================================
# LOADING SYSTEM
# ============================================================

PROGRESS_STEPS = [
    (10, "⏳ Starting..."),
    (20, "📥 Reading file..."),
    (30, "🔍 Checking data..."),
    (40, "⚙️ Preparing..."),
    (50, "🔄 Processing..."),
    (60, "🛠️ Applying tool..."),
    (70, "📦 Building result..."),
    (80, "✨ Finalizing..."),
    (90, "🚀 Almost Done..."),
    (100, "✅ SUCCESS"),
]


async def create_progress(message, title):
    msg = await message.reply_text(
        f"⏳ <b>{title}</b>\n\n"
        f"🟦 10%\n"
        f"🔄 Starting...",
        parse_mode=ParseMode.HTML,
    )

    return msg


async def update_progress(progress_msg, title, percent, status):
    try:
        await progress_msg.edit_text(
            f"⚙️ <b>{title}</b>\n\n"
            f"📊 Progress: <b>{percent}%</b>\n"
            f"🔄 {status}",
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass


async def progress_before(progress_msg, title):
    for percent, status in PROGRESS_STEPS[:5]:
        await update_progress(
            progress_msg,
            title,
            percent,
            status,
        )
        await asyncio.sleep(0.12)


async def progress_after(progress_msg, title):
    for percent, status in PROGRESS_STEPS[5:]:
        await update_progress(
            progress_msg,
            title,
            percent,
            status,
        )
        await asyncio.sleep(0.12)


# ============================================================
# FILE HELPERS
# ============================================================

def mb(size):
    return size / (1024 * 1024)


def check_file_size(file_size, premium):
    limit = PREMIUM_FILE_LIMIT_MB if premium else FREE_FILE_LIMIT_MB
    return mb(file_size) <= limit, limit


async def download_document(update, context):
    document = update.message.document

    if not document:
        return None

    file = await context.bot.get_file(document.file_id)

    data = await file.download_as_bytearray()

    return bytes(data)


async def download_photo(update, context):
    photo = update.message.photo[-1]

    file = await context.bot.get_file(photo.file_id)

    data = await file.download_as_bytearray()

    return bytes(data)


# ============================================================
# PDF FUNCTIONS
# ============================================================

def pdf_to_word(data):
    src = fitz.open(stream=data, filetype="pdf")

    doc = Document()

    for page in src:
        text = page.get_text("text")

        if text.strip():
            for paragraph in text.split("\n"):
                if paragraph.strip():
                    doc.add_paragraph(paragraph)

    out = io.BytesIO()
    doc.save(out)

    src.close()

    return out.getvalue()


def pdf_to_text(data):
    src = fitz.open(stream=data, filetype="pdf")

    text = []

    for i, page in enumerate(src, 1):
        text.append(f"===== PAGE {i} =====\n")
        text.append(page.get_text("text"))

    src.close()

    return "\n".join(text).encode("utf-8")


def pdf_to_images_zip(data, image_format="png"):
    src = fitz.open(stream=data, filetype="pdf")

    output = io.BytesIO()

    import zipfile

    with zipfile.ZipFile(
        output,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as z:

        for i, page in enumerate(src, 1):
            pix = page.get_pixmap(
                matrix=fitz.Matrix(1.5, 1.5),
                alpha=False,
            )

            ext = image_format.lower()

            name = f"page_{i}.{ext}"

            z.writestr(
                name,
                pix.tobytes(ext),
            )

    src.close()

    return output.getvalue()


def compress_pdf(data):
    src = fitz.open(stream=data, filetype="pdf")

    output = io.BytesIO()

    src.save(
        output,
        garbage=4,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
    )

    src.close()

    return output.getvalue()


def merge_pdfs(pdf_list):
    result = fitz.open()

    for data in pdf_list:
        src = fitz.open(
            stream=data,
            filetype="pdf",
        )

        result.insert_pdf(src)

        src.close()

    output = io.BytesIO()
    result.save(output)
    result.close()

    return output.getvalue()


def split_pdf(data, page_number):
    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    if page_number < 1 or page_number > len(src):
        raise ValueError(
            f"Page number must be between 1 and {len(src)}"
        )

    result = fitz.open()

    result.insert_pdf(
        src,
        from_page=page_number - 1,
        to_page=page_number - 1,
    )

    output = io.BytesIO()
    result.save(output)

    result.close()
    src.close()

    return output.getvalue()


def extract_pdf_pages(data, start_page, end_page):
    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    if (
        start_page < 1
        or end_page > len(src)
        or start_page > end_page
    ):
        raise ValueError("Invalid page range.")

    result = fitz.open()

    result.insert_pdf(
        src,
        from_page=start_page - 1,
        to_page=end_page - 1,
    )

    output = io.BytesIO()
    result.save(output)

    result.close()
    src.close()

    return output.getvalue()


def rotate_pdf(data, angle=90):
    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    angle = int(angle) % 360

    for page in src:
        page.set_rotation(
            (page.rotation + angle) % 360
        )

    output = io.BytesIO()
    src.save(output)

    src.close()

    return output.getvalue()


def resize_pdf(data, size_name="A4"):
    sizes = {
        "A4": (595, 842),
        "A5": (420, 595),
        "LETTER": (612, 792),
        "LEGAL": (612, 1008),
    }

    key = size_name.upper()

    if key not in sizes:
        key = "A4"

    width, height = sizes[key]

    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    result = fitz.open()

    for page in src:
        new_page = result.new_page(
            width=width,
            height=height,
        )

        rect = fitz.Rect(
            0,
            0,
            width,
            height,
        )

        new_page.show_pdf_page(
            rect,
            src,
            page.number,
        )

    output = io.BytesIO()
    result.save(output)

    result.close()
    src.close()

    return output.getvalue()


def add_page_numbers(data):
    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    for i, page in enumerate(src, 1):
        rect = page.rect

        page.insert_text(
            (
                rect.x0 + 20,
                rect.y1 - 15,
            ),
            f"Page {i}",
            fontsize=9,
        )

    output = io.BytesIO()
    src.save(output)

    src.close()

    return output.getvalue()


def watermark_pdf(data, text):
    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    for page in src:
        rect = page.rect

        page.insert_text(
            (
                rect.width / 2 - 100,
                rect.height / 2,
            ),
            text[:100],
            fontsize=28,
            rotate=45,
        )

    output = io.BytesIO()
    src.save(output)

    src.close()

    return output.getvalue()


def remove_pdf_metadata(data):
    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    metadata = src.metadata or {}

    for key in metadata:
        metadata[key] = ""

    src.set_metadata(metadata)

    output = io.BytesIO()
    src.save(output)

    src.close()

    return output.getvalue()


def pdf_info(data):
    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    metadata = src.metadata or {}

    text = (
        "📕 <b>PDF Information</b>\n\n"
        f"📄 Pages: <b>{len(src)}</b>\n"
        f"📦 Size: <b>{mb(len(data)):.2f} MB</b>\n"
        f"🔐 Encrypted: <b>{'Yes' if src.is_encrypted else 'No'}</b>\n\n"
        f"👤 Author: {metadata.get('author', '') or 'N/A'}\n"
        f"📝 Title: {metadata.get('title', '') or 'N/A'}\n"
        f"🏢 Creator: {metadata.get('creator', '') or 'N/A'}"
    )

    src.close()

    return text


def protect_pdf(data, password):
    src = fitz.open(
        stream=data,
        filetype="pdf",
    )

    output = io.BytesIO()

    encryption = getattr(
        fitz,
        "PDF_ENCRYPT_AES_256",
        getattr(
            fitz,
            "PDF_ENCRYPT_AES_128",
            4,
        ),
    )

    src.save(
        output,
        encryption=encryption,
        owner_pw=password,
        user_pw=password,
    )

    src.close()

    return output.getvalue()


def unlock_pdf(data, password):
    src = fitz.open(
        stream=data,
        filetype="pdf",
        password=password,
    )

    if src.needs_pass and not src.authenticate(password):
        src.close()
        raise ValueError("Incorrect PDF password.")

    output = io.BytesIO()

    src.save(
        output,
        encryption=fitz.PDF_ENCRYPT_NONE,
    )

    src.close()

    return output.getvalue()


def pdf_to_xps(data):
    gs = (
        shutil.which("gs")
        or shutil.which("gswin64c")
        or shutil.which("gswin32c")
    )

    if not gs:
        raise RuntimeError(
            "Ghostscript is not installed on this server. "
            "PDF → XPS is currently unavailable."
        )

    with tempfile.TemporaryDirectory(
        dir=TEMP_DIR
    ) as td:

        pdf_path = os.path.join(td, "input.pdf")
        xps_path = os.path.join(td, "output.xps")

        with open(pdf_path, "wb") as f:
            f.write(data)

        command = [
            gs,
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=xps",
            f"-sOutputFile={xps_path}",
            pdf_path,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "XPS conversion failed."
            )

        if not os.path.exists(xps_path):
            raise RuntimeError(
                "XPS output was not created."
            )

        with open(xps_path, "rb") as f:
            return f.read()


# ============================================================
# IMAGE FUNCTIONS
# ============================================================

def open_image(data):
    image = Image.open(io.BytesIO(data))
    return ImageOps.exif_transpose(image)


def image_output(image, fmt="PNG", quality=90):
    output = io.BytesIO()

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")

    if fmt.upper() in ("JPG", "JPEG"):
        if image.mode != "RGB":
            background = Image.new(
                "RGB",
                image.size,
                "white",
            )
            if "A" in image.getbands():
                background.paste(
                    image,
                    mask=image.getchannel("A"),
                )
            else:
                background.paste(image)
            image = background

        image.save(
            output,
            format="JPEG",
            quality=quality,
            optimize=True,
        )

    else:
        image.save(
            output,
            format=fmt.upper(),
            quality=quality,
            optimize=True,
        )

    return output.getvalue()


def compress_image(data):
    image = open_image(data)
    return image_output(
        image,
        "JPEG",
        70,
    )


def resize_image(data, width, height=None):
    image = open_image(data)

    width = int(width)

    if height:
        height = int(height)
    else:
        ratio = width / image.width
        height = int(image.height * ratio)

    image = image.resize(
        (width, height),
        Image.Resampling.LANCZOS,
    )

    return image_output(
        image,
        "PNG",
    )


def crop_image(data, x, y, width, height):
    image = open_image(data)

    x = int(x)
    y = int(y)
    width = int(width)
    height = int(height)

    box = (
        max(0, x),
        max(0, y),
        min(image.width, x + width),
        min(image.height, y + height),
    )

    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("Invalid crop area.")

    image = image.crop(box)

    return image_output(
        image,
        "PNG",
    )


def convert_image(data, fmt):
    image = open_image(data)

    if fmt == "WEBP":
        return image_output(image, "WEBP", 90)

    if fmt == "JPG":
        return image_output(image, "JPEG", 90)

    return image_output(image, "PNG", 90)


def image_to_pdf(data):
    image = open_image(data)

    if image.mode != "RGB":
        image = image.convert("RGB")

    output = io.BytesIO()

    image.save(
        output,
        format="PDF",
        resolution=100,
    )

    return output.getvalue()


def images_to_pdf(datas):
    images = []

    for data in datas:
        image = open_image(data)

        if image.mode != "RGB":
            image = image.convert("RGB")

        images.append(image)

    if not images:
        raise ValueError("No images found.")

    output = io.BytesIO()

    first = images[0]

    first.save(
        output,
        format="PDF",
        save_all=True,
        append_images=images[1:],
        resolution=100,
    )

    return output.getvalue()


def image_watermark(data, text):
    image = open_image(data).convert("RGBA")

    overlay = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(overlay)

    font = ImageFont.load_default()

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font,
    )

    x = max(
        10,
        image.width - (bbox[2] - bbox[0]) - 20,
    )

    y = image.height - 30

    draw.text(
        (x, y),
        text[:100],
        fill=(255, 255, 255, 180),
        font=font,
    )

    result = Image.alpha_composite(
        image,
        overlay,
    )

    return image_output(
        result,
        "PNG",
    )


def enhance_image(data):
    image = open_image(data)

    image = ImageEnhance.Contrast(
        image
    ).enhance(1.15)

    image = ImageEnhance.Sharpness(
        image
    ).enhance(1.25)

    return image_output(
        image,
        "PNG",
    )


def grayscale_image(data):
    image = open_image(data).convert("L")

    return image_output(
        image,
        "PNG",
    )


def rotate_image(data, angle=90):
    image = open_image(data)

    image = image.rotate(
        -int(angle),
        expand=True,
    )

    return image_output(
        image,
        "PNG",
    )


def flip_image(data):
    image = open_image(data)

    image = ImageOps.mirror(image)

    return image_output(
        image,
        "PNG",
    )


# ============================================================
# TEXT / UTILITY
# ============================================================

def word_count(text):
    words = re.findall(
        r"\S+",
        text,
        flags=re.UNICODE,
    )

    chars = len(text)
    chars_no_space = len(
        re.sub(r"\s+", "", text)
    )
    lines = len(text.splitlines())

    return (
        "📊 <b>Text Statistics</b>\n\n"
        f"📝 Words: <b>{len(words):,}</b>\n"
        f"🔤 Characters: <b>{chars:,}</b>\n"
        f"🔡 Without Spaces: <b>{chars_no_space:,}</b>\n"
        f"📄 Lines: <b>{lines:,}</b>"
    )


def clean_text(text):
    text = text.replace(
        "\r\n",
        "\n",
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def json_format(text):
    obj = json.loads(text)

    return json.dumps(
        obj,
        ensure_ascii=False,
        indent=2,
    )


def safe_base64_encode(text):
    return base64.b64encode(
        text.encode("utf-8")
    ).decode("ascii")


def safe_base64_decode(text):
    return base64.b64decode(
        text.encode("ascii")
    ).decode("utf-8")


def make_fernet(password):
    digest = hashlib.sha256(
        password.encode("utf-8")
    ).digest()

    key = base64.urlsafe_b64encode(
        digest
    )

    return Fernet(key)


def encrypt_text(password, text):
    f = make_fernet(password)

    return f.encrypt(
        text.encode("utf-8")
    ).decode("utf-8")


def decrypt_text(password, text):
    f = make_fernet(password)

    return f.decrypt(
        text.encode("utf-8")
    ).decode("utf-8")


# ============================================================
# SAFE CALCULATOR
# ============================================================

BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}

UNARY_OPS = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


def calculate_expression(expression):
    expression = expression.replace(
        "^",
        "**",
    )

    tree = ast.parse(
        expression,
        mode="eval",
    )

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(
                node.value,
                (int, float),
            ):
                return node.value

            raise ValueError(
                "Invalid number."
            )

        if isinstance(node, ast.BinOp):
            op = BIN_OPS.get(type(node.op))

            if not op:
                raise ValueError(
                    "Operator not allowed."
                )

            left = evaluate(node.left)
            right = evaluate(node.right)

            if abs(left) > 10**100:
                raise ValueError(
                    "Number too large."
                )

            if abs(right) > 10**100:
                raise ValueError(
                    "Number too large."
                )

            result = op(left, right)

            if abs(result) > 10**100:
                raise ValueError(
                    "Result too large."
                )

            return result

        if isinstance(node, ast.UnaryOp):
            op = UNARY_OPS.get(type(node.op))

            if not op:
                raise ValueError(
                    "Operator not allowed."
                )

            return op(evaluate(node.operand))

        raise ValueError(
            "Invalid expression."
        )

    return evaluate(tree)


def unit_convert(text):
    m = re.match(
        r"^\s*([-+]?\d+(?:\.\d+)?)\s*"
        r"([a-zA-Z]+)\s*(?:to|in|=)\s*"
        r"([a-zA-Z]+)\s*$",
        text,
    )

    if not m:
        raise ValueError(
            "Example: 10 km to mile"
        )

    value = float(m.group(1))
    src = m.group(2).lower()
    dst = m.group(3).lower()

    length = {
        "m": 1,
        "meter": 1,
        "meters": 1,
        "km": 1000,
        "kilometer": 1000,
        "mile": 1609.344,
        "mi": 1609.344,
        "ft": 0.3048,
        "feet": 0.3048,
        "inch": 0.0254,
        "in": 0.0254,
        "cm": 0.01,
        "mm": 0.001,
    }

    weight = {
        "g": 1,
        "gram": 1,
        "kg": 1000,
        "kilogram": 1000,
        "lb": 453.59237,
        "pound": 453.59237,
    }

    data_units = {
        "b": 1,
        "kb": 1024,
        "mb": 1024**2,
        "gb": 1024**3,
        "tb": 1024**4,
    }

    if src in length and dst in length:
        result = value * length[src] / length[dst]
        return f"{value:g} {src} = {result:g} {dst}"

    if src in weight and dst in weight:
        result = value * weight[src] / weight[dst]
        return f"{value:g} {src} = {result:g} {dst}"

    if src in data_units and dst in data_units:
        result = value * data_units[src] / data_units[dst]
        return f"{value:g} {src} = {result:g} {dst}"

    if src in ("c", "celsius") and dst in ("f", "fahrenheit"):
        result = value * 9 / 5 + 32
        return f"{value:g}°C = {result:g}°F"

    if src in ("f", "fahrenheit") and dst in ("c", "celsius"):
        result = (value - 32) * 5 / 9
        return f"{value:g}°F = {result:g}°C"

    raise ValueError(
        "Unsupported unit conversion."
    )


def date_calculator(text):
    m = re.match(
        r"^\s*(\d{4}-\d{2}-\d{2})\s*"
        r"([+-])\s*(\d+)\s*$",
        text,
    )

    if not m:
        raise ValueError(
            "Example: 2026-09-22 + 30"
        )

    d = date.fromisoformat(m.group(1))
    days = int(m.group(3))

    if m.group(2) == "-":
        days = -days

    result = d + timedelta(days=days)

    return (
        f"📅 {d.isoformat()} "
        f"{m.group(2)} {abs(days)} "
        f"= <b>{result.isoformat()}</b>"
    )


def random_generator(text):
    text = text.strip()

    if re.fullmatch(
        r"\d+\s*-\s*\d+",
        text,
    ):
        a, b = map(
            int,
            re.split(
                r"\s*-\s*",
                text,
            ),
        )

        if a > b:
            a, b = b, a

        return str(
            random.randint(a, b)
        )

    choices = [
        x.strip()
        for x in text.split(",")
        if x.strip()
    ]

    if not choices:
        raise ValueError(
            "Example: Apple, Banana, Mango"
        )

    return random.choice(choices)


def password_generator(length=16):
    length = max(
        8,
        min(int(length), 64),
    )

    alphabet = (
        string.ascii_letters
        + string.digits
        + "!@#$%^&*_-+="
    )

    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


def make_qr(text):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )

    qr.add_data(text)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    )

    output = io.BytesIO()

    image.save(
        output,
        format="PNG",
    )

    return output.getvalue()


# ============================================================
# SEND RESULT
# ============================================================

async def send_result(
    message,
    data,
    filename,
    caption="",
):
    await message.reply_document(
        document=io.BytesIO(data),
        filename=filename,
        caption=caption,
    )


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referral_id = 0

    if context.args:
        try:
            arg = context.args[0]

            if arg.startswith("ref_"):
                referral_id = int(
                    arg.replace("ref_", "")
                )
            elif arg.isdigit():
                referral_id = int(arg)
        except Exception:
            referral_id = 0

    ensure_user(
        user,
        referral_id,
    )

    if is_banned(user.id):
        await update.message.reply_text(
            tr(user.id, "banned"),
            parse_mode=ParseMode.HTML,
        )
        return

    daily, streak, bonus = process_daily(
        user.id
    )

    extra = ""

    if daily:
        extra = (
            f"\n\n🎁 Daily Bonus: <b>+{bonus}</b> Credits"
            f"\n🔥 Streak: <b>{streak}</b> দিন"
        )

    await update.message.reply_text(
        tr(user.id, "welcome")
        + extra
        + "\n\n👇 নিচের মেনু ব্যবহার করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ============================================================
# MAIN MENU
# ============================================================

async def main_menu(update, context):
    user = update.effective_user

    if not get_user(user.id):
        ensure_user(user)

    if is_banned(user.id):
        await update.message.reply_text(
            tr(user.id, "banned"),
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        tr(user.id, "main"),
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ============================================================
# PDF MENU
# ============================================================

async def pdf_menu(update, context):
    await update.message.reply_text(
        "📕 <b>PDF TOOLS</b>\n\n"
        "নিচের যেকোনো PDF Tool নির্বাচন করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=grid_buttons(
            PDF_TOOLS
        ),
    )


# ============================================================
# IMAGE MENU
# ============================================================

async def image_menu(update, context):
    await update.message.reply_text(
        "🖼️ <b>IMAGE TOOLS</b>\n\n"
        "নিচের যেকোনো Image Tool নির্বাচন করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=grid_buttons(
            IMAGE_TOOLS
        ),
    )


# ============================================================
# TEXT MENU
# ============================================================

async def text_menu(update, context):
    await update.message.reply_text(
        "📝 <b>TEXT TOOLS</b>\n\n"
        "নিচের Tool নির্বাচন করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=grid_buttons(
            TEXT_TOOLS
        ),
    )


# ============================================================
# UTILITY MENU
# ============================================================

async def utility_menu(update, context):
    await update.message.reply_text(
        "🧮 <b>UTILITY TOOLS</b>\n\n"
        "Calculator, QR, Password, Converter ইত্যাদি।",
        parse_mode=ParseMode.HTML,
        reply_markup=grid_buttons(
            UTILITY_TOOLS
        ),
    )


# ============================================================
# ACCOUNT
# ============================================================

async def account(update, context):
    uid = update.effective_user.id

    row = get_user(uid)

    if not row:
        ensure_user(update.effective_user)
        row = get_user(uid)

    premium_text = (
        "💎 ACTIVE"
        if is_premium(uid)
        else "🆓 FREE"
    )

    until = row["premium_until"] or "N/A"

    await update.message.reply_text(
        "👤 <b>MY ACCOUNT</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Name: {row['first_name'] or 'User'}\n"
        f"🔹 Username: @{row['username'] or 'N/A'}\n\n"
        f"💰 Credits: <b>{fmt_num(row['credits'])}</b>\n"
        f"⭐ XP: <b>{fmt_num(row['xp'])}</b>\n"
        f"🏆 Level: <b>{level_from_xp(row['xp'])}</b>\n"
        f"🔥 Streak: <b>{row['streak']}</b>\n"
        f"👥 Referrals: <b>{row['referral_count']}</b>\n"
        f"💎 Premium: <b>{premium_text}</b>\n"
        f"⏰ Premium Until: <code>{until}</code>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# DAILY
# ============================================================

async def daily_bonus(update, context):
    uid = update.effective_user.id

    success, streak, bonus = process_daily(
        uid
    )

    if success:
        await update.message.reply_text(
            "🎁 <b>DAILY BONUS CLAIMED!</b>\n\n"
            f"💰 +<b>{bonus}</b> Credits\n"
            f"🔥 Streak: <b>{streak}</b> দিন\n\n"
            "আগামীকাল আবার আসুন।",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            "⏳ <b>আজকের Daily Bonus ইতিমধ্যে নেওয়া হয়েছে।</b>\n\n"
            "আগামীকাল আবার চেষ্টা করুন।",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# REFERRAL
# ============================================================

async def referral(update, context):
    uid = update.effective_user.id

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{uid}"
    )

    row = get_user(uid)

    await update.message.reply_text(
        "👥 <b>REFERRAL SYSTEM</b>\n\n"
        f"🎁 প্রতি সফল Referral: <b>+{REFERRAL_REWARD}</b> Credits\n"
        f"⭐ Referral XP: <b>+{REFERRAL_XP}</b>\n\n"
        f"👥 Total Referral: <b>{row['referral_count']}</b>\n\n"
        "🔗 <b>Your Referral Link:</b>\n"
        f"<code>{link}</code>\n\n"
        "বন্ধুদের এই লিংক পাঠান।",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# REDEEM
# ============================================================

async def redeem(update, context):
    context.user_data["waiting"] = "redeem"

    await update.message.reply_text(
        "🎟️ <b>REDEEM CODE</b>\n\n"
        "আপনার Redeem Code পাঠান।\n\n"
        "উদাহরণ:\n"
        "<code>RAFIM2026</code>",
        parse_mode=ParseMode.HTML,
    )


async def process_redeem(update, code):
    uid = update.effective_user.id

    code = code.strip().upper()

    conn = db()

    row = conn.execute(
        """
        SELECT * FROM redeem_codes
        WHERE code=? AND active=1
        """,
        (code,),
    ).fetchone()

    if not row:
        conn.close()

        await update.message.reply_text(
            "❌ <b>ERROR</b>\n\n"
            "Invalid অথবা expired redeem code।",
            parse_mode=ParseMode.HTML,
        )
        return

    if row["used_count"] >= row["max_uses"]:
        conn.close()

        await update.message.reply_text(
            "❌ এই Redeem Code-এর limit শেষ।",
            parse_mode=ParseMode.HTML,
        )
        return

    already = conn.execute(
        """
        SELECT id FROM redemptions
        WHERE code=? AND user_id=?
        """,
        (code, uid),
    ).fetchone()

    if already:
        conn.close()

        await update.message.reply_text(
            "⚠️ আপনি এই Code ইতিমধ্যে ব্যবহার করেছেন।",
            parse_mode=ParseMode.HTML,
        )
        return

    conn.execute(
        """
        INSERT INTO redemptions
        (code, user_id, created_at)
        VALUES (?, ?, ?)
        """,
        (code, uid, now()),
    )

    conn.execute(
        """
        UPDATE redeem_codes
        SET used_count=used_count+1
        WHERE code=?
        """,
        (code,),
    )

    conn.execute(
        """
        UPDATE users
        SET credits=credits+?
        WHERE user_id=?
        """,
        (row["credits"], uid),
    )

    conn.execute(
        """
        INSERT INTO credit_history
        (user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            uid,
            row["credits"],
            f"Redeem: {code}",
            now(),
        ),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎉 <b>REDEEM SUCCESS!</b>\n\n"
        f"🎟️ Code: <code>{code}</code>\n"
        f"💰 Credits Added: <b>+{row['credits']}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# HISTORY
# ============================================================

async def history(update, context):
    uid = update.effective_user.id

    conn = db()

    rows = conn.execute(
        """
        SELECT tool, status, created_at
        FROM history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 15
        """,
        (uid,),
    ).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "📜 <b>History Empty</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    text = "📜 <b>RECENT HISTORY</b>\n\n"

    for r in rows:
        icon = (
            "✅"
            if r["status"] == "SUCCESS"
            else "❌"
        )

        text += (
            f"{icon} <b>{r['tool']}</b>\n"
            f"🕐 {r['created_at']}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# PREMIUM
# ============================================================

async def premium(update, context):
    await update.message.reply_text(
        "💎 <b>PREMIUM SYSTEM</b>\n\n"
        "🚀 Premium সুবিধা:\n"
        "• বেশি File Limit\n"
        "• Premium Tools\n"
        "• Faster Processing\n"
        "• Premium Access\n\n"
        f"📅 Weekly: <b>{WEEKLY_PRICE} টাকা</b>\n"
        f"📅 Monthly: <b>{MONTHLY_PRICE} টাকা</b>\n\n"
        f"💳 bKash: <code>{BKASH_NUMBER}</code>\n"
        f"💳 Nagad: <code>{NAGAD_NUMBER}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💎 Weekly Request",
                        callback_data="premium:weekly",
                    ),
                    InlineKeyboardButton(
                        "💎 Monthly Request",
                        callback_data="premium:monthly",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📊 Premium Status",
                        callback_data="premium:status",
                    ),
                ],
            ]
        ),
    )


async def create_premium_request(
    update,
    plan,
):
    uid = update.effective_user.id

    price = (
        WEEKLY_PRICE
        if plan == "weekly"
        else MONTHLY_PRICE
    )

    conn = db()

    conn.execute(
        """
        INSERT INTO premium_requests
        (user_id, plan, status, created_at, updated_at)
        VALUES (?, ?, 'pending', ?, ?)
        """,
        (
            uid,
            plan,
            now(),
            now(),
        ),
    )

    request_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.commit()
    conn.close()

    await update.effective_message.reply_text(
        "📨 <b>Premium Request Sent!</b>\n\n"
        f"🆔 Request: <code>#{request_id}</code>\n"
        f"📦 Plan: <b>{plan.title()}</b>\n"
        f"💰 Price: <b>{price} টাকা</b>\n\n"
        "Admin approval-এর জন্য অপেক্ষা করুন।",
        parse_mode=ParseMode.HTML,
    )

    await update.get_bot().send_message(
        ADMIN_ID,
        "💎 <b>NEW PREMIUM REQUEST</b>\n\n"
        f"🆔 Request: <code>#{request_id}</code>\n"
        f"👤 User: <code>{uid}</code>\n"
        f"📦 Plan: <b>{plan}</b>\n"
        f"💰 Price: <b>{price} টাকা</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ APPROVE",
                        callback_data=f"premapprove:{request_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ REJECT",
                        callback_data=f"premreject:{request_id}",
                    ),
                ]
            ]
        ),
    )


async def premium_status(update, context):
    uid = update.effective_user.id

    row = get_user(uid)

    if is_premium(uid):
        until = row["premium_until"]

        await update.effective_message.reply_text(
            "💎 <b>PREMIUM ACTIVE</b>\n\n"
            f"⏰ Valid Until:\n<code>{until}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.effective_message.reply_text(
            "🆓 আপনার Premium বর্তমানে Active নয়।",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# SETTINGS
# ============================================================

async def settings(update, context):
    uid = update.effective_user.id

    await update.message.reply_text(
        "⚙️ <b>SETTINGS</b>\n\n"
        "🌐 Language নির্বাচন করুন:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🇧🇩 বাংলা",
                        callback_data="lang:bn",
                    ),
                    InlineKeyboardButton(
                        "🇬🇧 English",
                        callback_data="lang:en",
                    ),
                    InlineKeyboardButton(
                        "🇮🇳 हिन्दी",
                        callback_data="lang:hi",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🏠 Main Menu",
                        callback_data="main",
                    )
                ],
            ]
        ),
    )


# ============================================================
# SUPPORT
# ============================================================

async def support(update, context):
    await update.message.reply_text(
        "🆘 <b>SUPPORT CENTER</b>\n\n"
        "কোনো সমস্যা হলে Support-এ যোগাযোগ করুন।\n\n"
        f"👨‍💻 Support: @{SUPPORT_USERNAME}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💬 Contact Support",
                        url=f"https://t.me/{SUPPORT_USERNAME}",
                    )
                ]
            ]
        ),
    )


async def support_text(update, context):
    uid = update.effective_user.id
    text = update.message.text.strip()

    conn = db()

    conn.execute(
        """
        INSERT INTO support_tickets
        (user_id, message, status, created_at)
        VALUES (?, ?, 'open', ?)
        """,
        (
            uid,
            text,
            now(),
        ),
    )

    ticket_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎫 <b>Support Ticket Created!</b>\n\n"
        f"🆔 Ticket: <code>#{ticket_id}</code>\n"
        "Admin আপনার মেসেজ দেখবেন।",
        parse_mode=ParseMode.HTML,
    )

    await context.bot.send_message(
        ADMIN_ID,
        "🆘 <b>NEW SUPPORT TICKET</b>\n\n"
        f"🎫 Ticket: <code>#{ticket_id}</code>\n"
        f"👤 User: <code>{uid}</code>\n\n"
        f"{text[:3000]}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# TEXT TOOL PROCESSOR
# ============================================================

async def process_text_tool(update, context, tool):
    uid = update.effective_user.id
    text = update.message.text

    try:
        if tool == "word_count":
            result = word_count(text)

            await update.message.reply_text(
                result,
                parse_mode=ParseMode.HTML,
            )

        elif tool == "upper":
            await update.message.reply_text(
                text.upper()
            )

        elif tool == "lower":
            await update.message.reply_text(
                text.lower()
            )

        elif tool == "title":
            await update.message.reply_text(
                text.title()
            )

        elif tool == "clean":
            await update.message.reply_text(
                clean_text(text)
            )

        elif tool == "json":
            result = json_format(text)

            await update.message.reply_text(
                f"<pre>{result[:3900]}</pre>",
                parse_mode=ParseMode.HTML,
            )

        elif tool == "url_encode":
            await update.message.reply_text(
                quote(text)
            )

        elif tool == "url_decode":
            await update.message.reply_text(
                unquote(text)
            )

        elif tool == "base64_encode":
            await update.message.reply_text(
                safe_base64_encode(text)
            )

        elif tool == "base64_decode":
            await update.message.reply_text(
                safe_base64_decode(text)
            )

        elif tool == "encrypt":
            parts = text.split(
                "|||",
                1,
            )

            if len(parts) != 2:
                raise ValueError(
                    "Format: password|||text"
                )

            result = encrypt_text(
                parts[0],
                parts[1],
            )

            await update.message.reply_text(
                result
            )

        elif tool == "decrypt":
            parts = text.split(
                "|||",
                1,
            )

            if len(parts) != 2:
                raise ValueError(
                    "Format: password|||encrypted_text"
                )

            result = decrypt_text(
                parts[0],
                parts[1],
            )

            await update.message.reply_text(
                result
            )

        add_history(
            uid,
            TEXT_TOOLS.get(tool, tool),
        )

        add_xp(uid)

    except Exception as e:
        await update.message.reply_text(
            "❌ <b>ERROR</b>\n\n"
            f"<code>{str(e)[:1500]}</code>\n\n"
            "🔄 সঠিক Format দিয়ে আবার চেষ্টা করুন।",
            parse_mode=ParseMode.HTML,
        )

    context.user_data.pop(
        "text_tool",
        None,
    )


# ============================================================
# UTILITY PROCESSOR
# ============================================================

async def process_utility(update, context, tool):
    uid = update.effective_user.id
    text = update.message.text.strip()

    try:
        if tool == "calculator":
            result = calculate_expression(
                text
            )

            await update.message.reply_text(
                f"🧮 <b>Result:</b>\n<code>{result}</code>",
                parse_mode=ParseMode.HTML,
            )

        elif tool == "unit":
            result = unit_convert(text)

            await update.message.reply_text(
                f"📏 <b>Result</b>\n\n{result}",
                parse_mode=ParseMode.HTML,
            )

        elif tool == "date_calc":
            result = date_calculator(text)

            await update.message.reply_text(
                result,
                parse_mode=ParseMode.HTML,
            )

        elif tool == "random":
            result = random_generator(text)

            await update.message.reply_text(
                f"🎲 <b>Random Result:</b>\n\n{result}",
                parse_mode=ParseMode.HTML,
            )

        elif tool == "uuid":
            await update.message.reply_text(
                f"🆔 <code>{uuid.uuid4()}</code>",
                parse_mode=ParseMode.HTML,
            )

        elif tool == "password":
            length = 16

            if text.isdigit():
                length = int(text)

            result = password_generator(
                length
            )

            await update.message.reply_text(
                "🔑 <b>Password Generated</b>\n\n"
                f"<code>{result}</code>",
                parse_mode=ParseMode.HTML,
            )

        elif tool == "qr":
            data = make_qr(text)

            await send_result(
                update.message,
                data,
                "qr.png",
                "🔳 QR Generated",
            )

        add_history(
            uid,
            UTILITY_TOOLS.get(tool, tool),
        )

        add_xp(uid)

    except Exception as e:
        await update.message.reply_text(
            "❌ <b>ERROR</b>\n\n"
            f"<code>{str(e)[:1200]}</code>",
            parse_mode=ParseMode.HTML,
        )

    context.user_data.pop(
        "utility_tool",
        None,
    )


# ============================================================
# TOOL CALLBACK
# ============================================================

async def tool_callback(update, context):
    query = update.callback_query

    await safe_answer(query)

    uid = update.effective_user.id

    if is_banned(uid):
        await safe_edit(
            query,
            "🚫 আপনার অ্যাকাউন্টটি বন্ধ করা হয়েছে।",
        )
        return

    data = query.data

    if data == "dl:menu":
        await safe_answer(query)
        await safe_edit(query, "📥 <b>Video Downloader</b>\n\nLink পাঠাতে নিচের button চাপুন বা সরাসরি URL পাঠান।", InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Send URL", callback_data="dl:send")], [InlineKeyboardButton("📜 History", callback_data="dl:history"), InlineKeyboardButton("📊 Stats", callback_data="dl:stats")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]))
        return

    if data == "dl:send":
        context.user_data["downloader_waiting_url"] = True
        await safe_edit(query, "🔗 <b>Video URL পাঠান</b>\n\nYouTube/Facebook/Instagram/TikTok বা supported public URL দিন।", back_keyboard("main"))
        return

    if data == "dl:history":
        await downloader_history_message(update, uid)
        return

    if data == "dl:stats":
        stats = dl_stats(uid)
        await safe_edit(query, f"📊 <b>MY DOWNLOADER STATS</b>\n\n📥 Total: <b>{stats['total']}</b>\n✅ Success: <b>{stats['success']}</b>\n❌ Failed: <b>{stats['failed']}</b>\n🛑 Cancelled: <b>{stats['cancelled']}</b>", back_keyboard("main"))
        return

    if data.startswith("dlq:") or data.startswith("dla:"):
        parts = data.split(":")
        job_key = parts[1]
        cache = DL_URL_CACHE.get(job_key)
        if not cache or cache.get("user_id") != uid:
            await safe_edit(query, "❌ এই download option আর available নেই। আবার URL পাঠান।", back_keyboard("main"))
            return
        kind = "audio" if data.startswith("dla:") else "video"
        quality = "audio" if kind == "audio" else parts[2]
        job = dl_make_job(uid, cache, kind, quality)
        await safe_edit(query, f"📋 <b>Queued</b>\n\n🎬 {dl_clean_title(job['title'])}\n🎞️ {quality}\n\nQueue-তে যোগ করা হয়েছে।")
        if DL_QUEUE is None:
            globals()["DL_QUEUE"] = asyncio.Queue()
        await DL_QUEUE.put(job)
        return

    if data.startswith("dlcancel:"):
        job_id = data.split(":",1)[1]
        job = DL_JOBS.get(job_id)
        if job and job.get("user_id") == uid and job.get("status") in ("queued","downloading"):
            job["cancel"].set()
            if job.get("status") == "queued":
                job["status"] = "cancelled"
                dl_job_db(job)
                dl_history_add(uid, job["url"], job["title"], job["kind"], job["quality"], "", "cancelled", "Cancelled by user")
            await safe_edit(query, "🛑 <b>Download Cancelled</b>", back_keyboard("main"))
        else:
            await safe_answer(query, "Already finished or unavailable.")
        return

    if data.startswith("dlretry:"):
        old_id = data.split(":",1)[1]
        old = DL_JOBS.get(old_id)
        if not old or old.get("user_id") != uid:
            await safe_answer(query, "Retry unavailable", True)
            return
        cache = {"url": old["url"], "title": old["title"], "user_id": uid}
        job = dl_make_job(uid, cache, old["kind"], old["quality"])
        if DL_QUEUE is None:
            globals()["DL_QUEUE"] = asyncio.Queue()
        await DL_QUEUE.put(job)
        await safe_edit(query, "🔄 <b>Retry added to queue.</b>", back_keyboard("main"))
        return

    if data == "main":
        await safe_edit(
            query,
            "🏠 <b>Main Menu</b>\n\n"
            "নিচের Reply Keyboard ব্যবহার করুন।",
        )
        return

    if data == "pdfmenu":
        await safe_edit(
            query,
            "📕 <b>PDF TOOLS</b>",
            grid_buttons(PDF_TOOLS),
        )
        return

    if data == "imagemenu":
        await safe_edit(
            query,
            "🖼️ <b>IMAGE TOOLS</b>",
            grid_buttons(IMAGE_TOOLS),
        )
        return

    if data.startswith("lang:"):
        selected = data.split(":", 1)[1]

        if selected not in TEXTS:
            selected = "bn"

        conn = db()

        conn.execute(
            """
            UPDATE users
            SET language=?
            WHERE user_id=?
            """,
            (
                selected,
                uid,
            ),
        )

        conn.commit()
        conn.close()

        await safe_edit(
            query,
            "✅ Language Updated.",
            back_keyboard("main"),
        )
        return

    if data.startswith("premium:"):
        action = data.split(":", 1)[1]

        if action == "weekly":
            await create_premium_request(
                update,
                "weekly",
            )
            return

        if action == "monthly":
            await create_premium_request(
                update,
                "monthly",
            )
            return

        if action == "status":
            await premium_status(
                update,
                context,
            )
            return

    if data.startswith("premapprove:"):
        if not is_admin(uid):
            return

        request_id = int(
            data.split(":", 1)[1]
        )

        await approve_premium(
            update,
            context,
            request_id,
        )
        return

    if data.startswith("premreject:"):
        if not is_admin(uid):
            return

        request_id = int(
            data.split(":", 1)[1]
        )

        await reject_premium(
            update,
            context,
            request_id,
        )
        return

    if data.startswith("admin:"):
        if not is_admin(uid):
            return

        action = data.split(":", 1)[1]

        if action == "stats":
            await admin_stats_message(
                update,
                context,
            )

        elif action == "users":
            await safe_edit(
                query,
                "👥 <b>User Management</b>\n\n"
                "Commands:\n"
                "/userinfo USER_ID\n"
                "/ban USER_ID\n"
                "/unban USER_ID\n"
                "/addcredits USER_ID AMOUNT",
                admin_keyboard(),
            )

        elif action == "premium":
            await premium_requests(
                update,
                context,
            )

        elif action == "redeem":
            await safe_edit(
                query,
                "🎟️ <b>Redeem Management</b>\n\n"
                "/createredeem CODE CREDITS USES\n"
                "/redeems",
                admin_keyboard(),
            )

        elif action == "broadcast":
            await safe_edit(
                query,
                "📢 <b>Broadcast</b>\n\n"
                "/broadcast\n"
                "/broadcastpremium\n"
                "/broadcastfree\n"
                "/cancelbroadcast JOB_ID\n"
                "/retrybroadcast JOB_ID",
                admin_keyboard(),
            )

        elif action == "ban":
            await safe_edit(
                query,
                "🚫 <b>Ban / Unban</b>\n\n"
                "/ban USER_ID\n"
                "/unban USER_ID",
                admin_keyboard(),
            )

        elif action == "tickets":
            await tickets(update, context)

        elif action == "settings":
            await safe_edit(
                query,
                "⚙️ <b>Admin Settings</b>\n\n"
                "/adminsettings",
                admin_keyboard(),
            )

        return

    if data.startswith("tool:"):
        tool = data.split(":", 1)[1]

        if tool in TEXT_TOOLS:
            context.user_data["text_tool"] = tool

            prompts = {
                "word_count": "📝 Text পাঠান।",
                "upper": "🔠 যে Text UPPERCASE করতে চান পাঠান।",
                "lower": "🔡 যে Text lowercase করতে চান পাঠান।",
                "title": "🔤 Text পাঠান।",
                "clean": "🧹 Clean করার Text পাঠান।",
                "json": "📋 JSON পাঠান।",
                "url_encode": "🔗 URL/Text পাঠান।",
                "url_decode": "🔓 Encoded URL পাঠান।",
                "base64_encode": "🔐 Text পাঠান।",
                "base64_decode": "🔓 Base64 পাঠান।",
                "encrypt": (
                    "🔒 Format:\n"
                    "<code>password|||text</code>"
                ),
                "decrypt": (
                    "🔓 Format:\n"
                    "<code>password|||encrypted_text</code>"
                ),
            }

            await safe_edit(
                query,
                prompts.get(
                    tool,
                    "📝 Text পাঠান।",
                ),
                back_keyboard("main"),
            )

            return

        if tool in UTILITY_TOOLS:
            if tool == "uuid":
                await safe_edit(
                    query,
                    f"🆔 <b>UUID</b>\n\n"
                    f"<code>{uuid.uuid4()}</code>",
                    back_keyboard("main"),
                )
                return

            if tool == "password":
                result = password_generator(16)

                await safe_edit(
                    query,
                    "🔑 <b>Password Generated</b>\n\n"
                    f"<code>{result}</code>",
                    back_keyboard("main"),
                )
                return

            context.user_data[
                "utility_tool"
            ] = tool

            prompts = {
                "calculator": (
                    "🧮 Example:\n"
                    "<code>(25+5)*2</code>"
                ),
                "unit": (
                    "📏 Example:\n"
                    "<code>10 km to mile</code>"
                ),
                "date_calc": (
                    "📅 Example:\n"
                    "<code>2026-09-22 + 30</code>"
                ),
                "random": (
                    "🎲 Example:\n"
                    "<code>1-100</code>\n"
                    "অথবা\n"
                    "<code>Apple, Banana, Mango</code>"
                ),
                "qr": "🔳 QR-এ যেটা রাখতে চান পাঠান।",
            }

            await safe_edit(
                query,
                prompts.get(
                    tool,
                    "Input পাঠান।",
                ),
                back_keyboard("main"),
            )

            return

        if tool in PDF_TOOLS:
            context.user_data[
                "selected_tool"
            ] = tool

            prompts = {
                "pdf_merge": (
                    "🔗 <b>PDF Merge</b>\n\n"
                    "একাধিক PDF একে একে পাঠান।\n"
                    "সবশেষে /done লিখুন।"
                ),
                "pdf_split": (
                    "✂️ <b>PDF Split</b>\n\n"
                    "প্রথমে PDF পাঠান।\n"
                    "তারপর Page Number পাঠান।"
                ),
                "pdf_extract": (
                    "📑 <b>Page Extract</b>\n\n"
                    "PDF পাঠান।\n"
                    "তারপর লিখুন:\n"
                    "<code>1-5</code>"
                ),
                "pdf_rotate": (
                    "🔄 <b>Rotate PDF</b>\n\n"
                    "PDF পাঠানোর পরে angle লিখুন:\n"
                    "<code>90</code>"
                ),
                "pdf_resize": (
                    "📐 <b>Page Size</b>\n\n"
                    "PDF পাঠান।\n"
                    "তারপর লিখুন:\n"
                    "<code>A4</code>\n"
                    "অথবা A5 / LETTER / LEGAL"
                ),
                "pdf_watermark": (
                    "💧 PDF পাঠান।\n"
                    "তারপর Watermark Text পাঠান।"
                ),
                "pdf_protect": (
                    "🔐 PDF পাঠান।\n"
                    "তারপর Password পাঠান।"
                ),
                "pdf_unlock": (
                    "🔓 Password-protected PDF পাঠান।\n"
                    "তারপর Password পাঠান।"
                ),
                "pdf_xps": (
                    "📦 PDF পাঠান।\n"
                    "Server-এ Ghostscript থাকলে XPS তৈরি হবে।"
                ),
            }

            await safe_edit(
                query,
                prompts.get(
                    tool,
                    f"📕 <b>{PDF_TOOLS[tool]}</b>\n\n"
                    "PDF file পাঠান।",
                ),
                back_keyboard("main"),
            )

            return

        if tool in IMAGE_TOOLS:
            context.user_data[
                "selected_tool"
            ] = tool

            prompts = {
                "img_resize": (
                    "📏 Image পাঠান।\n"
                    "তারপর লিখুন:\n"
                    "<code>800</code>\n"
                    "অথবা <code>800x600</code>"
                ),
                "img_crop": (
                    "✂️ Image পাঠান।\n"
                    "তারপর লিখুন:\n"
                    "<code>x,y,width,height</code>"
                ),
                "img_watermark": (
                    "💧 Image পাঠান।\n"
                    "তারপর Watermark Text পাঠান।"
                ),
                "img_rotate": (
                    "🔄 Image পাঠান।\n"
                    "তারপর angle পাঠান।\n"
                    "Example: <code>90</code>"
                ),
                "img_multi_pdf": (
                    "📚 একাধিক Image পাঠান।\n"
                    "সবশেষে /doneimages লিখুন।"
                ),
            }

            await safe_edit(
                query,
                prompts.get(
                    tool,
                    f"🖼️ <b>{IMAGE_TOOLS[tool]}</b>\n\n"
                    "Image পাঠান।",
                ),
                back_keyboard("main"),
            )

            return


# ============================================================
# DOCUMENT HANDLER
# ============================================================

async def document_handler(update, context):
    uid = update.effective_user.id

    if is_banned(uid):
        return

    tool = context.user_data.get(
        "selected_tool"
    )

    if not tool:
        await update.message.reply_text(
            "ℹ️ আগে PDF Tools অথবা Image Tools থেকে একটি Tool নির্বাচন করুন।"
        )
        return

    document = update.message.document

    file_size = document.file_size or 0

    premium = is_premium(uid)

    allowed, limit = check_file_size(
        file_size,
        premium,
    )

    if not allowed:
        await update.message.reply_text(
            "❌ <b>FILE TOO LARGE</b>\n\n"
            f"আপনার Limit: <b>{limit} MB</b>\n"
            "💎 Premium নিলে বেশি Limit পাওয়া যাবে।",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        data = await download_document(
            update,
            context,
        )

        if not data:
            raise ValueError(
                "File download failed."
            )

        if tool.startswith("pdf_"):
            if not document.file_name.lower().endswith(
                ".pdf"
            ):
                raise ValueError(
                    "এই Tool-এর জন্য PDF file পাঠান।"
                )

            if tool == "pdf_merge":
                files = context.user_data.setdefault(
                    "pdf_files",
                    [],
                )

                files.append(data)

                await update.message.reply_text(
                    f"📥 PDF #{len(files)} received.\n\n"
                    "আরও PDF পাঠান অথবা /done দিন।"
                )

                return

            if tool in {
                "pdf_split",
                "pdf_extract",
                "pdf_rotate",
                "pdf_resize",
                "pdf_watermark",
                "pdf_protect",
                "pdf_unlock",
            }:
                context.user_data[
                    "pending_file"
                ] = data

                await update.message.reply_text(
                    "✅ PDF received.\n\n"
                    "এখন প্রয়োজনীয় Input পাঠান।"
                )

                return

            await process_pdf(
                update,
                context,
                tool,
                data,
            )

        elif tool.startswith("img_"):
            if not (
                document.mime_type
                and document.mime_type.startswith(
                    "image/"
                )
            ):
                raise ValueError(
                    "এই Tool-এর জন্য Image file পাঠান।"
                )

            if tool == "img_multi_pdf":
                files = context.user_data.setdefault(
                    "image_files",
                    [],
                )

                files.append(data)

                await update.message.reply_text(
                    f"📥 Image #{len(files)} received.\n\n"
                    "আরও Image পাঠান অথবা /doneimages দিন।"
                )

                return

            if tool in {
                "img_resize",
                "img_crop",
                "img_watermark",
                "img_rotate",
            }:
                context.user_data[
                    "pending_file"
                ] = data

                await update.message.reply_text(
                    "✅ Image received.\n\n"
                    "এখন প্রয়োজনীয় Input পাঠান।"
                )

                return

            await process_image(
                update,
                context,
                tool,
                data,
            )

    except Exception as e:
        add_history(
            uid,
            tool,
            "ERROR",
        )

        await update.message.reply_text(
            "❌ <b>ERROR</b>\n\n"
            f"<code>{str(e)[:1500]}</code>\n\n"
            "🔄 আবার চেষ্টা করুন।",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# PHOTO HANDLER
# ============================================================

async def photo_handler(update, context):
    uid = update.effective_user.id

    if is_banned(uid):
        return

    tool = context.user_data.get(
        "selected_tool"
    )

    if not tool:
        await update.message.reply_text(
            "ℹ️ আগে Image Tools থেকে একটি Tool নির্বাচন করুন।"
        )
        return

    if not tool.startswith("img_"):
        await update.message.reply_text(
            "ℹ️ Image Tools থেকে একটি Image Tool নির্বাচন করুন।"
        )
        return

    try:
        data = await download_photo(
            update,
            context,
        )

        if tool == "img_multi_pdf":
            files = context.user_data.setdefault(
                "image_files",
                [],
            )

            files.append(data)

            await update.message.reply_text(
                f"📥 Image #{len(files)} received.\n\n"
                "আরও Image পাঠান অথবা /doneimages দিন।"
            )

            return

        if tool in {
            "img_resize",
            "img_crop",
            "img_watermark",
            "img_rotate",
        }:
            context.user_data[
                "pending_file"
            ] = data

            await update.message.reply_text(
                "✅ Image received.\n\n"
                "এখন প্রয়োজনীয় Input পাঠান।"
            )

            return

        await process_image(
            update,
            context,
            tool,
            data,
        )

    except Exception as e:
        await update.message.reply_text(
            "❌ <b>ERROR</b>\n\n"
            f"<code>{str(e)[:1200]}</code>",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# PDF PROCESS
# ============================================================

async def process_pdf(
    update,
    context,
    tool,
    data,
):
    uid = update.effective_user.id

    title = PDF_TOOLS.get(
        tool,
        "PDF Tool",
    )

    progress = await create_progress(
        update.message,
        title,
    )

    try:
        await progress_before(
            progress,
            title,
        )

        if tool == "pdf_word":
            result = await asyncio.to_thread(
                pdf_to_word,
                data,
            )
            filename = "converted.docx"

        elif tool == "pdf_text":
            result = await asyncio.to_thread(
                pdf_to_text,
                data,
            )
            filename = "converted.txt"

        elif tool == "pdf_images":
            result = await asyncio.to_thread(
                pdf_to_images_zip,
                data,
                "png",
            )
            filename = "pdf_images.zip"

        elif tool == "pdf_compress":
            result = await asyncio.to_thread(
                compress_pdf,
                data,
            )
            filename = "compressed.pdf"

        elif tool == "pdf_rotate":
            angle = context.user_data.pop(
                "pending_input",
                90,
            )

            result = await asyncio.to_thread(
                rotate_pdf,
                data,
                int(angle),
            )

            filename = "rotated.pdf"

        elif tool == "pdf_resize":
            size = context.user_data.pop(
                "pending_input",
                "A4",
            )

            result = await asyncio.to_thread(
                resize_pdf,
                data,
                size,
            )

            filename = "resized.pdf"

        elif tool == "pdf_numbers":
            result = await asyncio.to_thread(
                add_page_numbers,
                data,
            )
            filename = "page_numbers.pdf"

        elif tool == "pdf_watermark":
            text = context.user_data.pop(
                "pending_input",
                "Rafim Tools",
            )

            result = await asyncio.to_thread(
                watermark_pdf,
                data,
                text,
            )

            filename = "watermarked.pdf"

        elif tool == "pdf_metadata":
            result = await asyncio.to_thread(
                remove_pdf_metadata,
                data,
            )
            filename = "clean_metadata.pdf"

        elif tool == "pdf_info":
            info = await asyncio.to_thread(
                pdf_info,
                data,
            )

            await progress_after(
                progress,
                title,
            )

            await progress.edit_text(
                info,
                parse_mode=ParseMode.HTML,
            )

            add_history(
                uid,
                title,
            )

            add_xp(uid)

            return

        elif tool == "pdf_protect":
            password = context.user_data.pop(
                "pending_input",
                "",
            )

            if not password:
                raise ValueError(
                    "Password required."
                )

            result = await asyncio.to_thread(
                protect_pdf,
                data,
                password,
            )

            filename = "protected.pdf"

        elif tool == "pdf_unlock":
            password = context.user_data.pop(
                "pending_input",
                "",
            )

            if not password:
                raise ValueError(
                    "Password required."
                )

            result = await asyncio.to_thread(
                unlock_pdf,
                data,
                password,
            )

            filename = "unlocked.pdf"

        elif tool == "pdf_xps":
            result = await asyncio.to_thread(
                pdf_to_xps,
                data,
            )

            filename = "converted.xps"

        else:
            raise ValueError(
                "Unknown PDF Tool."
            )

        await progress_after(
            progress,
            title,
        )

        await send_result(
            update.message,
            result,
            filename,
            f"✅ {title} SUCCESS",
        )

        add_history(
            uid,
            title,
        )

        add_xp(uid)

    except Exception as e:
        await progress.edit_text(
            "❌ <b>ERROR</b>\n\n"
            f"<code>{str(e)[:1800]}</code>\n\n"
            "🔄 Retry করে আবার চেষ্টা করুন।",
            parse_mode=ParseMode.HTML,
        )

        add_history(
            uid,
            title,
            "ERROR",
        )

    finally:
        context.user_data.pop(
            "pending_file",
            None,
        )


# ============================================================
# IMAGE PROCESS
# ============================================================

async def process_image(
    update,
    context,
    tool,
    data,
):
    uid = update.effective_user.id

    title = IMAGE_TOOLS.get(
        tool,
        "Image Tool",
    )

    progress = await create_progress(
        update.message,
        title,
    )

    try:
        await progress_before(
            progress,
            title,
        )

        if tool == "img_compress":
            result = await asyncio.to_thread(
                compress_image,
                data,
            )
            filename = "compressed.jpg"

        elif tool == "img_resize":
            value = context.user_data.pop(
                "pending_input",
                "1000",
            )

            if "x" in str(value).lower():
                w, h = re.split(
                    r"x",
                    str(value),
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )

                result = await asyncio.to_thread(
                    resize_image,
                    data,
                    int(w),
                    int(h),
                )
            else:
                result = await asyncio.to_thread(
                    resize_image,
                    data,
                    int(value),
                )

            filename = "resized.png"

        elif tool == "img_crop":
            values = context.user_data.pop(
                "pending_input",
                "",
            ).split(",")

            if len(values) != 4:
                raise ValueError(
                    "Format: x,y,width,height"
                )

            result = await asyncio.to_thread(
                crop_image,
                data,
                *map(int, values),
            )

            filename = "cropped.png"

        elif tool == "img_jpg":
            result = await asyncio.to_thread(
                convert_image,
                data,
                "JPG",
            )
            filename = "converted.jpg"

        elif tool == "img_png":
            result = await asyncio.to_thread(
                convert_image,
                data,
                "PNG",
            )
            filename = "converted.png"

        elif tool == "img_webp":
            result = await asyncio.to_thread(
                convert_image,
                data,
                "WEBP",
            )
            filename = "converted.webp"

        elif tool == "img_pdf":
            result = await asyncio.to_thread(
                image_to_pdf,
                data,
            )
            filename = "image.pdf"

        elif tool == "img_watermark":
            text = context.user_data.pop(
                "pending_input",
                "Rafim Tools",
            )

            result = await asyncio.to_thread(
                image_watermark,
                data,
                text,
            )

            filename = "watermarked.png"

        elif tool == "img_enhance":
            result = await asyncio.to_thread(
                enhance_image,
                data,
            )
            filename = "enhanced.png"

        elif tool == "img_gray":
            result = await asyncio.to_thread(
                grayscale_image,
                data,
            )
            filename = "grayscale.png"

        elif tool == "img_rotate":
            angle = context.user_data.pop(
                "pending_input",
                90,
            )

            result = await asyncio.to_thread(
                rotate_image,
                data,
                int(angle),
            )

            filename = "rotated.png"

        elif tool == "img_flip":
            result = await asyncio.to_thread(
                flip_image,
                data,
            )
            filename = "flipped.png"

        else:
            raise ValueError(
                "Unknown Image Tool."
            )

        await progress_after(
            progress,
            title,
        )

        await send_result(
            update.message,
            result,
            filename,
            f"✅ {title} SUCCESS",
        )

        add_history(
            uid,
            title,
        )

        add_xp(uid)

    except Exception as e:
        await progress.edit_text(
            "❌ <b>ERROR</b>\n\n"
            f"<code>{str(e)[:1500]}</code>\n\n"
            "🔄 Retry করে আবার চেষ্টা করুন।",
            parse_mode=ParseMode.HTML,
        )

        add_history(
            uid,
            title,
            "ERROR",
        )

    finally:
        context.user_data.pop(
            "pending_file",
            None,
        )


# ============================================================
# /DONE
# ============================================================

async def done_command(update, context):
    uid = update.effective_user.id

    files = context.user_data.get(
        "pdf_files",
        [],
    )

    if not files:
        await update.message.reply_text(
            "❌ কোনো PDF জমা হয়নি।"
        )
        return

    progress = await create_progress(
        update.message,
        "📕 PDF Merge",
    )

    try:
        await progress_before(
            progress,
            "📕 PDF Merge",
        )

        result = await asyncio.to_thread(
            merge_pdfs,
            files,
        )

        await progress_after(
            progress,
            "📕 PDF Merge",
        )

        await send_result(
            update.message,
            result,
            "merged.pdf",
            "✅ PDF Merge SUCCESS",
        )

        add_history(
            uid,
            "PDF Merge",
        )

        add_xp(uid)

    except Exception as e:
        await progress.edit_text(
            "❌ <b>ERROR</b>\n\n"
            f"<code>{str(e)[:1200]}</code>",
            parse_mode=ParseMode.HTML,
        )

    finally:
        context.user_data.pop(
            "pdf_files",
            None,
        )


async def done_images(update, context):
    uid = update.effective_user.id

    files = context.user_data.get(
        "image_files",
        [],
    )

    if not files:
        await update.message.reply_text(
            "❌ কোনো Image জমা হয়নি।"
        )
        return

    progress = await create_progress(
        update.message,
        "📚 Images → PDF",
    )

    try:
        await progress_before(
            progress,
            "📚 Images → PDF",
        )

        result = await asyncio.to_thread(
            images_to_pdf,
            files,
        )

        await progress_after(
            progress,
            "📚 Images → PDF",
        )

        await send_result(
            update.message,
            result,
            "images.pdf",
            "✅ Images → PDF SUCCESS",
        )

        add_history(
            uid,
            "Images → PDF",
        )

        add_xp(uid)

    except Exception as e:
        await progress.edit_text(
            "❌ <b>ERROR</b>\n\n"
            f"<code>{str(e)[:1200]}</code>",
            parse_mode=ParseMode.HTML,
        )

    finally:
        context.user_data.pop(
            "image_files",
            None,
        )


# ============================================================
# PENDING INPUT HANDLER
# ============================================================

async def pending_input_handler(
    update,
    context,
):
    if not update.message.text:
        return False

    if (
        "pending_file"
        not in context.user_data
    ):
        return False

    tool = context.user_data.get(
        "selected_tool"
    )

    if not tool:
        return False

    text = update.message.text.strip()

    if tool == "pdf_split":
        try:
            page = int(text)
        except Exception:
            await update.message.reply_text(
                "❌ Page Number দিন। Example: <code>2</code>",
                parse_mode=ParseMode.HTML,
            )
            return True

        data = context.user_data.pop(
            "pending_file"
        )

        progress = await create_progress(
            update.message,
            "✂️ PDF Split",
        )

        try:
            await progress_before(
                progress,
                "✂️ PDF Split",
            )

            result = await asyncio.to_thread(
                split_pdf,
                data,
                page,
            )

            await progress_after(
                progress,
                "✂️ PDF Split",
            )

            await send_result(
                update.message,
                result,
                "split.pdf",
                "✅ PDF Split SUCCESS",
            )

            add_history(
                update.effective_user.id,
                "PDF Split",
            )
            add_xp(
                update.effective_user.id
            )

        except Exception as e:
            await progress.edit_text(
                "❌ <b>ERROR</b>\n\n"
                f"<code>{str(e)[:1200]}</code>",
                parse_mode=ParseMode.HTML,
            )

        return True

    if tool == "pdf_extract":
        m = re.match(
            r"^(\d+)\s*-\s*(\d+)$",
            text,
        )

        if not m:
            await update.message.reply_text(
                "❌ Format: <code>1-5</code>",
                parse_mode=ParseMode.HTML,
            )
            return True

        start_page = int(m.group(1))
        end_page = int(m.group(2))

        data = context.user_data.pop(
            "pending_file"
        )

        progress = await create_progress(
            update.message,
            "📑 Page Extract",
        )

        try:
            await progress_before(
                progress,
                "📑 Page Extract",
            )

            result = await asyncio.to_thread(
                extract_pdf_pages,
                data,
                start_page,
                end_page,
            )

            await progress_after(
                progress,
                "📑 Page Extract",
            )

            await send_result(
                update.message,
                result,
                "extracted.pdf",
                "✅ Page Extract SUCCESS",
            )

            add_history(
                update.effective_user.id,
                "PDF Page Extract",
            )
            add_xp(
                update.effective_user.id
            )

        except Exception as e:
            await progress.edit_text(
                "❌ <b>ERROR</b>\n\n"
                f"<code>{str(e)[:1200]}</code>",
                parse_mode=ParseMode.HTML,
            )

        return True

    if tool in {
        "pdf_rotate",
        "pdf_resize",
        "pdf_watermark",
        "pdf_protect",
        "pdf_unlock",
        "img_resize",
        "img_crop",
        "img_watermark",
        "img_rotate",
    }:
        data = context.user_data.pop(
            "pending_file"
        )

        context.user_data[
            "pending_input"
        ] = text

        if tool.startswith("pdf_"):
            await process_pdf(
                update,
                context,
                tool,
                data,
            )
        else:
            await process_image(
                update,
                context,
                tool,
                data,
            )

        return True

    return False


# ============================================================
# ADMIN DECORATOR
# ============================================================

def admin_only(func):
    @wraps(func)
    async def wrapper(update, context):
        if update.effective_user.id != ADMIN_ID:
            await update.effective_message.reply_text(
                "🚫 Admin Only."
            )
            return

        return await func(
            update,
            context,
        )

    return wrapper


# ============================================================
# ADMIN PANEL
# ============================================================

@admin_only
async def admin_panel(update, context):
    await update.message.reply_text(
        "👑 <b>ADMIN CONTROL PANEL</b>\n\n"
        "সব Admin Control নিচে দেওয়া হলো।",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def admin_stats_message(
    update,
    context,
):
    conn = db()

    users = conn.execute(
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

    tools = conn.execute(
        "SELECT COUNT(*) c FROM history"
    ).fetchone()["c"]

    today_users = conn.execute(
        """
        SELECT COUNT(*) c FROM users
        WHERE substr(created_at,1,10)=?
        """,
        (today(),),
    ).fetchone()["c"]

    conn.close()

    text = (
        "📊 <b>ADMIN STATISTICS</b>\n\n"
        f"👥 Total Users: <b>{fmt_num(users)}</b>\n"
        f"💎 Premium Users: <b>{fmt_num(premium)}</b>\n"
        f"🚫 Banned Users: <b>{fmt_num(banned)}</b>\n"
        f"💰 Total Credits: <b>{fmt_num(credits)}</b>\n"
        f"🛠️ Tool Usage: <b>{fmt_num(tools)}</b>\n"
        f"🆕 Today's New Users: <b>{fmt_num(today_users)}</b>\n"
    )

    if update.callback_query:
        await safe_edit(
            update.callback_query,
            text,
            admin_keyboard(),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )


@admin_only
async def stats(update, context):
    await admin_stats_message(
        update,
        context,
    )


# ============================================================
# USER INFO
# ============================================================

@admin_only
async def userinfo(update, context):
    if not context.args:
        await update.message.reply_text(
            "Usage: /userinfo USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text(
            "❌ Invalid User ID."
        )
        return

    row = get_user(uid)

    if not row:
        await update.message.reply_text(
            "❌ User not found."
        )
        return

    await update.message.reply_text(
        "👤 <b>USER INFO</b>\n\n"
        f"🆔 ID: <code>{row['user_id']}</code>\n"
        f"👤 Name: {row['first_name']}\n"
        f"🔹 Username: @{row['username'] or 'N/A'}\n"
        f"💰 Credits: <b>{row['credits']}</b>\n"
        f"⭐ XP: <b>{row['xp']}</b>\n"
        f"🏆 Level: <b>{level_from_xp(row['xp'])}</b>\n"
        f"🔥 Streak: <b>{row['streak']}</b>\n"
        f"👥 Referrals: <b>{row['referral_count']}</b>\n"
        f"💎 Premium: <b>{'YES' if is_premium(uid) else 'NO'}</b>\n"
        f"🚫 Banned: <b>{'YES' if row['banned'] else 'NO'}</b>\n"
        f"📅 Joined: {row['created_at']}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ADD / REMOVE CREDITS
# ============================================================

@admin_only
async def addcredits(update, context):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /addcredits USER_ID AMOUNT"
        )
        return

    try:
        uid = int(context.args[0])
        amount = int(context.args[1])
    except Exception:
        await update.message.reply_text(
            "❌ Invalid values."
        )
        return

    if not get_user(uid):
        await update.message.reply_text(
            "❌ User not found."
        )
        return

    add_credits(
        uid,
        amount,
        "Admin Credit",
    )

    await update.message.reply_text(
        f"✅ <b>+{amount} Credits Added</b>",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            uid,
            f"🎁 Admin আপনার account-এ <b>+{amount}</b> Credits যোগ করেছেন।",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


# ============================================================
# BAN / UNBAN
# ============================================================

@admin_only
async def ban(update, context):
    if not context.args:
        await update.message.reply_text(
            "Usage: /ban USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text(
            "❌ Invalid ID."
        )
        return

    if uid == ADMIN_ID:
        await update.message.reply_text(
            "❌ নিজের Admin ID ban করা যাবে না।"
        )
        return

    ban_user(uid)

    await update.message.reply_text(
        f"🚫 User <code>{uid}</code> banned.",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def unban(update, context):
    if not context.args:
        await update.message.reply_text(
            "Usage: /unban USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text(
            "❌ Invalid ID."
        )
        return

    unban_user(uid)

    await update.message.reply_text(
        f"✅ User <code>{uid}</code> unbanned.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# PREMIUM ADMIN
# ============================================================

async def approve_premium(
    update,
    context,
    request_id,
):
    conn = db()

    row = conn.execute(
        """
        SELECT * FROM premium_requests
        WHERE id=? AND status='pending'
        """,
        (request_id,),
    ).fetchone()

    if not row:
        conn.close()

        await safe_answer(
            update.callback_query,
            "Request already processed.",
            True,
        )
        return

    days = (
        7
        if row["plan"] == "weekly"
        else 30
    )

    conn.execute(
        """
        UPDATE premium_requests
        SET status='approved', updated_at=?
        WHERE id=?
        """,
        (now(), request_id),
    )

    conn.commit()
    conn.close()

    set_premium(
        row["user_id"],
        days,
    )

    await safe_edit(
        update.callback_query,
        "✅ <b>PREMIUM APPROVED</b>\n\n"
        f"Request #{request_id}\n"
        f"User: <code>{row['user_id']}</code>\n"
        f"Plan: {row['plan']}",
    )

    try:
        await context.bot.send_message(
            row["user_id"],
            "🎉 <b>PREMIUM APPROVED!</b>\n\n"
            f"📦 Plan: <b>{row['plan']}</b>\n"
            f"⏰ Duration: <b>{days} Days</b>\n\n"
            "আপনার Premium এখন Active।",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def reject_premium(
    update,
    context,
    request_id,
):
    conn = db()

    row = conn.execute(
        """
        SELECT * FROM premium_requests
        WHERE id=? AND status='pending'
        """,
        (request_id,),
    ).fetchone()

    if not row:
        conn.close()
        return

    conn.execute(
        """
        UPDATE premium_requests
        SET status='rejected', updated_at=?
        WHERE id=?
        """,
        (now(), request_id),
    )

    conn.commit()
    conn.close()

    await safe_edit(
        update.callback_query,
        "❌ <b>PREMIUM REQUEST REJECTED</b>\n\n"
        f"Request #{request_id}",
    )

    try:
        await context.bot.send_message(
            row["user_id"],
            "❌ আপনার Premium Request reject করা হয়েছে।",
        )
    except Exception:
        pass


@admin_only
async def premium_requests(
    update,
    context,
):
    conn = db()

    rows = conn.execute(
        """
        SELECT * FROM premium_requests
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:
        text = (
            "💎 <b>Premium Requests</b>\n\n"
            "কোনো pending request নেই।"
        )

        if update.callback_query:
            await safe_edit(
                update.callback_query,
                text,
                admin_keyboard(),
            )
        else:
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
            )

        return

    text = "💎 <b>PENDING PREMIUM REQUESTS</b>\n\n"

    buttons = []

    for row in rows:
        text += (
            f"🆔 #{row['id']} | "
            f"User: <code>{row['user_id']}</code> | "
            f"{row['plan']}\n"
        )

        buttons.append(
            [
                InlineKeyboardButton(
                    f"✅ #{row['id']}",
                    callback_data=f"premapprove:{row['id']}",
                ),
                InlineKeyboardButton(
                    f"❌ #{row['id']}",
                    callback_data=f"premreject:{row['id']}",
                ),
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "⬅️ Admin",
                callback_data="admin:stats",
            )
        ]
    )

    markup = InlineKeyboardMarkup(
        buttons
    )

    if update.callback_query:
        await safe_edit(
            update.callback_query,
            text,
            markup,
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )


# ============================================================
# REDEEM ADMIN
# ============================================================

@admin_only
async def create_redeem(update, context):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage:\n"
            "/createredeem CODE CREDITS USES\n\n"
            "Example:\n"
            "/createredeem RAFIM20 20 100"
        )
        return

    code = context.args[0].upper()

    try:
        credits = int(context.args[1])
        uses = int(context.args[2])
    except Exception:
        await update.message.reply_text(
            "❌ Credits/Uses must be number."
        )
        return

    conn = db()

    try:
        conn.execute(
            """
            INSERT INTO redeem_codes
            (code, credits, max_uses, used_count,
             active, created_at)
            VALUES (?, ?, ?, 0, 1, ?)
            """,
            (
                code,
                credits,
                uses,
                now(),
            ),
        )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        await update.message.reply_text(
            "❌ এই Code already exists."
        )
        return

    conn.close()

    await update.message.reply_text(
        "🎟️ <b>REDEEM CREATED</b>\n\n"
        f"Code: <code>{code}</code>\n"
        f"Credits: <b>{credits}</b>\n"
        f"Uses: <b>{uses}</b>",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def redeems(update, context):
    conn = db()

    rows = conn.execute(
        """
        SELECT * FROM redeem_codes
        ORDER BY created_at DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "🎟️ No redeem codes."
        )
        return

    text = "🎟️ <b>REDEEM CODES</b>\n\n"

    for row in rows:
        status = (
            "ON"
            if row["active"]
            else "OFF"
        )

        text += (
            f"🔹 <code>{row['code']}</code>\n"
            f"💰 {row['credits']} Credits | "
            f"📊 {row['used_count']}/{row['max_uses']} | "
            f"{status}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# SUPPORT TICKETS ADMIN
# ============================================================

@admin_only
async def tickets(update, context):
    conn = db()

    rows = conn.execute(
        """
        SELECT * FROM support_tickets
        WHERE status='open'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:
        text = "🎫 কোনো open ticket নেই।"
    else:
        text = "🎫 <b>OPEN TICKETS</b>\n\n"

        for row in rows:
            text += (
                f"#{row['id']} | "
                f"User: <code>{row['user_id']}</code>\n"
                f"{row['message'][:300]}\n\n"
            )

    if update.callback_query:
        await safe_edit(
            update.callback_query,
            text,
            admin_keyboard(),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# BROADCAST
# ============================================================

def create_broadcast_job(
    target,
    message,
):
    conn = db()

    if target == "all":
        total = conn.execute(
            """
            SELECT COUNT(*) c
            FROM users
            WHERE banned=0
            """
        ).fetchone()["c"]

    elif target == "premium":
        total = conn.execute(
            """
            SELECT COUNT(*) c
            FROM users
            WHERE banned=0 AND premium=1
            """
        ).fetchone()["c"]

    else:
        total = conn.execute(
            """
            SELECT COUNT(*) c
            FROM users
            WHERE banned=0 AND premium=0
            """
        ).fetchone()["c"]

    conn.execute(
        """
        INSERT INTO broadcast_jobs
        (admin_id, target, message, status,
         total, sent, failed, created_at, updated_at)
        VALUES (?, ?, ?, 'running', ?, 0, 0, ?, ?)
        """,
        (
            ADMIN_ID,
            target,
            message,
            total,
            now(),
            now(),
        ),
    )

    job_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.commit()
    conn.close()

    return job_id


async def get_broadcast_users(target):
    conn = db()

    if target == "all":
        rows = conn.execute(
            """
            SELECT user_id FROM users
            WHERE banned=0
            """
        ).fetchall()

    elif target == "premium":
        rows = conn.execute(
            """
            SELECT user_id FROM users
            WHERE banned=0 AND premium=1
            """
        ).fetchall()

    else:
        rows = conn.execute(
            """
            SELECT user_id FROM users
            WHERE banned=0 AND premium=0
            """
        ).fetchall()

    conn.close()

    return [int(x["user_id"]) for x in rows]


async def run_broadcast(
    context,
    job_id,
):
    conn = db()

    job = conn.execute(
        """
        SELECT * FROM broadcast_jobs
        WHERE id=?
        """,
        (job_id,),
    ).fetchone()

    conn.close()

    if not job:
        return

    users = await get_broadcast_users(
        job["target"]
    )

    sent = 0
    failed = 0

    for index, uid in enumerate(users, 1):

        conn = db()

        current = conn.execute(
            """
            SELECT status FROM broadcast_jobs
            WHERE id=?
            """,
            (job_id,),
        ).fetchone()

        conn.close()

        if not current:
            break

        if current["status"] == "cancelled":
            break

        try:
            await context.bot.send_message(
                uid,
                job["message"],
                parse_mode=ParseMode.HTML,
            )

            sent += 1

        except Exception as e:
            failed += 1

            conn = db()

            conn.execute(
                """
                INSERT INTO broadcast_failures
                (job_id, user_id, error, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    job_id,
                    uid,
                    str(e)[:500],
                    now(),
                ),
            )

            conn.commit()
            conn.close()

        conn = db()

        conn.execute(
            """
            UPDATE broadcast_jobs
            SET sent=?, failed=?, updated_at=?
            WHERE id=?
            """,
            (
                sent,
                failed,
                now(),
                job_id,
            ),
        )

        conn.commit()
        conn.close()

        if index % 10 == 0:
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    "📢 <b>Broadcast Progress</b>\n\n"
                    f"🆔 Job: <code>#{job_id}</code>\n"
                    f"📊 {index}/{len(users)}\n"
                    f"✅ Sent: {sent}\n"
                    f"❌ Failed: {failed}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        await asyncio.sleep(0.05)

    conn = db()

    status = conn.execute(
        """
        SELECT status FROM broadcast_jobs
        WHERE id=?
        """,
        (job_id,),
    ).fetchone()

    if status and status["status"] != "cancelled":
        conn.execute(
            """
            UPDATE broadcast_jobs
            SET status='completed',
                sent=?,
                failed=?,
                updated_at=?
            WHERE id=?
            """,
            (
                sent,
                failed,
                now(),
                job_id,
            ),
        )

    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(
            ADMIN_ID,
            "✅ <b>BROADCAST FINISHED</b>\n\n"
            f"🆔 Job: <code>#{job_id}</code>\n"
            f"✅ Sent: <b>{sent}</b>\n"
            f"❌ Failed: <b>{failed}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@admin_only
async def broadcast(update, context):
    context.user_data[
        "broadcast_target"
    ] = "all"

    context.user_data[
        "broadcast_mode"
    ] = True

    await update.message.reply_text(
        "📢 <b>BROADCAST MODE</b>\n\n"
        "এখন যে Message পাঠাবেন সেটাই সব User-এর কাছে যাবে।\n\n"
        "❌ Cancel: /cancel\n"
        "⚠️ HTML supported.",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def broadcast_premium(
    update,
    context,
):
    context.user_data[
        "broadcast_target"
    ] = "premium"

    context.user_data[
        "broadcast_mode"
    ] = True

    await update.message.reply_text(
        "💎 <b>PREMIUM BROADCAST MODE</b>\n\n"
        "Premium users-এর জন্য Message পাঠান।",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def broadcast_free(
    update,
    context,
):
    context.user_data[
        "broadcast_target"
    ] = "free"

    context.user_data[
        "broadcast_mode"
    ] = True

    await update.message.reply_text(
        "🆓 <b>FREE USER BROADCAST MODE</b>\n\n"
        "Free users-এর জন্য Message পাঠান।",
        parse_mode=ParseMode.HTML,
    )


async def broadcast_text_handler(
    update,
    context,
):
    if not context.user_data.get(
        "broadcast_mode"
    ):
        return

    if update.effective_user.id != ADMIN_ID:
        return

    text = update.message.text.strip()

    context.user_data[
        "broadcast_mode"
    ] = False

    target = context.user_data.pop(
        "broadcast_target",
        "all",
    )

    job_id = create_broadcast_job(
        target,
        text,
    )

    await update.message.reply_text(
        "📢 <b>Broadcast Started!</b>\n\n"
        f"🆔 Job ID: <code>#{job_id}</code>\n"
        f"🎯 Target: <b>{target}</b>\n\n"
        "Progress এবং final report Admin-এ পাঠানো হবে।\n\n"
        f"Cancel: <code>/cancelbroadcast {job_id}</code>",
        parse_mode=ParseMode.HTML,
    )

    asyncio.create_task(
        run_broadcast(
            context,
            job_id,
        )
    )

    raise ApplicationHandlerStop


@admin_only
async def cancel_broadcast(
    update,
    context,
):
    if not context.args:
        await update.message.reply_text(
            "Usage: /cancelbroadcast JOB_ID"
        )
        return

    try:
        job_id = int(context.args[0])
    except Exception:
        await update.message.reply_text(
            "❌ Invalid Job ID."
        )
        return

    conn = db()

    conn.execute(
        """
        UPDATE broadcast_jobs
        SET status='cancelled', updated_at=?
        WHERE id=? AND status='running'
        """,
        (
            now(),
            job_id,
        ),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🛑 Broadcast <code>#{job_id}</code> cancellation requested.",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def retry_broadcast(
    update,
    context,
):
    if not context.args:
        await update.message.reply_text(
            "Usage: /retrybroadcast JOB_ID"
        )
        return

    try:
        job_id = int(context.args[0])
    except Exception:
        await update.message.reply_text(
            "❌ Invalid Job ID."
        )
        return

    conn = db()

    job = conn.execute(
        """
        SELECT * FROM broadcast_jobs
        WHERE id=?
        """,
        (job_id,),
    ).fetchone()

    failures = conn.execute(
        """
        SELECT user_id FROM broadcast_failures
        WHERE job_id=?
        """,
        (job_id,),
    ).fetchall()

    conn.close()

    if not job:
        await update.message.reply_text(
            "❌ Job not found."
        )
        return

    if not failures:
        await update.message.reply_text(
            "ℹ️ এই Job-এ কোনো failed user নেই।"
        )
        return

    success = 0
    failed = 0

    for row in failures:
        uid = row["user_id"]

        try:
            await context.bot.send_message(
                uid,
                job["message"],
                parse_mode=ParseMode.HTML,
            )
            success += 1

        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        "🔄 <b>Retry Finished</b>\n\n"
        f"✅ Success: <b>{success}</b>\n"
        f"❌ Failed: <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ADMIN SETTINGS
# ============================================================

@admin_only
async def adminsettings(
    update,
    context,
):
    await update.message.reply_text(
        "⚙️ <b>ADMIN SETTINGS</b>\n\n"
        "এই version-এ important settings bot.py-এর Config section-এ রাখা হয়েছে।\n\n"
        f"🎁 Free Credits: <b>{FREE_CREDITS}</b>\n"
        f"🎁 Daily Bonus: <b>{DAILY_BONUS}</b>\n"
        f"👥 Referral Reward: <b>{REFERRAL_REWARD}</b>\n"
        f"⭐ Referral XP: <b>{REFERRAL_XP}</b>\n"
        f"🆓 Free Limit: <b>{FREE_FILE_LIMIT_MB} MB</b>\n"
        f"💎 Premium Limit: <b>{PREMIUM_FILE_LIMIT_MB} MB</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# COMMANDS
# ============================================================

async def help_command(update, context):
    await update.message.reply_text(
        "📚 <b>HELP CENTER</b>\n\n"
        "/start — Start Bot\n"
        "/menu — Main Menu\n"
        "/admin — Admin Panel\n"
        "/done — PDF Merge Complete\n"
        "/doneimages — Images → PDF Complete\n"
        "/cancel — Cancel current mode\n\n"
        "📕 PDF Tools\n"
        "🖼️ Image Tools\n"
        "📝 Text Tools\n"
        "🧮 Utility Tools\n"
        "💎 Premium\n"
        "🎁 Daily Bonus\n"
        "👥 Referral\n"
        "🎟️ Redeem\n"
        "📜 History\n"
        "🆘 Support",
        parse_mode=ParseMode.HTML,
    )


async def cancel(update, context):
    keys = [
        "selected_tool",
        "pending_file",
        "pending_input",
        "pdf_files",
        "image_files",
        "text_tool",
        "utility_tool",
        "redeem",
        "waiting",
        "broadcast_mode",
        "broadcast_target",
        "downloader_waiting_url",
        "direct_chat_target",
    ]

    for key in keys:
        context.user_data.pop(
            key,
            None,
        )

    await update.message.reply_text(
        "🛑 <b>Cancelled</b>\n\n"
        "🏠 Main Menu-তে ফিরে গেছেন।",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ============================================================
# TEXT ROUTER
# ============================================================

async def text_router(update, context):
    if not update.message or not update.message.text:
        return

    uid = update.effective_user.id

    if not get_user(uid):
        ensure_user(
            update.effective_user
        )

    if is_banned(uid):
        await update.message.reply_text(
            tr(uid, "banned"),
        )
        return

    # Admin direct-chat user replies
    if await user_direct_chat_reply(update, context):
        return

    # Downloader URL / pending URL
    if context.user_data.get("downloader_waiting_url"):
        text_value = update.message.text.strip()
        if dl_is_url(text_value):
            await downloader_show_info(update, context, text_value)
        else:
            await update.message.reply_text("❌ Valid http/https URL দিন।")
        return

    # URL auto-detection
    if dl_is_url(update.message.text.strip()):
        await downloader_show_info(update, context, update.message.text.strip())
        return

    # Pending file input
    if await pending_input_handler(
        update,
        context,
    ):
        return

    # Redeem
    if context.user_data.get(
        "waiting"
    ) == "redeem":
        context.user_data.pop(
            "waiting",
            None,
        )

        await process_redeem(
            update,
            update.message.text,
        )
        return

    # Text tools
    text_tool = context.user_data.get(
        "text_tool"
    )

    if text_tool:
        await process_text_tool(
            update,
            context,
            text_tool,
        )
        return

    # Utility tools
    utility_tool = context.user_data.get(
        "utility_tool"
    )

    if utility_tool:
        await process_utility(
            update,
            context,
            utility_tool,
        )
        return

    # Reply Keyboard
    text = update.message.text.strip()

    if text == "📕 PDF Tools":
        await pdf_menu(update, context)
        return

    if text == "🖼️ Image Tools":
        await image_menu(update, context)
        return

    if text == "📝 Text Tools":
        await text_menu(update, context)
        return

    if text == "🧮 Utility Tools":
        await utility_menu(update, context)
        return

    if text == "📥 Video Downloader":
        await downloader_menu(update, context)
        return

    if text == "💎 Premium":
        await premium(update, context)
        return

    if text == "👤 Account":
        await account(update, context)
        return

    if text == "🎁 Daily Bonus":
        await daily_bonus(update, context)
        return

    if text == "👥 Referral":
        await referral(update, context)
        return

    if text == "🎟️ Redeem":
        await redeem(update, context)
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

    if text == "🏠 Main Menu":
        await main_menu(update, context)
        return

    await update.message.reply_text(
        "ℹ️ নিচের Menu থেকে একটি Option নির্বাচন করুন।",
        reply_markup=main_keyboard(),
    )


# ============================================================
# PREMIUM EXPIRY WATCHER
# ============================================================

async def premium_expiry_watcher(
    application,
):
    while True:
        try:
            conn = db()

            rows = conn.execute(
                """
                SELECT user_id
                FROM users
                WHERE premium=1
                AND premium_until != ''
                AND premium_until < ?
                """,
                (datetime.now().isoformat(sep=" "),),
            ).fetchall()

            for row in rows:
                conn.execute(
                    """
                    UPDATE users
                    SET premium=0
                    WHERE user_id=?
                    """,
                    (row["user_id"],),
                )

            conn.commit()
            conn.close()

            for row in rows:
                try:
                    await application.bot.send_message(
                        row["user_id"],
                        "⏰ আপনার Premium মেয়াদ শেষ হয়েছে।",
                    )
                except Exception:
                    pass

        except Exception:
            pass

        await asyncio.sleep(300)


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):
    try:
        print(
            "ERROR:",
            repr(context.error),
        )
    except Exception:
        pass


# ============================================================
# POST INIT
# ============================================================

async def post_init(application):
    global DL_QUEUE
    if DL_QUEUE is None:
        DL_QUEUE = asyncio.Queue()
    asyncio.create_task(
        premium_expiry_watcher(
            application
        )
    )
    asyncio.create_task(
        downloader_worker(application)
    )


# ============================================================
# MAIN
# ============================================================

def main():
    init_db()

    import threading

    threading.Thread(
        target=run_web,
        daemon=True,
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "menu",
            main_menu,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel,
        )
    )

    application.add_handler(
        CommandHandler(
            "done",
            done_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "chat",
            admin_direct_chat_start,
        )
    )

    application.add_handler(
        CommandHandler(
            "endchat",
            admin_direct_chat_end,
        )
    )

    application.add_handler(
        CommandHandler(
            "downloadstats",
            downloader_admin_stats,
        )
    )

    application.add_handler(
        CommandHandler(
            "doneimages",
            done_images,
        )
    )

    # Admin
    application.add_handler(
        CommandHandler(
            "admin",
            admin_panel,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats,
        )
    )

    application.add_handler(
        CommandHandler(
            "userinfo",
            userinfo,
        )
    )

    application.add_handler(
        CommandHandler(
            "addcredits",
            addcredits,
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            ban,
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            unban,
        )
    )

    application.add_handler(
        CommandHandler(
            "createredeem",
            create_redeem,
        )
    )

    application.add_handler(
        CommandHandler(
            "redeems",
            redeems,
        )
    )

    application.add_handler(
        CommandHandler(
            "tickets",
            tickets,
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast,
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcastpremium",
            broadcast_premium,
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcastfree",
            broadcast_free,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancelbroadcast",
            cancel_broadcast,
        )
    )

    application.add_handler(
        CommandHandler(
            "retrybroadcast",
            retry_broadcast,
        )
    )

    application.add_handler(
        CommandHandler(
            "adminsettings",
            adminsettings,
        )
    )

    # Callback
    application.add_handler(
        CallbackQueryHandler(
            tool_callback
        )
    )

    # Admin direct chat MUST run before broadcast/normal text
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(user_id=ADMIN_ID),
            admin_direct_chat_text,
        ),
        group=0,
    )

    # Broadcast text MUST run before normal text
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.User(
                user_id=ADMIN_ID
            ),
            broadcast_text_handler,
        ),
        group=0,
    )

    # User replies in Admin Direct Chat
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            user_direct_chat_reply,
        ),
        group=1,
    )

    # Normal text
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_router,
        ),
        group=2,
    )

    # Documents
    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler,
        )
    )

    # Photos
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("Rafim Tools Bot Started...")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
