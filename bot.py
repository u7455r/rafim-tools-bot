# ============================================================
# RAFIM MULTI-PRO — ALL-IN-ONE TELEGRAM BOT (FULL ENGINE)
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
#     qrcode
#     requests
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
import hashlib
import urllib.parse
from datetime import datetime, date, timedelta

import fitz
from PIL import Image, ImageOps, ImageEnhance
from docx import Document
from flask import Flask

import qrcode
import requests

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

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "8298133943"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "rafimhossen")

BKASH_NUMBER = os.getenv("BKASH_NUMBER", "YOUR bKASH NUMBER").strip()
NAGAD_NUMBER = os.getenv("NAGAD_NUMBER", "YOUR NAGAD NUMBER").strip()

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
    return "Rafim Multi-Pro Engine is running!"

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
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
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
        language TEXT DEFAULT 'bn',
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
        language TEXT DEFAULT 'bn',
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
# USER & PREMIUM UTILS
# ============================================================

def referral_code_for(user_id):
    return f"R{user_id}"

def get_user(user_id):
    con = db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row

def ensure_user(tg_user, referred_by=None):
    uid = tg_user.id
    now = datetime.now().isoformat()
    existing = get_user(uid)

    if existing:
        con = db()
        con.execute(
            "UPDATE users SET username=?, first_name=? WHERE user_id=?",
            (tg_user.username or "", tg_user.first_name or "", uid)
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
        INSERT OR REPLACE INTO user_settings(user_id,language,notifications)
        VALUES(?,?,?)
    """, (uid, "bn", 1))

    con.commit()
    con.close()
    return get_user(uid), True

def is_banned(user_id):
    u = get_user(user_id)
    return bool(u and u["banned"])

def is_premium(user_id):
    u = get_user(user_id)
    if not u or not u["premium"]:
        return False
    if u["premium_until"]:
        try:
            expiry = datetime.fromisoformat(u["premium_until"])
            if datetime.now() > expiry:
                con = db()
                con.execute("UPDATE users SET premium=0 WHERE user_id=?", (user_id,))
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
        expiry = datetime.fromisoformat(u["premium_until"])
        if datetime.now() >= expiry:
            return "❌ Expired"
        return expiry.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "N/A"

async def premium_expiry_watcher(application):
    while True:
        try:
            now = datetime.now().isoformat()
            con = db()
            rows = con.execute("""
                SELECT user_id,premium_until FROM users
                WHERE premium=1 AND premium_until IS NOT NULL AND premium_until <= ?
            """, (now,)).fetchall()

            if rows:
                con.execute("""
                    UPDATE users SET premium=0
                    WHERE premium=1 AND premium_until IS NOT NULL AND premium_until <= ?
                """, (now,))
                con.commit()
            con.close()

            for row in rows:
                try:
                    await application.bot.send_message(
                        row["user_id"],
                        "⏰ <b>PREMIUM EXPIRED!</b>\n\n💎 আপনার Premium membership-এর মেয়াদ শেষ হয়েছে।",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(60)

def add_credits(user_id, amount, reason=""):
    con = db()
    con.execute("UPDATE users SET credits=credits+? WHERE user_id=?", (amount, user_id))
    con.execute("""
        INSERT INTO credit_history(user_id,amount,reason,created_at)
        VALUES(?,?,?,?)
    """, (user_id, amount, reason, datetime.now().isoformat()))
    con.commit()
    con.close()

def remove_credits(user_id, amount, reason=""):
    u = get_user(user_id)
    if not u or u["credits"] < amount:
        return False
    add_credits(user_id, -amount, reason)
    return True

def add_xp(user_id, amount):
    con = db()
    u = get_user(user_id)
    if not u:
        con.close()
        return
    xp = u["xp"] + amount
    level = max(1, (xp // 100) + 1)
    con.execute("UPDATE users SET xp=?,level=? WHERE user_id=?", (xp, level, user_id))
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
            old = date.fromisoformat(u["last_streak"])
            if old == date.today() - timedelta(days=1):
                streak = u["streak"] + 1
        except Exception:
            pass
    con = db()
    con.execute("UPDATE users SET streak=?,last_streak=? WHERE user_id=?", (streak, today, user_id))
    con.commit()
    con.close()

def log_history(user_id, tool, status, filename="", credits=0):
    con = db()
    con.execute("""
        INSERT INTO history(user_id,tool,status,filename,credits,created_at)
        VALUES(?,?,?,?,?,?)
    """, (user_id, tool, status, filename, credits, datetime.now().isoformat()))
    con.commit()
    con.close()

def create_job(user_id, tool, filename):
    job = str(uuid.uuid4())[:12]
    con = db()
    con.execute("""
        INSERT INTO jobs(job_id,user_id,tool,filename,status,created_at)
        VALUES(?,?,?,?,?,?)
    """, (job, user_id, tool, filename, "processing", datetime.now().isoformat()))
    con.commit()
    con.close()
    return job

def finish_job(job_id, status):
    con = db()
    con.execute("UPDATE jobs SET status=?,finished_at=? WHERE job_id=?", (status, datetime.now().isoformat(), job_id))
    con.commit()
    con.close()

def max_file_mb(user_id):
    return PREMIUM_FILE_LIMIT_MB if is_premium(user_id) else FREE_FILE_LIMIT_MB

def check_file_size(user_id, size):
    return size <= (max_file_mb(user_id) * 1024 * 1024)

async def send_result(update, data, filename):
    bio = io.BytesIO(data)
    bio.name = filename
    await update.effective_chat.send_document(document=bio, filename=filename)

# ============================================================
# KEYBOARDS (8 ACTIVE CORE TOOLS + FULL UTILITIES)
# ============================================================

def main_keyboard(user_id):
    return ReplyKeyboardMarkup([
        ["📕 PDF Tools", "🖼️ Image Tools"],
        ["📝 Text Tools", "📁 File Tools"],
        ["🔗 URL/QR", "🔐 Security"],
        ["🧮 Calculator", "💻 Developer"],
        ["💎 Premium", "👤 My Account"],
        ["🎁 Daily Bonus", "👥 Refer & Earn"],
        ["🎟️ Redeem Code", "📜 History"],
        ["🆘 Support", "⚙️ Settings"],
    ], resize_keyboard=True)

def pdf_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 PDF → Word", callback_data="tool:PDF → Word"), InlineKeyboardButton("📝 PDF → TXT", callback_data="tool:PDF → TXT")],
        [InlineKeyboardButton("🖼️ PDF → JPG", callback_data="tool:PDF → JPG"), InlineKeyboardButton("🖼️ PDF → PNG", callback_data="tool:PDF → PNG")],
        [InlineKeyboardButton("🗜️ Compress PDF", callback_data="tool:Compress PDF"), InlineKeyboardButton("🔗 Merge PDF", callback_data="merge_start")],
        [InlineKeyboardButton("✂️ Split PDF", callback_data="tool:Split PDF"), InlineKeyboardButton("📑 Extract Pages", callback_data="tool:Extract Pages")],
        [InlineKeyboardButton("🔄 Rotate PDF", callback_data="tool:Rotate PDF"), InlineKeyboardButton("📐 Page Size", callback_data="tool:PDF Page Size")],
        [InlineKeyboardButton("🔢 Page Numbers", callback_data="tool:Add Page Numbers"), InlineKeyboardButton("💧 Watermark", callback_data="tool:Add Watermark")],
        [InlineKeyboardButton("🔐 Protect PDF", callback_data="tool:Protect PDF"), InlineKeyboardButton("🔓 Unlock PDF", callback_data="tool:Unlock PDF")],
        [InlineKeyboardButton("🧹 Clean Meta", callback_data="tool:Remove Metadata"), InlineKeyboardButton("ℹ️ PDF Info", callback_data="tool:PDF Info")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def image_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 JPG → PDF", callback_data="tool:JPG → PDF"), InlineKeyboardButton("📄 PNG → PDF", callback_data="tool:PNG → PDF")],
        [InlineKeyboardButton("📚 Multiple Images → PDF", callback_data="tool:Multiple Images → PDF")],
        [InlineKeyboardButton("🗜️ Compress Image", callback_data="tool:Compress Image"), InlineKeyboardButton("📏 Resize Image", callback_data="tool:Resize Image")],
        [InlineKeyboardButton("📐 Custom Resize", callback_data="tool:Custom Resize"), InlineKeyboardButton("🔄 JPG ↔ PNG", callback_data="tool:JPG ↔ PNG")],
        [InlineKeyboardButton("🌐 Image → WebP", callback_data="tool:Image → WebP")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def text_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Text to PDF", callback_data="tool:Text to PDF"), InlineKeyboardButton("📊 Word & Char Count", callback_data="tool:Word Count")],
        [InlineKeyboardButton("🔠 UPPERCASE", callback_data="tool:Text Upper"), InlineKeyboardButton("🔡 lowercase", callback_data="tool:Text Lower")],
        [InlineKeyboardButton("🔤 Title Case", callback_data="tool:Text Title"), InlineKeyboardButton("🔄 Reverse Text", callback_data="tool:Reverse Text")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def file_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Extract ZIP", callback_data="tool:Extract ZIP"), InlineKeyboardButton("🗜️ Compress to ZIP", callback_data="tool:Compress to ZIP")],
        [InlineKeyboardButton("🔍 File Checksum (SHA256)", callback_data="tool:File Checksum")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def url_qr_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Make QR Code", callback_data="tool:Generate QR"), InlineKeyboardButton("🔗 Shorten URL", callback_data="tool:Shorten URL")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def security_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Generate Strong Password", callback_data="tool:Gen Password")],
        [InlineKeyboardButton("🛡️ Hash Generator (MD5/SHA256)", callback_data="tool:Hash Generator")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def calc_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧮 Math Calculator", callback_data="tool:Math Calc"), InlineKeyboardButton("📊 Percentage Calculator", callback_data="tool:Percent Calc")],
        [InlineKeyboardButton("🎂 Age Calculator", callback_data="tool:Age Calc")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def dev_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Format & Prettify JSON", callback_data="tool:JSON Format")],
        [InlineKeyboardButton("🔐 Base64 Encode", callback_data="tool:B64 Encode"), InlineKeyboardButton("🔓 Base64 Decode", callback_data="tool:B64 Decode")],
        [InlineKeyboardButton("🌐 URL Encode", callback_data="tool:URL Encode"), InlineKeyboardButton("🌐 URL Decode", callback_data="tool:URL Decode")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def settings_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Notifications", callback_data="settings:notifications")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def premium_plan_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💎 Weekly — ৳{WEEKLY_PRICE}", callback_data="premium:weekly")],
        [InlineKeyboardButton(f"👑 Monthly — ৳{MONTHLY_PRICE}", callback_data="premium:monthly")],
        [InlineKeyboardButton("📋 My Premium Status", callback_data="premium:status")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

def premium_payment_keyboard(plan):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 bKash", callback_data=f"payment:bkash:{plan}"), InlineKeyboardButton("📱 Nagad", callback_data=f"payment:nagad:{plan}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="premium:menu")]
    ])

def admin_premium_request_keyboard(request_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ APPROVE", callback_data=f"premium_admin:approve:{request_id}"), InlineKeyboardButton("❌ REJECT", callback_data=f"premium_admin:reject:{request_id}")]
    ])

# ============================================================
# PROGRESS SYSTEM & COSTS
# ============================================================

def progress_bar(percent):
    filled = percent // 10
    return "█" * filled + "░" * (10 - filled)

def progress_text(percent, filename=""):
    return f"""
╔══════════════════════════════╗
       ⚡ RAFIM MULTI-PRO
╚══════════════════════════════╝

⚙️ <b>প্রসেসিং চলছে...</b>
<code>{progress_bar(percent)}</code> <b>{percent}%</b>

📄 <b>ফাইল:</b> {filename[:40]}

━━━━━━━━━━━━━━━━━━━━
⚡ <i>Smart Processing Engine Active</i>
"""

TOOL_COST = {
    "PDF → Word": 2, "PDF → TXT": 1, "PDF → JPG": 2, "PDF → PNG": 2,
    "Compress PDF": 2, "Merge PDF": 3, "Split PDF": 3, "Extract Pages": 2,
    "Rotate PDF": 2, "PDF Page Size": 2, "Add Page Numbers": 2, "Add Watermark": 2,
    "Remove Metadata": 1, "PDF Info": 1, "Protect PDF": 2, "Unlock PDF": 2,
    "JPG → PDF": 1, "PNG → PDF": 1, "Multiple Images → PDF": 2,
    "Compress Image": 1, "Resize Image": 1, "Custom Resize": 1, "JPG ↔ PNG": 1, "Image → WebP": 1,
    "Text to PDF": 1, "Word Count": 1, "Text Upper": 1, "Text Lower": 1, "Text Title": 1, "Reverse Text": 1,
    "Extract ZIP": 2, "Compress to ZIP": 2, "File Checksum": 1,
    "Generate QR": 1, "Shorten URL": 1,
    "Gen Password": 1, "Hash Generator": 1,
    "Math Calc": 1, "Percent Calc": 1, "Age Calc": 1,
    "JSON Format": 1, "B64 Encode": 1, "B64 Decode": 1, "URL Encode": 1, "URL Decode": 1
}

# ============================================================
# PROCESSING WORKERS
# ============================================================

def pdf_to_word(data):
    pdf = fitz.open(stream=data, filetype="pdf")
    doc = Document()
    for page in pdf:
        text = page.get_text("text")
        if text.strip():
            doc.add_paragraph(text)
    out = io.BytesIO()
    doc.save(out)
    out.seek(0)
    return out.getvalue(), "document.docx"

def pdf_to_txt(data):
    pdf = fitz.open(stream=data, filetype="pdf")
    text = [f"\n--- PAGE {i} ---\n" + page.get_text("text") for i, page in enumerate(pdf, 1)]
    return "\n".join(text).encode("utf-8"), "document.txt"

def pdf_to_images_zip(data, fmt="jpg"):
    pdf = fitz.open(stream=data, filetype="pdf")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for i, page in enumerate(pdf, 1):
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            b = io.BytesIO()
            if fmt.lower() == "png":
                img.save(b, "PNG")
                name = f"page_{i}.png"
            else:
                img.save(b, "JPEG", quality=90)
                name = f"page_{i}.jpg"
            z.writestr(name, b.getvalue())
    zip_buffer.seek(0)
    return zip_buffer.getvalue(), "pdf_pages.zip"

def compress_pdf(data):
    pdf = fitz.open(stream=data, filetype="pdf")
    out = io.BytesIO()
    pdf.save(out, garbage=4, deflate=True, clean=True)
    return out.getvalue(), "compressed.pdf"

def merge_pdfs(datas):
    out = fitz.open()
    for data in datas:
        src = fitz.open(stream=data, filetype="pdf")
        out.insert_pdf(src)
        src.close()
    b = io.BytesIO()
    out.save(b)
    out.close()
    return b.getvalue(), "merged.pdf"

def split_pdf(data):
    pdf = fitz.open(stream=data, filetype="pdf")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(len(pdf)):
            single = fitz.open()
            single.insert_pdf(pdf, from_page=i, to_page=i)
            b = io.BytesIO()
            single.save(b)
            single.close()
            z.writestr(f"page_{i + 1}.pdf", b.getvalue())
    zip_buffer.seek(0)
    return zip_buffer.getvalue(), "split_pages.zip"

def extract_pages(data, start=1, end=None):
    pdf = fitz.open(stream=data, filetype="pdf")
    if end is None:
        end = start
    start = max(1, start)
    end = min(len(pdf), end)
    out = fitz.open()
    out.insert_pdf(pdf, from_page=start - 1, to_page=end - 1)
    b = io.BytesIO()
    out.save(b)
    out.close()
    return b.getvalue(), f"pages_{start}-{end}.pdf"

def rotate_pdf(data, angle=90):
    pdf = fitz.open(stream=data, filetype="pdf")
    for page in pdf:
        page.set_rotation((page.rotation + angle) % 360)
    b = io.BytesIO()
    pdf.save(b)
    pdf.close()
    return b.getvalue(), "rotated.pdf"

def resize_pdf_page(data, size="A4"):
    sizes = {"A4": (595, 842), "A5": (420, 595), "LETTER": (612, 792)}
    w, h = sizes.get(size.upper(), sizes["A4"])
    src = fitz.open(stream=data, filetype="pdf")
    out = fitz.open()
    for page in src:
        new = out.new_page(width=w, height=h)
        new.show_pdf_page(fitz.Rect(0, 0, w, h), src, page.number)
    b = io.BytesIO()
    out.save(b)
    out.close()
    return b.getvalue(), "resized_pages.pdf"

def add_page_numbers(data):
    pdf = fitz.open(stream=data, filetype="pdf")
    for i, page in enumerate(pdf, 1):
        page.insert_text(fitz.Point(page.rect.width / 2 - 10, page.rect.height - 25), str(i), fontsize=10)
    b = io.BytesIO()
    pdf.save(b)
    pdf.close()
    return b.getvalue(), "numbered.pdf"

def add_watermark(data, text="RAFIM MULTI-PRO"):
    pdf = fitz.open(stream=data, filetype="pdf")
    for page in pdf:
        page.insert_text(
            fitz.Point(page.rect.width / 2 - 80, page.rect.height / 2),
            text, fontsize=24, rotate=45, color=(0.5, 0.5, 0.5), overlay=True
        )
    b = io.BytesIO()
    pdf.save(b)
    pdf.close()
    return b.getvalue(), "watermarked.pdf"

def remove_metadata(data):
    pdf = fitz.open(stream=data, filetype="pdf")
    pdf.set_metadata({})
    b = io.BytesIO()
    pdf.save(b)
    pdf.close()
    return b.getvalue(), "clean_metadata.pdf"

def pdf_info(data):
    pdf = fitz.open(stream=data, filetype="pdf")
    meta = pdf.metadata or {}
    return f"""📊 <b>PDF INFORMATION</b>\n\n📄 Pages: {len(pdf)}\n📦 Size: {len(data) / 1024 / 1024:.2f} MB\n\nTitle: {meta.get("title") or "N/A"}\nAuthor: {meta.get("author") or "N/A"}\nSubject: {meta.get("subject") or "N/A"}"""

def protect_pdf(data, password="123456"):
    pdf = fitz.open(stream=data, filetype="pdf")
    b = io.BytesIO()
    pdf.save(b, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=password, user_pw=password)
    pdf.close()
    return b.getvalue(), "protected.pdf"

def unlock_pdf(data, password):
    pdf = fitz.open(stream=data, filetype="pdf")
    if pdf.needs_pass and not pdf.authenticate(password):
        raise ValueError("ভুল PDF পাসওয়ার্ড দেওয়া হয়েছে।")
    out = fitz.open()
    for page in pdf:
        out.insert_pdf(pdf, from_page=page.number, to_page=page.number)
    b = io.BytesIO()
    out.save(b)
    out.close()
    pdf.close()
    return b.getvalue(), "unlocked.pdf"

def image_to_pdf(data):
    img = Image.open(io.BytesIO(data)).convert("RGB")
    b = io.BytesIO()
    img.save(b, "PDF", resolution=150)
    return b.getvalue(), "image.pdf"

def multiple_images_to_pdf(datas):
    images = [Image.open(io.BytesIO(d)).convert("RGB") for d in datas]
    if not images:
        raise ValueError("কোনো ইমেজ পাওয়া যায়নি।")
    b = io.BytesIO()
    images[0].save(b, "PDF", save_all=True, append_images=images[1:])
    return b.getvalue(), "images.pdf"

def process_image(data, tool):
    img = Image.open(io.BytesIO(data))
    out = io.BytesIO()
    if tool == "Compress Image":
        img.thumbnail((1920, 1920))
        img.convert("RGB").save(out, "JPEG", quality=70, optimize=True)
        return out.getvalue(), "compressed.jpg"
    elif tool == "Resize Image":
        img.thumbnail((1280, 1280))
        img.convert("RGB").save(out, "JPEG", quality=90)
        return out.getvalue(), "resized.jpg"
    elif tool == "Custom Resize":
        img.thumbnail((1080, 1080))
        img.convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue(), "custom_resized.jpg"
    elif tool == "Image → WebP":
        img.save(out, "WEBP", quality=85)
        return out.getvalue(), "image.webp"
    elif tool == "JPG ↔ PNG":
        if img.format == "PNG":
            img.convert("RGB").save(out, "JPEG", quality=92)
            return out.getvalue(), "converted.jpg"
        img.save(out, "PNG")
        return out.getvalue(), "converted.png"
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue(), "image.jpg"

def text_to_pdf_bytes(text):
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(50, 50, 550, 800)
    page.insert_textbox(rect, text, fontsize=12, align=0)
    b = io.BytesIO()
    doc.save(b)
    doc.close()
    return b.getvalue()

def make_qr_bytes(content):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    b = io.BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()

def shorten_url_api(url):
    try:
        res = requests.get(f"https://tinyurl.com/api-create.php?url={urllib.parse.quote(url)}", timeout=10)
        if res.status_code == 200:
            return res.text.strip()
    except Exception:
        pass
    return "Error generating short URL."

# ============================================================
# START & BASIC USER HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = None
    if context.args:
        arg = context.args[0].strip()
        if arg.startswith("R"):
            try:
                possible_id = int(arg[1:])
                if possible_id != user.id and get_user(possible_id):
                    referred_by = possible_id
            except Exception:
                pass

    u, created = ensure_user(user, referred_by=referred_by)
    update_streak(user.id)

    if created and referred_by:
        add_credits(referred_by, REFERRAL_REWARD, "Successful referral")
        add_xp(referred_by, REFERRAL_XP)
        con = db()
        con.execute("UPDATE users SET referral_count=referral_count+1, referral_earned=referral_earned+? WHERE user_id=?", (REFERRAL_REWARD, referred_by))
        con.commit()
        con.close()

    u = get_user(user.id)
    prem = "✅ ACTIVE" if is_premium(user.id) else "❌ FREE"

    msg = f"""╔══════════════════════════════╗
   ⚡ <b>RAFIM MULTI-PRO ENGINE</b> ⚡
   🔥 <i>আল্টিমেট অল-ইন-ওয়ান পাওয়ার</i> 🔥
╚══════════════════════════════╝

👋 <b>স্বাগতম, {user.first_name}!</b>

🚀 <i>৮টি পাওয়ারফুল ইঞ্জিন সম্পূর্ণ রেডি! নিচের যেকোনো অপশন বেছে নিন।</i>

┌──────────────────────────────┐
│ 💳 <b>ক্রেডিট ব্যালেন্স</b> : <code>{u['credits']}</code>
│ 💎 <b>মেম্বারশিপ</b>      : <b>{prem}</b>
│ ⭐ <b>লেভেল ও র‍্যাঙ্ক</b>   : <code>Lv.{u['level']}</code>
│ 🔥 <b>দৈনিক স্ট্রিক</b>    : <code>{u['streak']} দিন</code>
│ 👥 <b>রেফারেল টিম</b>    : <code>{u['referral_count']} জন</code>
└──────────────────────────────┘

⚡ <b>সার্ভার স্ট্যাটাস:</b> <code>100% সচল ও দ্রুত</code>
🔥 <b>নিচের বাটন চেপে কাজ শুরু করুন!</b>"""

    await update.message.reply_text(
        msg,
        reply_markup=main_keyboard(user.id),
        parse_mode=ParseMode.HTML
    )

async def menu_cmd(update, context):
    await update.message.reply_text("🏠 <b>MAIN MENU</b>\n\nনিচের অপশন থেকে সিলেক্ট করুন:", reply_markup=main_keyboard(update.effective_user.id), parse_mode=ParseMode.HTML)

async def account(update, context):
    uid = update.effective_user.id
    u = get_user(uid)
    await update.message.reply_text(
        f"""👤 <b>YOUR ACCOUNT</b>\n\n🆔 ID: <code>{uid}</code>\n👤 Name: {u["first_name"]}\n💳 Credits: <b>{u["credits"]}</b>\n💎 Premium: {"✅ ACTIVE" if is_premium(uid) else "❌ FREE"}\n📅 Premium Until: <code>{premium_expiry_text(uid)}</code>\n⭐ XP: {u["xp"]} | Level: {u["level"]}\n🔥 Streak: {u["streak"]} Days\n👥 Referrals: {u["referral_count"]}""",
        parse_mode=ParseMode.HTML
    )

async def bonus(update, context):
    uid = update.effective_user.id
    u = get_user(uid)
    today = date.today().isoformat()
    if u["last_bonus"] == today:
        await update.message.reply_text("⏰ <b>আজকের ডেইলি বোনাস গ্রহণ করা হয়েছে!</b>\nআগামীকাল আবার আসুন।", parse_mode=ParseMode.HTML)
        return
    add_credits(uid, DAILY_BONUS, "Daily bonus")
    add_xp(uid, 10)
    con = db()
    con.execute("UPDATE users SET last_bonus=? WHERE user_id=?", (today, uid))
    con.commit()
    con.close()
    await update.message.reply_text(f"🎁 <b>+{DAILY_BONUS} Credits</b> এবং <b>+10 XP</b> যোগ হয়েছে!", parse_mode=ParseMode.HTML)

async def refer(update, context):
    uid = update.effective_user.id
    u = get_user(uid)
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={u['referral_code']}"
    await update.message.reply_text(
        f"""👥 <b>REFERRAL ENGINE</b>\n\n🔗 <b>আপনার ইনভাইট লিংক:</b>\n<code>{link}</code>\n\nপ্রতিটি রেফারে পাবেন +{REFERRAL_REWARD} ক্রেডিট এবং +{REFERRAL_XP} XP!\n👥 মোট রেফার: {u["referral_count"]} জন""",
        parse_mode=ParseMode.HTML
    )

async def history_cmd(update, context):
    uid = update.effective_user.id
    con = db()
    rows = con.execute("SELECT tool,status,filename,credits,created_at FROM history WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("📜 হিস্টোরি খালি রয়েছে।")
        return
    text = "📜 <b>RECENT HISTORY</b>\n\n"
    for r in rows:
        icon = "✅" if r["status"] == "success" else "❌"
        text += f"{icon} <b>{r['tool']}</b>\n📄 {r['filename'][:30]}\n💳 {r['credits']} Credits | 🕒 {r['created_at'][:16]}\n━━━━━━━━━━━━━━\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def support(update, context):
    await update.message.reply_text(f"🆘 <b>সাপোর্ট সেন্টার</b>\n\nসরাসরি মেসেজ পাঠাতে পারেন: @{SUPPORT_USERNAME}\nঅথবা এখানে আপনার সমস্যা লিখে পাঠান, সাপোর্ট টিকেট ওপেন হবে।", parse_mode=ParseMode.HTML)
    context.user_data["support_mode"] = True

async def settings(update, context):
    await update.message.reply_text("⚙️ <b>সেটিংস মেনু</b>", reply_markup=settings_keyboard(update.effective_user.id), parse_mode=ParseMode.HTML)

async def premium(update, context):
    await update.message.reply_text(f"💎 <b>PREMIUM POWER</b>\n\nসাপ্তাহিক: ৳{WEEKLY_PRICE}\nমাসিক: ৳{MONTHLY_PRICE}\n\nপ্ল্যান নির্বাচন করুন:", reply_markup=premium_plan_keyboard(), parse_mode=ParseMode.HTML)

# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if is_banned(uid):
        return

    data = query.data

    if data == "home":
        await query.message.edit_text("🏠 <b>MAIN MENU</b>\n\nনিচের মেনু থেকে ক্যাটাগরি বেছে নিন।", parse_mode=ParseMode.HTML)
        return

    if data == "settings:notifications":
        u = get_user(uid)
        new_val = 0 if u["notifications"] else 1
        con = db()
        con.execute("UPDATE users SET notifications=? WHERE user_id=?", (new_val, uid))
        con.commit()
        con.close()
        await query.edit_message_text(f"🔔 Notifications: {'✅ ON' if new_val else '❌ OFF'}", reply_markup=settings_keyboard(uid))
        return

    if data == "merge_start":
        context.user_data["merge_mode"] = True
        context.user_data["merge_files"] = []
        await query.edit_message_text("🔗 <b>MERGE PDF MODE</b>\n\nএকটি একটি করে PDF ফাইল পাঠান।\nসব পাঠানো শেষ হলে টাইপ করুন: <code>/done</code>", parse_mode=ParseMode.HTML)
        return

    if data.startswith("tool:"):
        tool = data.split(":", 1)[1]
        context.user_data["selected_tool"] = tool
        cost = TOOL_COST.get(tool, 1)

        if tool in ["Math Calc", "Percent Calc", "Age Calc", "Generate QR", "Shorten URL", "Hash Generator", "JSON Format", "B64 Encode", "B64 Decode", "URL Encode", "URL Decode", "Text Upper", "Text Lower", "Text Title", "Reverse Text", "Text to PDF"]:
            context.user_data["waiting_text_input"] = tool
            await query.edit_message_text(f"⚡ <b>{tool}</b>\n💳 খরচ: {cost} ক্রেডিট\n\n✍️ <b>এখন আপনার টেক্সট বা ইনপুট লিখে পাঠান:</b>", parse_mode=ParseMode.HTML)
            return

        if tool == "Gen Password":
            import secrets
            import string
            chars = string.ascii_letters + string.digits + "!@#$%^&*()_+"
            pwd = "".join(secrets.choice(chars) for _ in range(16))
            if not is_premium(uid):
                remove_credits(uid, cost, "Gen Password")
            await query.edit_message_text(f"🔐 <b>শক্তিশালী পাসওয়ার্ড তৈরি হয়েছে:</b>\n\n<code>{pwd}</code>\n\n<i>কপি করতে ওপরে ট্যাপ করুন।</i>", parse_mode=ParseMode.HTML)
            return

        if tool == "Unlock PDF" or tool == "Protect PDF":
            context.user_data["waiting_password"] = True
        if tool == "Add Watermark":
            context.user_data["waiting_watermark"] = True
        if tool == "Custom Resize":
            context.user_data["waiting_resize"] = True
        if tool == "Extract Pages":
            context.user_data["waiting_pages"] = True

        await query.edit_message_text(f"⚡ <b>{tool}</b>\n💳 খরচ: {cost} ক্রেডিট\n\n📤 <b>এখন আপনার ফাইলটি পাঠান!</b>", parse_mode=ParseMode.HTML)
        return

    if data == "premium:menu":
        await query.edit_message_text(f"💎 <b>প্রিমিয়াম প্যাকেজ</b>\n\n💎 Weekly: ৳{WEEKLY_PRICE}\n👑 Monthly: ৳{MONTHLY_PRICE}\n\nআপনার প্ল্যান নির্বাচন করুন:", reply_markup=premium_plan_keyboard(), parse_mode=ParseMode.HTML)
        return

    if data in ["premium:weekly", "premium:monthly"]:
        plan = data.split(":")[1]
        context.user_data["premium_plan"] = plan
        await query.edit_message_text(f"💎 <b>{plan.title()} Premium</b>\nপেমেন্ট মেথড বেছে নিন:", reply_markup=premium_payment_keyboard(plan), parse_mode=ParseMode.HTML)
        return

    if data.startswith("payment:"):
        parts = data.split(":")
        method, plan = parts[1], parts[2]
        number = BKASH_NUMBER if method == "bkash" else NAGAD_NUMBER
        context.user_data["premium_plan"] = plan
        context.user_data["premium_payment_method"] = method
        context.user_data["premium_txn"] = True
        await query.edit_message_text(
            f"📱 <b>{method.upper()}-এ পেমেন্ট করুন</b>\n\nSend Money করুন এই নাম্বারে:\n<code>{number}</code>\n\nটাকা পাঠানোর পর প্রাপ্ত <b>Transaction ID</b> লিখে মেসেজ দিন।",
            parse_mode=ParseMode.HTML
        )
        return

    if data.startswith("premium_admin:"):
        if uid != ADMIN_ID:
            return
        _, action, rid = data.split(":")
        con = db()
        row = con.execute("SELECT * FROM premium_requests WHERE id=?", (rid,)).fetchone()
        if not row or row["status"] != "pending":
            con.close()
            await query.answer("ইতোমধ্যে সম্পন্ন হয়েছে।")
            return

        if action == "approve":
            days = 30 if row["plan"] == "monthly" else 7
            expiry = datetime.now() + timedelta(days=days)
            con.execute("UPDATE premium_requests SET status='approved', reviewed_at=? WHERE id=?", (datetime.now().isoformat(), rid))
            con.execute("UPDATE users SET premium=1, premium_until=? WHERE user_id=?", (expiry.isoformat(), row["user_id"]))
            con.commit()
            con.close()
            await query.edit_message_text(f"✅ রিকোয়েস্ট #{rid} অ্যাপ্রুভ হয়েছে!")
            try:
                await context.bot.send_message(row["user_id"], "🎉 আপনার প্রিমিয়াম অ্যাকাউন্ট অ্যাক্টিভ হয়েছে!")
            except Exception:
                pass
        else:
            con.execute("UPDATE premium_requests SET status='rejected', reviewed_at=? WHERE id=?", (datetime.now().isoformat(), rid))
            con.commit()
            con.close()
            await query.edit_message_text(f"❌ রিকোয়েস্ট #{rid} বাতিল করা হয়েছে!")
            try:
                await context.bot.send_message(row["user_id"], "❌ আপনার প্রিমিয়াম রিকোয়েস্টটি বাতিল করা হয়েছে।")
            except Exception:
                pass
        return

# ============================================================
# TEXT INPUT & WORKFLOW
# ============================================================

async def text_handler(update, context):
    uid = update.effective_user.id
    text = update.message.text.strip()
    if is_banned(uid):
        return

    if context.user_data.get("waiting_password"):
        context.user_data["custom_password"] = text
        context.user_data["waiting_password"] = False
        await update.message.reply_text("🔐 পাসওয়ার্ড সংরক্ষিত। এখন PDF পাঠান।")
        return

    if context.user_data.get("waiting_watermark"):
        context.user_data["watermark"] = text
        context.user_data["waiting_watermark"] = False
        await update.message.reply_text("💧 ওয়াটারমার্ক টেক্সট সংরক্ষিত। এখন PDF পাঠান।")
        return

    if context.user_data.get("waiting_pages"):
        context.user_data["waiting_pages"] = False
        m = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$", text)
        if m:
            start_p = int(m.group(1))
            end_p = int(m.group(2) or m.group(1))
            context.user_data["page_range"] = (start_p, end_p)
            await update.message.reply_text(f"📑 পেজ {start_p}-{end_p} সংরক্ষিত। এখন PDF পাঠান।")
            return
        else:
            await update.message.reply_text("❌ ফরম্যাট সঠিক নয়। উদাহরণ: 1-5")
            return

    waiting_tool = context.user_data.pop("waiting_text_input", None)
    if waiting_tool:
        cost = TOOL_COST.get(waiting_tool, 1)
        if not is_premium(uid) and get_user(uid)["credits"] < cost:
            await update.message.reply_text("💳 পর্যাপ্ত ক্রেডিট নেই।")
            return

        if waiting_tool == "Generate QR":
            qr_bytes = make_qr_bytes(text)
            if not is_premium(uid):
                remove_credits(uid, cost, waiting_tool)
            await update.message.reply_photo(photo=io.BytesIO(qr_bytes), caption="📱 <b>আপনার QR কোড প্রস্তুত!</b>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Shorten URL":
            short = shorten_url_api(text)
            if not is_premium(uid):
                remove_credits(uid, cost, waiting_tool)
            await update.message.reply_text(f"🔗 <b>সংক্ষিপ্ত লিঙ্ক:</b>\n<code>{short}</code>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Math Calc":
            try:
                allowed = set("0123456789+-*/().% ")
                if not all(c in allowed for c in text):
                    raise ValueError("অবৈধ অক্ষর")
                res = eval(text, {"__builtins__": None}, {})
                ans = f"🧮 <b>হিসাব:</b> <code>{text}</code>\n📊 <b>ফলাফল:</b> <code>{res}</code>"
            except Exception as e:
                ans = f"❌ সমস্যা হয়েছে: {str(e)}"
            if not is_premium(uid):
                remove_credits(uid, cost, waiting_tool)
            await update.message.reply_text(ans, parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Percent Calc":
            try:
                parts = re.findall(r"[-+]?(?:\d*\.\d+|\d+)", text)
                if len(parts) >= 2:
                    p, total = float(parts[0]), float(parts[1])
                    val = (p / 100) * total
                    ans = f"📊 <b>{total}-এর {p}%</b> = <code>{val:.2f}</code>"
                else:
                    ans = "❌ ফরম্যাট উদাহরণ: <code>20 500</code>"
            except Exception:
                ans = "❌ সঠিক তথ্য দিন।"
            await update.message.reply_text(ans, parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Age Calc":
            try:
                bday = datetime.strptime(text, "%Y-%m-%d").date()
                today = date.today()
                years = today.year - bday.year - ((today.month, today.day) < (bday.month, bday.day))
                ans = f"🎂 <b>বয়স:</b> {years} বছর।"
            except Exception:
                ans = "❌ তারিখের সঠিক ফরম্যাট লিখুন: <code>YYYY-MM-DD</code>"
            await update.message.reply_text(ans, parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Hash Generator":
            md5 = hashlib.md5(text.encode()).hexdigest()
            sha256 = hashlib.sha256(text.encode()).hexdigest()
            res = f"🛡️ <b>MD5:</b> <code>{md5}</code>\n\n🛡️ <b>SHA256:</b> <code>{sha256}</code>"
            await update.message.reply_text(res, parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "JSON Format":
            try:
                parsed = json.loads(text)
                formatted = json.dumps(parsed, indent=2)
                res = f"<pre><code class=\"language-json\">{formatted[:4000]}</code></pre>"
            except Exception as e:
                res = f"❌ ইনভ্যালিড JSON: {str(e)}"
            await update.message.reply_text(res, parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "B64 Encode":
            import base64
            encoded = base64.b64encode(text.encode()).decode()
            await update.message.reply_text(f"🔐 <b>Base64 Encoded:</b>\n<code>{encoded}</code>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "B64 Decode":
            import base64
            try:
                decoded = base64.b64decode(text.encode()).decode(errors="ignore")
                await update.message.reply_text(f"🔓 <b>Base64 Decoded:</b>\n<code>{decoded}</code>", parse_mode=ParseMode.HTML)
            except Exception as e:
                await update.message.reply_text(f"❌ ডিকোড ব্যর্থ: {str(e)}")
            return

        if waiting_tool == "URL Encode":
            enc = urllib.parse.quote(text)
            await update.message.reply_text(f"🌐 <b>URL Encoded:</b>\n<code>{enc}</code>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "URL Decode":
            dec = urllib.parse.unquote(text)
            await update.message.reply_text(f"🌐 <b>URL Decoded:</b>\n<code>{dec}</code>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Word Count":
            words = len(text.split())
            chars = len(text)
            lines = len(text.splitlines())
            await update.message.reply_text(f"📊 <b>টেক্সট বিবরণ:</b>\n\n📝 মোট শব্দ: {words}\n🔤 মোট বর্ণ: {chars}\n📑 মোট লাইন: {lines}", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Text Upper":
            await update.message.reply_text(f"🔠 <code>{text.upper()}</code>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Text Lower":
            await update.message.reply_text(f"🔡 <code>{text.lower()}</code>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Text Title":
            await update.message.reply_text(f"🔤 <code>{text.title()}</code>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Reverse Text":
            await update.message.reply_text(f"🔄 <code>{text[::-1]}</code>", parse_mode=ParseMode.HTML)
            return

        if waiting_tool == "Text to PDF":
            pdf_bytes = text_to_pdf_bytes(text)
            await send_result(update, pdf_bytes, "document.pdf")
            return

    if context.user_data.get("premium_txn"):
        context.user_data["premium_txn"] = False
        plan = context.user_data.get("premium_plan", "weekly")
        method = context.user_data.get("premium_payment_method", "bkash")
        con = db()
        cur = con.execute("INSERT INTO premium_requests(user_id, plan, transaction_id, status, created_at) VALUES(?,?,?,?,?)",
                          (uid, plan, text, "pending", datetime.now().isoformat()))
        req_id = cur.lastrowid
        con.commit()
        con.close()
        await update.message.reply_text(f"💎 রিকোয়েস্ট #{req_id} জমা হয়েছে। অ্যাডমিন শীঘ্রই ভেরিফাই করবে।")
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💎 <b>নতুন প্রিমিয়াম পেমেন্ট</b>\n\nID: #{req_id}\nUser: <code>{uid}</code>\nPlan: {plan}\nMethod: {method}\nTXN: <code>{text}</code>",
                reply_markup=admin_premium_request_keyboard(req_id),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        return

    if context.user_data.get("waiting_redeem"):
        context.user_data["waiting_redeem"] = False
        code = text.upper()
        con = db()
        row = con.execute("SELECT * FROM redeem_codes WHERE code=?", (code,)).fetchone()
        if not row or not row["enabled"] or row["used_count"] >= row["max_uses"]:
            con.close()
            await update.message.reply_text("❌ কোডটি সঠিক নয় অথবা ব্যবহারের মেয়াদ শেষ।")
            return
        used = con.execute("SELECT * FROM redemptions WHERE user_id=? AND code=?", (uid, code)).fetchone()
        if used:
            con.close()
            await update.message.reply_text("⚠️ আপনি ইতিপূর্বে এই কোডটি ব্যবহার করেছেন।")
            return
        con.execute("UPDATE redeem_codes SET used_count=used_count+1 WHERE code=?", (code,))
        con.execute("INSERT INTO redemptions(user_id,code,credits,created_at) VALUES(?,?,?,?)", (uid, code, row["credits"], datetime.now().isoformat()))
        con.commit()
        con.close()
        add_credits(uid, row["credits"], f"Redeem {code}")
        await update.message.reply_text(f"🎟️ রিডিম সফল! +{row['credits']} ক্রেডিট যোগ করা হয়েছে।")
        return

    if context.user_data.get("support_mode"):
        context.user_data["support_mode"] = False
        con = db()
        cur = con.execute("INSERT INTO support_tickets(user_id,message,status,created_at) VALUES(?,?,?,?)", (uid, text, "open", datetime.now().isoformat()))
        ticket_id = cur.lastrowid
        con.commit()
        con.close()
        await update.message.reply_text(f"🆘 সাপোর্ট টিকেট #{ticket_id} সফলভাবে খোলা হয়েছে।")
        try:
            await context.bot.send_message(ADMIN_ID, f"🆘 Ticket #{ticket_id} from {uid}:\n{text}")
        except Exception:
            pass
        return

    # ৮টি ফিচার বাটন রাউটিং
    if text == "📕 PDF Tools":
        await update.message.reply_text("📕 <b>PDF TITAN ENGINE</b>\n\nনিচের অপশন থেকে টুল বেছে নিন:", reply_markup=pdf_keyboard(uid), parse_mode=ParseMode.HTML)
        return
    if text == "🖼️ Image Tools":
        await update.message.reply_text("🖼️ <b>ULTRA IMAGE STUDIO</b>\n\nনিচের অপশন থেকে টুল বেছে নিন:", reply_markup=image_keyboard(uid), parse_mode=ParseMode.HTML)
        return
    if text == "📝 Text Tools":
        await update.message.reply_text("📝 <b>SMART TEXT MATRIX</b>\n\nনিচের অপশন থেকে টুল বেছে নিন:", reply_markup=text_keyboard(uid), parse_mode=ParseMode.HTML)
        return
    if text == "📁 File Tools":
        await update.message.reply_text("📁 <b>FILE VAULT & ARCHIVE</b>\n\nনিচের অপশন থেকে টুল বেছে নিন:", reply_markup=file_keyboard(uid), parse_mode=ParseMode.HTML)
        return
    if text == "🔗 URL/QR":
        await update.message.reply_text("🔗 <b>CYBER URL & QR PORTAL</b>\n\nনিচের অপশন থেকে টুল বেছে নিন:", reply_markup=url_qr_keyboard(uid), parse_mode=ParseMode.HTML)
        return
    if text == "🔐 Security":
        await update.message.reply_text("🔐 <b>FORTRESS SECURITY LAB</b>\n\nনিচের অপশন থেকে টুল বেছে নিন:", reply_markup=security_keyboard(uid), parse_mode=ParseMode.HTML)
        return
    if text == "🧮 Calculator":
        await update.message.reply_text("🧮 <b>QUANTUM CALCULATOR</b>\n\nনিচের অপশন থেকে টুল বেছে নিন:", reply_markup=calc_keyboard(uid), parse_mode=ParseMode.HTML)
        return
    if text == "💻 Developer":
        await update.message.reply_text("💻 <b>DEV TERMINAL CORE</b>\n\nনিচের অপশন থেকে টুল বেছে নিন:", reply_markup=dev_keyboard(uid), parse_mode=ParseMode.HTML)
        return

    if text == "💎 Premium":
        await premium(update, context)
        return
    if text == "👤 My Account":
        await account(update, context)
        return
    if text == "🎁 Daily Bonus":
        await bonus(update, context)
        return
    if text == "👥 Refer & Earn":
        await refer(update, context)
        return
    if text == "🎟️ Redeem Code":
        context.user_data["waiting_redeem"] = True
        await update.message.reply_text("🎟️ রিডিম কোডটি লিখে পাঠান:")
        return
    if text == "📜 History":
        await history_cmd(update, context)
        return
    if text == "🆘 Support":
        await support(update, context)
        return
    if text == "⚙️ Settings":
        await settings(update, context)
        return

    await update.message.reply_text("🤖 নিচের কিবোর্ড মেনু থেকে অপশন নির্বাচন করুন।", reply_markup=main_keyboard(uid))

# ============================================================
# DOCUMENT & PHOTO HANDLERS
# ============================================================

async def document_handler(update, context):
    uid = update.effective_user.id
    if is_banned(uid):
        return
    doc = update.message.document
    if not doc:
        return
    filename = doc.file_name or "file"

    if context.user_data.get("merge_mode"):
        file = await doc.get_file()
        data = await file.download_as_bytearray()
        context.user_data.setdefault("merge_files", []).append(bytes(data))
        await update.message.reply_text(f"📎 PDF #{len(context.user_data['merge_files'])} যুক্ত হয়েছে। আরও পাঠান অথবা /done লিখুন।")
        return

    tool = context.user_data.get("selected_tool")
    if not tool:
        await update.message.reply_text("❗ প্রথমে মেনু থেকে টুল সিলেক্ট করুন।")
        return

    cost = TOOL_COST.get(tool, 1)
    if not is_premium(uid) and get_user(uid)["credits"] < cost:
        await update.message.reply_text("💳 পর্যাপ্ত ক্রেডিট নেই।")
        return

    status = await update.message.reply_text(progress_text(20, filename), parse_mode=ParseMode.HTML)
    try:
        file = await doc.get_file()
        raw = bytes(await file.download_as_bytearray())
        await status.edit_text(progress_text(60, filename), parse_mode=ParseMode.HTML)

        if tool == "PDF → Word":
            result, out_name = pdf_to_word(raw)
        elif tool == "PDF → TXT":
            result, out_name = pdf_to_txt(raw)
        elif tool == "PDF → JPG":
            result, out_name = pdf_to_images_zip(raw, "jpg")
        elif tool == "PDF → PNG":
            result, out_name = pdf_to_images_zip(raw, "png")
        elif tool == "Compress PDF":
            result, out_name = compress_pdf(raw)
        elif tool == "Split PDF":
            result, out_name = split_pdf(raw)
        elif tool == "Extract Pages":
            start_p, end_p = context.user_data.get("page_range", (1, 1))
            result, out_name = extract_pages(raw, start_p, end_p)
        elif tool == "Rotate PDF":
            result, out_name = rotate_pdf(raw)
        elif tool == "PDF Page Size":
            result, out_name = resize_pdf_page(raw, "A4")
        elif tool == "Add Page Numbers":
            result, out_name = add_page_numbers(raw)
        elif tool == "Add Watermark":
            wm = context.user_data.get("watermark", "RAFIM MULTI-PRO")
            result, out_name = add_watermark(raw, wm)
        elif tool == "Remove Metadata":
            result, out_name = remove_metadata(raw)
        elif tool == "PDF Info":
            info = pdf_info(raw)
            await status.edit_text(progress_text(100, filename), parse_mode=ParseMode.HTML)
            await update.message.reply_text(info, parse_mode=ParseMode.HTML)
            return
        elif tool == "Protect PDF":
            pw = context.user_data.get("custom_password", "123456")
            result, out_name = protect_pdf(raw, pw)
        elif tool == "Unlock PDF":
            pw = context.user_data.get("custom_password", "")
            result, out_name = unlock_pdf(raw, pw)
        elif tool in ["JPG → PDF", "PNG → PDF"]:
            result, out_name = image_to_pdf(raw)
        elif tool == "Extract ZIP":
            zip_in = io.BytesIO(raw)
            with zipfile.ZipFile(zip_in, "r") as z:
                first = z.namelist()[0]
                result = z.read(first)
                out_name = first
        elif tool == "Compress to ZIP":
            out_zip = io.BytesIO()
            with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(filename, raw)
            result = out_zip.getvalue()
            out_name = f"{filename}.zip"
        elif tool == "File Checksum":
            h = hashlib.sha256(raw).hexdigest()
            await status.edit_text(f"🔍 <b>SHA256 Checksum:</b>\n\n<code>{h}</code>", parse_mode=ParseMode.HTML)
            return
        else:
            result, out_name = process_image(raw, tool)

        if not is_premium(uid):
            remove_credits(uid, cost, f"Used {tool}")
        add_xp(uid, XP_SUCCESS)
        log_history(uid, tool, "success", filename, cost)

        await status.edit_text(progress_text(100, filename), parse_mode=ParseMode.HTML)
        await send_result(update, result, out_name)
    except Exception as e:
        await status.edit_text(f"🚨 প্রসেস ব্যর্থ: {str(e)[:250]}")
    finally:
        context.user_data.pop("selected_tool", None)

async def photo_handler(update, context):
    uid = update.effective_user.id
    if is_banned(uid):
        return
    photo = update.message.photo[-1]
    tool = context.user_data.get("selected_tool")
    if not tool:
        await update.message.reply_text("🖼️ প্রথমে Image Tool সিলেক্ট করুন।")
        return

    cost = TOOL_COST.get(tool, 1)
    if not is_premium(uid) and get_user(uid)["credits"] < cost:
        await update.message.reply_text("💳 পর্যাপ্ত ক্রেডিট নেই।")
        return

    status = await update.message.reply_text(progress_text(30, "image.jpg"), parse_mode=ParseMode.HTML)
    try:
        file = await photo.get_file()
        raw = bytes(await file.download_as_bytearray())

        if tool in ["JPG → PDF", "PNG → PDF"]:
            result, out_name = image_to_pdf(raw)
        elif tool == "Multiple Images → PDF":
            context.user_data.setdefault("image_batch", []).append(raw)
            await status.edit_text(f"📚 ইমেজ যুক্ত হয়েছে! মোট: {len(context.user_data['image_batch'])}\nআরও পাঠান অথবা /doneimages দিন।")
            return
        else:
            result, out_name = process_image(raw, tool)

        if not is_premium(uid):
            remove_credits(uid, cost, f"Used {tool}")
        add_xp(uid, XP_SUCCESS)
        log_history(uid, tool, "success", "image.jpg", cost)

        await status.edit_text(progress_text(100, out_name), parse_mode=ParseMode.HTML)
        await send_result(update, result, out_name)
    except Exception as e:
        await status.edit_text(f"🚨 প্রসেস ব্যর্থ: {str(e)[:250]}")
    finally:
        context.user_data.pop("selected_tool", None)

async def done_images(update, context):
    uid = update.effective_user.id
    files = context.user_data.get("image_batch", [])
    if not files:
        await update.message.reply_text("❌ কোনো ইমেজ পাওয়া যায়নি।")
        return
    cost = TOOL_COST["Multiple Images → PDF"]
    if not is_premium(uid) and get_user(uid)["credits"] < cost:
        await update.message.reply_text("💳 পর্যাপ্ত ক্রেডিট নেই।")
        return
    try:
        result, out_name = multiple_images_to_pdf(files)
        if not is_premium(uid):
            remove_credits(uid, cost, "Multiple Images PDF")
        add_xp(uid, XP_SUCCESS)
        await send_result(update, result, out_name)
    except Exception as e:
        await update.message.reply_text(f"🚨 ব্যর্থ: {str(e)}")
    finally:
        context.user_data.pop("image_batch", None)

async def done_command(update, context):
    uid = update.effective_user.id
    files = context.user_data.get("merge_files", [])
    if len(files) < 2:
        await update.message.reply_text("❌ কমপক্ষে ২টি PDF ফাইল পাঠাতে হবে।")
        return
    cost = TOOL_COST["Merge PDF"]
    if not is_premium(uid) and get_user(uid)["credits"] < cost:
        await update.message.reply_text("💳 পর্যাপ্ত ক্রেডিট নেই।")
        return
    try:
        res, out_name = merge_pdfs(files)
        if not is_premium(uid):
            remove_credits(uid, cost, "Merge PDF")
        await send_result(update, res, out_name)
    except Exception as e:
        await update.message.reply_text(f"🚨 মার্জ ব্যর্থ: {str(e)}")
    finally:
        context.user_data.pop("merge_mode", None)
        context.user_data.pop("merge_files", None)

# ============================================================
# FULL ADMIN PANEL & BROADCAST ENGINE
# ============================================================

def admin_only(func):
    async def wrapper(update, context):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ শুধুমাত্র অ্যাডমিনের জন্য।")
            return
        return await func(update, context)
    return wrapper

@admin_only
async def admin_cmd(update, context):
    await update.message.reply_text(
        """👑 <b>RAFIM ADMIN CENTER</b>

👤 Users:
/userinfo USER_ID
/ban USER_ID
/unban USER_ID
/addcredits USER_ID AMOUNT
/removecredits USER_ID AMOUNT

💎 Premium:
/addpremium USER_ID DAYS
/premiumrequests
/approvepremium ID
/rejectpremium ID

🎟️ Redeem Codes:
/createcode CODE CREDITS USES
/codes
/disablecode CODE

📊 Analytics:
/stats
/leaderboard

📢 Broadcast:
/broadcast""",
        parse_mode=ParseMode.HTML
    )

@admin_only
async def stats_cmd(update, context):
    con = db()
    u_count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    p_count = con.execute("SELECT COUNT(*) FROM users WHERE premium=1").fetchone()[0]
    banned = con.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]
    jobs = con.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    con.close()
    await update.message.reply_text(
        f"""📊 <b>DETAILED SYSTEM STATS</b>\n\n👥 মোট ইউজার: {u_count}\n💎 প্রিমিয়াম ইউজার: {p_count}\n🚫 ব্যানড ইউজার: {banned}\n⚙️ মোট জব প্রসেসড: {jobs}""",
        parse_mode=ParseMode.HTML
    )

@admin_only
async def userinfo(update, context):
    if not context.args:
        await update.message.reply_text("ব্যবহার: /userinfo USER_ID")
        return
    uid = int(context.args[0])
    u = get_user(uid)
    if not u:
        await update.message.reply_text("❌ ইউজার পাওয়া যায়নি।")
        return
    await update.message.reply_text(
        f"""👤 <b>USER DETAILS:</b>\n🆔 ID: <code>{uid}</code>\n👤 Name: {u['first_name']}\n💳 Credits: {u['credits']}\n💎 Premium: {u['premium']}\n📅 Until: {u['premium_until']}\n⭐ Level: {u['level']} | XP: {u['xp']}\n🚫 Banned: {u['banned']}""",
        parse_mode=ParseMode.HTML
    )

@admin_only
async def addcredits_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("ব্যবহার: /addcredits USER_ID AMOUNT")
        return
    uid, amt = int(context.args[0]), int(context.args[1])
    add_credits(uid, amt, "Admin Add")
    await update.message.reply_text(f"✅ {uid} ইউজারের অ্যাকাউন্টে {amt} ক্রেডিট যোগ হয়েছে।")

@admin_only
async def removecredits_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("ব্যবহার: /removecredits USER_ID AMOUNT")
        return
    uid, amt = int(context.args[0]), int(context.args[1])
    remove_credits(uid, amt, "Admin Deduct")
    await update.message.reply_text(f"✅ {uid} ইউজারের অ্যাকাউন্ট থেকে {amt} ক্রেডিট কেটে নেওয়া হয়েছে।")

@admin_only
async def addpremium_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("ব্যবহার: /addpremium USER_ID DAYS")
        return
    uid, days = int(context.args[0]), int(context.args[1])
    expiry = datetime.now() + timedelta(days=days)
    con = db()
    con.execute("UPDATE users SET premium=1, premium_until=? WHERE user_id=?", (expiry.isoformat(), uid))
    con.commit()
    con.close()
    await update.message.reply_text(f"💎 User {uid}-কে {days} দিনের জন্য Premium দেওয়া হয়েছে।")

@admin_only
async def ban_cmd(update, context):
    if not context.args:
        return
    uid = int(context.args[0])
    con = db()
    con.execute("UPDATE users SET banned=1 WHERE user_id=?", (uid,))
    con.commit()
    con.close()
    await update.message.reply_text(f"🚫 User {uid} ব্যান করা হয়েছে।")

@admin_only
async def unban_cmd(update, context):
    if not context.args:
        return
    uid = int(context.args[0])
    con = db()
    con.execute("UPDATE users SET banned=0 WHERE user_id=?", (uid,))
    con.commit()
    con.close()
    await update.message.reply_text(f"✅ User {uid} আনব্যান করা হয়েছে।")

@admin_only
async def leaderboard_cmd(update, context):
    con = db()
    rows = con.execute("SELECT first_name, referral_count FROM users ORDER BY referral_count DESC LIMIT 10").fetchall()
    con.close()
    text = "🏆 <b>REFERRAL LEADERBOARD</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r['first_name']} — {r['referral_count']} referrals\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

@admin_only
async def createcode_cmd(update, context):
    if len(context.args) < 3:
        await update.message.reply_text("ব্যবহার: /createcode CODE CREDITS USES")
        return
    code, credits, uses = context.args[0].upper(), int(context.args[1]), int(context.args[2])
    con = db()
    con.execute("INSERT INTO redeem_codes(code,credits,max_uses,created_at) VALUES(?,?,?,?)", (code, credits, uses, datetime.now().isoformat()))
    con.commit()
    con.close()
    await update.message.reply_text(f"🎟️ কোড তৈরি হয়েছে: <code>{code}</code> (Credits: {credits}, Uses: {uses})", parse_mode=ParseMode.HTML)

@admin_only
async def codes_cmd(update, context):
    con = db()
    rows = con.execute("SELECT * FROM redeem_codes ORDER BY created_at DESC").fetchall()
    con.close()
    text = "🎟️ <b>REDEEM CODES:</b>\n\n"
    for r in rows:
        text += f"🔐 <code>{r['code']}</code> | +{r['credits']} Credits | Uses: {r['used_count']}/{r['max_uses']}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

@admin_only
async def broadcast(update, context):
    context.user_data["broadcast_mode"] = True
    await update.message.reply_text("📢 <b>ব্রডকাস্ট মেসেজটি লিখে পাঠান:</b>", parse_mode=ParseMode.HTML)

async def run_broadcast(bot, message):
    con = db()
    rows = con.execute("SELECT user_id FROM users WHERE banned=0").fetchall()
    con.close()
    sent = 0
    for r in rows:
        try:
            await bot.send_message(r["user_id"], message, parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

async def broadcast_text_handler(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    if context.user_data.get("broadcast_mode"):
        context.user_data["broadcast_mode"] = False
        msg = update.message.text
        await update.message.reply_text("🚀 ব্রডকাস্ট পাঠানো শুরু হয়েছে...")
        asyncio.create_task(run_broadcast(context.bot, msg))

# ============================================================
# MAIN INITIALIZER
# ============================================================

async def post_init(application):
    application.create_task(premium_expiry_watcher(application))

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN পাওয়া যায়নি!")

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # সাধারণ কমান্ড
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CommandHandler("account", account))
    application.add_handler(CommandHandler("bonus", bonus))
    application.add_handler(CommandHandler("refer", refer))
    application.add_handler(CommandHandler("history", history_cmd))
    application.add_handler(CommandHandler("support", support))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("premium", premium))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("doneimages", done_images))

    # অ্যাডমিন কমান্ড
    application.add_handler(CommandHandler("admin", admin_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("userinfo", userinfo))
    application.add_handler(CommandHandler("addcredits", addcredits_cmd))
    application.add_handler(CommandHandler("removecredits", removecredits_cmd))
    application.add_handler(CommandHandler("addpremium", addpremium_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))
    application.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    application.add_handler(CommandHandler("createcode", createcode_cmd))
    application.add_handler(CommandHandler("codes", codes_cmd))
    application.add_handler(CommandHandler("broadcast", broadcast))

    # কলব্যাক ও মেসেজ হ্যান্ডলার
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID), broadcast_text_handler), group=1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("===================================")
    print(" RAFIM MULTI-PRO COMPLETE BOT RUNNING")
    print(" 8 ACTIVE TOOLS FULLY LOADED")
    print("===================================")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
