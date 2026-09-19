import os
import io
import re
import sqlite3
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime, date, timedelta

import fitz  # PyMuPDF
from PIL import Image
from docx import Document as DocxDocument

from flask import Flask
from threading import Thread

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

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8298133943"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "rafimhossen")

FREE_CREDITS = 10
DAILY_BONUS = 2
REFERRAL_BONUS = 5

DB_FILE = "rafim_pdf_pro.db"

app_web = Flask(__name__)


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

@app_web.route("/")
def home():
    return "Rafim PDF Pro is running ✅"


@app_web.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.getenv("PORT", "10000"))
    app_web.run(host="0.0.0.0", port=port)


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_FILE)
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
            premium_until TEXT,
            last_bonus TEXT,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            credits INTEGER NOT NULL,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS redemptions (
            user_id INTEGER,
            code TEXT,
            redeemed_at TEXT,
            PRIMARY KEY(user_id, code)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tool TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def ensure_user(user):
    conn = db()
    cur = conn.cursor()

    row = cur.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    ).fetchone()

    if not row:
        cur.execute("""
            INSERT INTO users
            (user_id, username, first_name, credits, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            FREE_CREDITS,
            datetime.utcnow().isoformat()
        ))
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
    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row


def add_credits(user_id, amount):
    conn = db()
    conn.execute(
        "UPDATE users SET credits=credits+? WHERE user_id=?",
        (amount, user_id)
    )
    conn.commit()
    conn.close()


def spend_credit(user_id, amount=1):
    conn = db()
    cur = conn.cursor()

    row = cur.execute(
        "SELECT credits FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not row or row["credits"] < amount:
        conn.close()
        return False

    cur.execute(
        "UPDATE users SET credits=credits-? WHERE user_id=?",
        (amount, user_id)
    )

    conn.commit()
    conn.close()
    return True


def log_usage(user_id, tool):
    conn = db()
    conn.execute(
        "INSERT INTO usage(user_id, tool, created_at) VALUES (?, ?, ?)",
        (user_id, tool, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


# =========================================================
# KEYBOARDS
# =========================================================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📄 PDF Tools", "🖼️ Image Tools"],
        ["⭐ Premium", "👤 My Account"],
        ["🎁 Daily Bonus", "🎉 Refer & Earn"],
        ["🎟️ Redeem Code", "📜 History"],
        ["💬 Support"],
    ],
    resize_keyboard=True,
    is_persistent=True
)


def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="main")]
    ])


PDF_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📕 PDF → Word", callback_data="pdf_word"),
        InlineKeyboardButton("📝 PDF → TXT", callback_data="pdf_txt")
    ],
    [
        InlineKeyboardButton("🖼️ PDF → JPG", callback_data="pdf_jpg"),
        InlineKeyboardButton("🖼️ PDF → PNG", callback_data="pdf_png")
    ],
    [
        InlineKeyboardButton("🗜️ Compress PDF", callback_data="pdf_compress"),
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
        InlineKeyboardButton("🔓 Unlock PDF", callback_data="pdf_unlock")
    ],
    [
        InlineKeyboardButton("⬅️ Back", callback_data="main")
    ]
])


IMAGE_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📄 JPG/PNG → PDF", callback_data="img_pdf"),
        InlineKeyboardButton("🗜️ Compress Image", callback_data="img_compress")
    ],
    [
        InlineKeyboardButton("🔄 Convert Image", callback_data="img_convert"),
        InlineKeyboardButton("📐 Resize Image", callback_data="img_resize")
    ],
    [
        InlineKeyboardButton("⬅️ Back", callback_data="main")
    ]
])


# =========================================================
# HELPERS
# =========================================================

def safe_name(name):
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)


async def send_processing(update, text="⚙️ Processing..."):
    if update.callback_query:
        return await update.callback_query.message.reply_text(text)
    return await update.message.reply_text(text)


async def progress(message, text):
    try:
        await message.edit_text(text)
    except Exception:
        pass


def temp_dir():
    return Path(tempfile.mkdtemp(prefix="rafim_pdf_"))


def is_premium(user_id):
    row = get_user(user_id)

    if not row or not row["premium_until"]:
        return False

    try:
        return datetime.fromisoformat(
            row["premium_until"]
        ) > datetime.utcnow()
    except Exception:
        return False


def tool_cost(tool):
    return {
        "PDF → Word": 2,
        "PDF → TXT": 1,
        "PDF → JPG": 1,
        "PDF → PNG": 1,
        "Compress PDF": 2,
        "Merge PDF": 2,
        "Split PDF": 2,
        "Extract Pages": 2,
        "PDF → XPS": 2,
        "Protect PDF": 2,
        "Unlock PDF": 2,
        "Image → PDF": 1,
        "Compress Image": 1,
        "Convert Image": 1,
        "Resize Image": 1,
    }.get(tool, 1)


def check_cost(user_id, tool):
    if is_premium(user_id):
        return True

    row = get_user(user_id)
    return row and row["credits"] >= tool_cost(tool)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    # Referral
    args = context.args

    if args:
        try:
            ref_id = int(args[0])

            if ref_id != user.id:
                conn = db()

                current = conn.execute(
                    "SELECT referred_by FROM users WHERE user_id=?",
                    (user.id,)
                ).fetchone()

                if current and current["referred_by"] is None:
                    ref = conn.execute(
                        "SELECT user_id FROM users WHERE user_id=?",
                        (ref_id,)
                    ).fetchone()

                    if ref:
                        conn.execute("""
                            UPDATE users
                            SET referred_by=?
                            WHERE user_id=?
                        """, (ref_id, user.id))

                        conn.execute("""
                            UPDATE users
                            SET credits=credits+?,
                                referral_count=referral_count+1
                            WHERE user_id=?
                        """, (REFERRAL_BONUS, ref_id))

                        conn.commit()

                conn.close()
        except Exception:
            pass

    row = get_user(user.id)

    text = f"""
✨ <b>Welcome to Rafim PDF Pro</b> ✨

🚀 Your smart PDF & Image utility bot.

📄 PDF Tools
🖼️ Image Tools
⭐ Premium
🎁 Daily Bonus
🎉 Refer & Earn
🎟️ Redeem Code

💳 Your Credits: <b>{row["credits"]}</b>

━━━━━━━━━━━━━━━━━━
⚡ Fast • Simple • Useful
🔐 Your files are processed temporarily.
━━━━━━━━━━━━━━━━━━
"""

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD
    )


# =========================================================
# MAIN MENU
# =========================================================

async def main_menu(update, context):
    await update.message.reply_text(
        """
🏠 <b>Rafim PDF Pro</b>

👇 Choose a service:

📄 PDF Tools
🖼️ Image Tools
⭐ Premium
👤 My Account
🎁 Daily Bonus
🎉 Refer & Earn
🎟️ Redeem Code
📜 History
💬 Support
""",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD
    )


async def pdf_tools(update, context):
    await update.message.reply_text(
        """
📄 <b>PDF TOOLS</b>

Choose what you want to do 👇

⚡ Professional PDF utilities
🔐 Secure processing
🚀 Fast conversion
""",
        parse_mode="HTML",
        reply_markup=PDF_KEYBOARD
    )


async def image_tools(update, context):
    await update.message.reply_text(
        """
🖼️ <b>IMAGE TOOLS</b>

Choose an image operation 👇
""",
        parse_mode="HTML",
        reply_markup=IMAGE_KEYBOARD
    )


# =========================================================
# ACCOUNT
# =========================================================

async def account(update, context):
    row = get_user(update.effective_user.id)

    premium = "❌ Free"

    if is_premium(update.effective_user.id):
        premium = f"⭐ Premium until {row['premium_until']}"

    await update.message.reply_text(
        f"""
👤 <b>MY ACCOUNT</b>

🆔 User ID: <code>{row["user_id"]}</code>
💳 Credits: <b>{row["credits"]}</b>
⭐ Plan: {premium}
🎉 Referrals: <b>{row["referral_count"]}</b>

━━━━━━━━━━━━━━━━━━
Rafim PDF Pro
""",
        parse_mode="HTML"
    )


# =========================================================
# DAILY BONUS
# =========================================================

async def daily_bonus(update, context):
    user_id = update.effective_user.id
    row = get_user(user_id)

    today = date.today().isoformat()

    if row["last_bonus"] == today:
        await update.message.reply_text(
            "⏳ <b>Today's bonus already claimed!</b>\n\nCome back tomorrow 🎁",
            parse_mode="HTML"
        )
        return

    conn = db()

    conn.execute("""
        UPDATE users
        SET credits=credits+?, last_bonus=?
        WHERE user_id=?
    """, (DAILY_BONUS, today, user_id))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"""
🎁 <b>DAILY BONUS CLAIMED!</b>

➕ <b>+{DAILY_BONUS} Credits</b>

💳 Your credits have been updated.

Come back tomorrow 🚀
""",
        parse_mode="HTML"
    )


# =========================================================
# REFER & EARN
# =========================================================

async def referral(update, context):
    user_id = update.effective_user.id

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={user_id}"

    row = get_user(user_id)

    await update.message.reply_text(
        f"""
🎉 <b>REFER & EARN</b>

Invite your friends using your personal link.

🔗 Your link:

<code>{link}</code>

🎁 Reward:
<b>+{REFERRAL_BONUS} credits</b> per successful referral.

👥 Your referrals: <b>{row["referral_count"]}</b>
""",
        parse_mode="HTML"
    )


# =========================================================
# PREMIUM
# =========================================================

async def premium(update, context):
    await update.message.reply_text(
        """
⭐ <b>RAFIM PDF PRO PREMIUM</b>

Premium members get:

🚀 Priority processing
♾️ More usage
💎 Premium utilities
📦 Larger workflow support

━━━━━━━━━━━━━━━━━━

💳 Plans

🗓️ Weekly
🗓️ Monthly
💳 Credit Packs

Payment integration can be connected later.

💬 Contact Support:
@rafimhossen
""",
        parse_mode="HTML"
    )


# =========================================================
# SUPPORT
# =========================================================

async def support(update, context):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 Contact Support",
                url=f"https://t.me/{SUPPORT_USERNAME}"
            )
        ]
    ])

    await update.message.reply_text(
        """
💬 <b>SUPPORT</b>

Need help?

Our support:
@rafimhossen

Tap the button below 👇
""",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# HISTORY
# =========================================================

async def history(update, context):
    user_id = update.effective_user.id

    conn = db()

    rows = conn.execute("""
        SELECT tool, created_at
        FROM usage
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (user_id,)).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "📜 <b>History is empty.</b>\n\nStart using a tool 🚀",
            parse_mode="HTML"
        )
        return

    text = "📜 <b>YOUR RECENT HISTORY</b>\n\n"

    for r in rows:
        text += f"• {r['tool']}\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# REDEEM CODE
# =========================================================

async def redeem_start(update, context):
    context.user_data["awaiting_redeem"] = True

    await update.message.reply_text(
        """
🎟️ <b>REDEEM CODE</b>

Send your redeem code now.

Example:
<code>RAFIM20</code>

🔐 Codes are checked automatically.
""",
        parse_mode="HTML"
    )


async def process_redeem(update, context):
    user_id = update.effective_user.id
    code = update.message.text.strip().upper()

    context.user_data["awaiting_redeem"] = False

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM redeem_codes
        WHERE code=? AND active=1
    """, (code,)).fetchone()

    if not row:
        conn.close()

        await update.message.reply_text(
            "❌ <b>Invalid or disabled redeem code.</b>",
            parse_mode="HTML"
        )
        return

    if row["used_count"] >= row["max_uses"]:
        conn.close()

        await update.message.reply_text(
            "⚠️ <b>This code has reached its maximum uses.</b>",
            parse_mode="HTML"
        )
        return

    already = conn.execute("""
        SELECT 1
        FROM redemptions
        WHERE user_id=? AND code=?
    """, (user_id, code)).fetchone()

    if already:
        conn.close()

        await update.message.reply_text(
            "⚠️ <b>You have already redeemed this code.</b>",
            parse_mode="HTML"
        )
        return

    conn.execute("""
        INSERT INTO redemptions(user_id, code, redeemed_at)
        VALUES (?, ?, ?)
    """, (
        user_id,
        code,
        datetime.utcnow().isoformat()
    ))

    conn.execute("""
        UPDATE redeem_codes
        SET used_count=used_count+1
        WHERE code=?
    """, (code,))

    conn.execute("""
        UPDATE users
        SET credits=credits+?
        WHERE user_id=?
    """, (row["credits"], user_id))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"""
🎉 <b>REDEEM SUCCESSFUL!</b>

🎟️ Code: <code>{code}</code>
💳 Reward: <b>+{row["credits"]} credits</b>

🚀 Enjoy Rafim PDF Pro!
""",
        parse_mode="HTML"
    )


# =========================================================
# CALLBACK MENU
# =========================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "main":
        await query.message.edit_text(
            """
🏠 <b>RAFIM PDF PRO</b>

Use the keyboard below to choose a service.

👇 Select an option:
""",
            parse_mode="HTML"
        )
        return

    if data.startswith("pdf_"):
        await pdf_callback(query, context, data)
        return

    if data.startswith("img_"):
        await image_callback(query, context, data)
        return


# =========================================================
# PDF CALLBACK
# =========================================================

PDF_INSTRUCTIONS = {
    "pdf_word": (
        "📕 PDF → Word",
        "Send a PDF file.\n\n⚠️ This creates a text-based DOCX."
    ),
    "pdf_txt": (
        "📝 PDF → TXT",
        "Send your PDF file."
    ),
    "pdf_jpg": (
        "🖼️ PDF → JPG",
        "Send your PDF file."
    ),
    "pdf_png": (
        "🖼️ PDF → PNG",
        "Send your PDF file."
    ),
    "pdf_compress": (
        "🗜️ Compress PDF",
        "Send your PDF file."
    ),
    "pdf_merge": (
        "🔗 Merge PDF",
        "Send the first PDF, then send additional PDFs.\n\nWhen finished type /done"
    ),
    "pdf_split": (
        "✂️ Split PDF",
        "Send the PDF you want to split."
    ),
    "pdf_extract": (
        "📑 Extract Pages",
        "Send the PDF first.\n\nThen tell me the page numbers, e.g.:\n1,3,5"
    ),
    "pdf_xps": (
        "📦 PDF → XPS",
        "Send your PDF file."
    ),
    "pdf_protect": (
        "🔐 Protect PDF",
        "Send the PDF first.\nThen send the password."
    ),
    "pdf_unlock": (
        "🔓 Unlock PDF",
        "Send the protected PDF first.\nThen send its password."
    ),
}


async def pdf_callback(query, context, data):
    title, instruction = PDF_INSTRUCTIONS.get(
        data,
        ("PDF Tool", "Send your PDF file.")
    )

    context.user_data["mode"] = data

    await query.message.edit_text(
        f"""
{title}

━━━━━━━━━━━━━━━━━━

{instruction}

💳 Tool cost:
<b>{tool_cost(title.replace("📕 ", "").replace("📝 ", "").replace("🖼️ ", "").replace("🗜️ ", "").replace("🔗 ", "").replace("✂️ ", "").replace("📑 ", "").replace("📦 ", "").replace("🔐 ", "").replace("🔓 ", ""))}</b> credit

⭐ Premium users may have different limits.
""",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )


# =========================================================
# IMAGE CALLBACK
# =========================================================

async def image_callback(query, context, data):
    instructions = {
        "img_pdf": (
            "📄 JPG/PNG → PDF",
            "Send a JPG or PNG image."
        ),
        "img_compress": (
            "🗜️ Compress Image",
            "Send a JPG/PNG image."
        ),
        "img_convert": (
            "🔄 Convert Image",
            "Send an image."
        ),
        "img_resize": (
            "📐 Resize Image",
            "Send an image.\n\nThen send width and height like:\n1080 1080"
        ),
    }

    title, instruction = instructions.get(
        data,
        ("Image Tool", "Send an image.")
    )

    context.user_data["mode"] = data

    await query.message.edit_text(
        f"""
{title}

━━━━━━━━━━━━━━━━━━

{instruction}

🚀 Send your file now.
""",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )


# =========================================================
# DOCUMENT HANDLER
# =========================================================

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    mode = context.user_data.get("mode")

    if not mode:
        await update.message.reply_text(
            "📂 Please choose a tool first.",
            reply_markup=MAIN_KEYBOARD
        )
        return

    document = update.message.document

    if not document:
        return

    if document.file_size and document.file_size > 50 * 1024 * 1024:
        await update.message.reply_text(
            "⚠️ Maximum file size is 50 MB."
        )
        return

    work = temp_dir()

    try:
        tg_file = await document.get_file()

        input_path = work / safe_name(
            document.file_name or "input.pdf"
        )

        await tg_file.download_to_drive(str(input_path))

        if mode == "pdf_merge":
            await handle_merge_file(update, context, input_path)
            return

        await process_pdf_file(
            update,
            context,
            input_path,
            mode,
            work
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ <b>Processing failed.</b>\n\n<code>{str(e)[:500]}</code>",
            parse_mode="HTML"
        )

        shutil.rmtree(work, ignore_errors=True)


# =========================================================
# PDF PROCESSING
# =========================================================

async def process_pdf_file(update, context, input_path, mode, work):
    user_id = update.effective_user.id

    tool_names = {
        "pdf_word": "PDF → Word",
        "pdf_txt": "PDF → TXT",
        "pdf_jpg": "PDF → JPG",
        "pdf_png": "PDF → PNG",
        "pdf_compress": "Compress PDF",
        "pdf_split": "Split PDF",
        "pdf_extract": "Extract Pages",
        "pdf_xps": "PDF → XPS",
        "pdf_protect": "Protect PDF",
        "pdf_unlock": "Unlock PDF",
    }

    tool = tool_names.get(mode, "PDF Tool")
    cost = tool_cost(tool)

    if not check_cost(user_id, tool):
        await update.message.reply_text(
            f"""
❌ <b>Not enough credits.</b>

💳 Required: {cost}
💰 Available: {get_user(user_id)["credits"]}

🎁 Use Daily Bonus
🎉 Refer friends
🎟️ Redeem a code
⭐ Get Premium
""",
            parse_mode="HTML"
        )
        shutil.rmtree(work, ignore_errors=True)
        return

    status = await update.message.reply_text(
        "⚙️ <b>10%</b>\nStarting processing...",
        parse_mode="HTML"
    )

    try:
        if mode == "pdf_txt":
            await progress(status, "⚙️ <b>30%</b>\nReading PDF...")

            doc = fitz.open(str(input_path))
            text = ""

            for page in doc:
                text += page.get_text() + "\n"

            doc.close()

            output = work / "converted.txt"
            output.write_text(text, encoding="utf-8")

            await progress(status, "⚙️ <b>90%</b>\nFinalizing...")

            if not spend_credit(user_id, cost) and not is_premium(user_id):
                raise Exception("Credit deduction failed")

            log_usage(user_id, tool)

            await status.delete()

            with open(output, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="converted.txt",
                    caption="✅ PDF → TXT complete!"
                )

        elif mode in ("pdf_jpg", "pdf_png"):
            await progress(status, "⚙️ <b>20%</b>\nOpening PDF...")

            doc = fitz.open(str(input_path))
            total = len(doc)

            for i, page in enumerate(doc):
                percent = 20 + int(((i + 1) / total) * 70)

                await progress(
                    status,
                    f"⚙️ <b>{percent}%</b>\nConverting page {i+1}/{total}..."
                )

                pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7))

                ext = "jpg" if mode == "pdf_jpg" else "png"
                output = work / f"page_{i+1}.{ext}"

                if ext == "jpg":
                    pix.save(str(output), output="jpeg")
                else:
                    pix.save(str(output), output="png")

            doc.close()

            if not spend_credit(user_id, cost) and not is_premium(user_id):
                raise Exception("Credit deduction failed")

            log_usage(user_id, tool)

            await status.delete()

            files = sorted(work.glob(f"page_*.{ext}"))

            for file in files:
                with open(file, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename=file.name
                    )

            await update.message.reply_text(
                "✅ <b>Conversion complete!</b>",
                parse_mode="HTML"
            )

        elif mode == "pdf_word":
            await progress(status, "⚙️ <b>30%</b>\nExtracting text...")

            doc = fitz.open(str(input_path))
            word = DocxDocument()

            for i, page in enumerate(doc):
                text = page.get_text()

                if text.strip():
                    word.add_heading(
                        f"Page {i+1}",
                        level=2
                    )
                    word.add_paragraph(text)

            doc.close()

            output = work / "converted.docx"
            word.save(str(output))

            await progress(status, "⚙️ <b>90%</b>\nCreating Word file...")

            if not spend_credit(user_id, cost) and not is_premium(user_id):
                raise Exception("Credit deduction failed")

            log_usage(user_id, tool)

            await status.delete()

            with open(output, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="converted.docx",
                    caption="✅ PDF → Word complete!"
                )

        elif mode == "pdf_compress":
            await progress(status, "⚙️ <b>30%</b>\nCompressing PDF...")

            output = work / "compressed.pdf"

            subprocess.run(
                [
                    "gs",
                    "-sDEVICE=pdfwrite",
                    "-dCompatibilityLevel=1.4",
                    "-dPDFSETTINGS=/ebook",
                    "-dNOPAUSE",
                    "-dQUIET",
                    "-dBATCH",
                    f"-sOutputFile={output}",
                    str(input_path),
                ],
                check=True
            )

            await progress(status, "⚙️ <b>90%</b>\nFinalizing...")

            if not spend_credit(user_id, cost) and not is_premium(user_id):
                raise Exception("Credit deduction failed")

            log_usage(user_id, tool)

            await status.delete()

            with open(output, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="compressed.pdf",
                    caption="✅ PDF compressed!"
                )

        elif mode == "pdf_xps":
            await progress(status, "⚙️ <b>30%</b>\nConverting PDF → XPS...")

            output = work / "converted.xps"

            subprocess.run(
                [
                    "gs",
                    "-sDEVICE=xpswrite",
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-dQUIET",
                    f"-sOutputFile={output}",
                    str(input_path),
                ],
                check=True
            )

            await progress(status, "⚙️ <b>90%</b>\nFinalizing XPS...")

            if not spend_credit(user_id, cost) and not is_premium(user_id):
                raise Exception("Credit deduction failed")

            log_usage(user_id, tool)

            await status.delete()

            with open(output, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="converted.xps",
                    caption="✅ PDF → XPS complete!"
                )

        elif mode == "pdf_split":
            await progress(status, "⚙️ <b>30%</b>\nSplitting PDF...")

            doc = fitz.open(str(input_path))
            total = len(doc)

            for i in range(total):
                output = work / f"split_page_{i+1}.pdf"

                new_doc = fitz.open()
                new_doc.insert_pdf(
                    doc,
                    from_page=i,
                    to_page=i
                )
                new_doc.save(str(output))
                new_doc.close()

            doc.close()

            if not spend_credit(user_id, cost) and not is_premium(user_id):
                raise Exception("Credit deduction failed")

            log_usage(user_id, tool)

            await status.delete()

            await update.message.reply_text(
                f"✅ Split complete!\n\n📄 Pages created: {total}"
            )

            for file in sorted(work.glob("split_page_*.pdf")):
                with open(file, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename=file.name
                    )

        elif mode == "pdf_extract":
            context.user_data["extract_pdf"] = str(input_path)
            context.user_data["extract_work"] = str(work)

            await progress(
                status,
                "📑 <b>PDF received.</b>\n\n"
                "Now send page numbers.\n\n"
                "Example: <code>1,3,5</code>"
            )

            return

        elif mode == "pdf_protect":
            context.user_data["protect_pdf"] = str(input_path)
            context.user_data["protect_work"] = str(work)

            await progress(
                status,
                "🔐 <b>PDF received.</b>\n\n"
                "Now send the password you want to use."
            )

            return

        elif mode == "pdf_unlock":
            context.user_data["unlock_pdf"] = str(input_path)
            context.user_data["unlock_work"] = str(work)

            await progress(
                status,
                "🔓 <b>Protected PDF received.</b>\n\n"
                "Now send the PDF password."
            )

            return

        await progress(status, "✅ <b>100%</b>\nComplete!")

    except Exception as e:
        await status.edit_text(
            f"❌ <b>Processing error</b>\n\n<code>{str(e)[:500]}</code>",
            parse_mode="HTML"
        )

        shutil.rmtree(work, ignore_errors=True)


# =========================================================
# TEXT HANDLER FOR PASSWORD / PAGES / RESIZE
# =========================================================

async def text_handler(update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    ensure_user(update.effective_user)

    # Redeem
    if context.user_data.get("awaiting_redeem"):
        await process_redeem(update, context)
        return

    # Extract pages
    if context.user_data.get("extract_pdf"):
        await extract_pages(update, context, text)
        return

    # Protect
    if context.user_data.get("protect_pdf"):
        await protect_pdf(update, context, text)
        return

    # Unlock
    if context.user_data.get("unlock_pdf"):
        await unlock_pdf(update, context, text)
        return

    # Resize
    if context.user_data.get("resize_image"):
        await resize_image(update, context, text)
        return

    # Main keyboard
    if text == "📄 PDF Tools":
        await pdf_tools(update, context)

    elif text == "🖼️ Image Tools":
        await image_tools(update, context)

    elif text == "⭐ Premium":
        await premium(update, context)

    elif text == "👤 My Account":
        await account(update, context)

    elif text == "🎁 Daily Bonus":
        await daily_bonus(update, context)

    elif text == "🎉 Refer & Earn":
        await referral(update, context)

    elif text == "🎟️ Redeem Code":
        await redeem_start(update, context)

    elif text == "📜 History":
        await history(update, context)

    elif text == "💬 Support":
        await support(update, context)

    else:
        await update.message.reply_text(
            "👇 Please choose an option from the menu.",
            reply_markup=MAIN_KEYBOARD
        )


# =========================================================
# EXTRACT PAGES
# =========================================================

async def extract_pages(update, context, text):
    user_id = update.effective_user.id
    pdf_path = context.user_data.get("extract_pdf")
    work_path = Path(context.user_data.get("extract_work"))

    if not pdf_path:
        return

    try:
        pages = []

        for item in text.split(","):
            n = int(item.strip())
            if n > 0:
                pages.append(n - 1)

        doc = fitz.open(pdf_path)

        valid = [
            p for p in pages
            if 0 <= p < len(doc)
        ]

        if not valid:
            raise Exception("Invalid page numbers")

        output = work_path / "extracted_pages.pdf"

        new_doc = fitz.open()

        for p in valid:
            new_doc.insert_pdf(
                doc,
                from_page=p,
                to_page=p
            )

        new_doc.save(str(output))
        new_doc.close()
        doc.close()

        cost = tool_cost("Extract Pages")

        if not check_cost(user_id, "Extract Pages"):
            await update.message.reply_text(
                "❌ Not enough credits."
            )
            return

        if not spend_credit(user_id, cost) and not is_premium(user_id):
            raise Exception("Credit deduction failed")

        log_usage(user_id, "Extract Pages")

        with open(output, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="extracted_pages.pdf",
                caption="✅ Pages extracted!"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

    finally:
        context.user_data.pop("extract_pdf", None)
        context.user_data.pop("extract_work", None)


# =========================================================
# PROTECT PDF
# =========================================================

async def protect_pdf(update, context, password):
    user_id = update.effective_user.id

    pdf_path = context.user_data.get("protect_pdf")
    work = Path(context.user_data.get("protect_work"))

    try:
        if not check_cost(user_id, "Protect PDF"):
            await update.message.reply_text(
                "❌ Not enough credits."
            )
            return

        doc = fitz.open(pdf_path)
        output = work / "protected.pdf"

        doc.save(
            str(output),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=password,
            user_pw=password
        )

        doc.close()

        if not spend_credit(user_id, tool_cost("Protect PDF")) and not is_premium(user_id):
            raise Exception("Credit deduction failed")

        log_usage(user_id, "Protect PDF")

        with open(output, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="protected.pdf",
                caption="🔐 PDF protected successfully!"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Protect failed: {str(e)}"
        )

    finally:
        context.user_data.pop("protect_pdf", None)
        context.user_data.pop("protect_work", None)


# =========================================================
# UNLOCK PDF
# =========================================================

async def unlock_pdf(update, context, password):
    user_id = update.effective_user.id

    pdf_path = context.user_data.get("unlock_pdf")
    work = Path(context.user_data.get("unlock_work"))

    try:
        if not check_cost(user_id, "Unlock PDF"):
            await update.message.reply_text(
                "❌ Not enough credits."
            )
            return

        doc = fitz.open(pdf_path)

        if doc.needs_pass:
            if not doc.authenticate(password):
                raise Exception("Wrong PDF password")

        output = work / "unlocked.pdf"

        new_doc = fitz.open()
        new_doc.insert_pdf(doc)
        new_doc.save(
            str(output),
            encryption=fitz.PDF_ENCRYPT_NONE
        )

        new_doc.close()
        doc.close()

        if not spend_credit(user_id, tool_cost("Unlock PDF")) and not is_premium(user_id):
            raise Exception("Credit deduction failed")

        log_usage(user_id, "Unlock PDF")

        with open(output, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="unlocked.pdf",
                caption="🔓 PDF unlocked successfully!"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Unlock failed: {str(e)}"
        )

    finally:
        context.user_data.pop("unlock_pdf", None)
        context.user_data.pop("unlock_work", None)


# =========================================================
# MERGE PDF
# =========================================================

async def handle_merge_file(update, context, input_path):
    files = context.user_data.setdefault("merge_files", [])

    files.append(str(input_path))

    await update.message.reply_text(
        f"""
📎 <b>PDF added!</b>

Files in queue: <b>{len(files)}</b>

➕ Send another PDF

or

✅ Type /done when finished.
""",
        parse_mode="HTML"
    )


async def done_command(update, context):
    files = context.user_data.get("merge_files", [])

    if not files:
        await update.message.reply_text(
            "⚠️ No PDF files are waiting."
        )
        return

    user_id = update.effective_user.id

    if not check_cost(user_id, "Merge PDF"):
        await update.message.reply_text(
            "❌ Not enough credits."
        )
        return

    work = Path(files[0]).parent

    try:
        output = work / "merged.pdf"

        result = fitz.open()

        for file in files:
            doc = fitz.open(file)
            result.insert_pdf(doc)
            doc.close()

        result.save(str(output))
        result.close()

        if not spend_credit(user_id, tool_cost("Merge PDF")) and not is_premium(user_id):
            raise Exception("Credit deduction failed")

        log_usage(user_id, "Merge PDF")

        with open(output, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="merged.pdf",
                caption="🔗 PDF merge complete!"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Merge failed: {str(e)}"
        )

    finally:
        context.user_data.pop("merge_files", None)


# =========================================================
# IMAGE HANDLER
# =========================================================

async def image_handler(update, context):
    user_id = update.effective_user.id
    ensure_user(update.effective_user)

    mode = context.user_data.get("mode")

    if mode not in [
        "img_pdf",
        "img_compress",
        "img_convert",
        "img_resize"
    ]:
        return

    photo = None

    if update.message.photo:
        photo = update.message.photo[-1]

    elif update.message.document:
        photo = update.message.document

    if not photo:
        return

    work = temp_dir()

    try:
        tg_file = await photo.get_file()

        if update.message.document:
            name = safe_name(
                update.message.document.file_name or "image.jpg"
            )
        else:
            name = "image.jpg"

        input_path = work / name

        await tg_file.download_to_drive(str(input_path))

        if mode == "img_resize":
            context.user_data["resize_image"] = str(input_path)
            context.user_data["resize_work"] = str(work)

            await update.message.reply_text(
                """
📐 <b>Resize Image</b>

Send width and height.

Example:
<code>1080 1080</code>
""",
                parse_mode="HTML"
            )
            return

        await process_image(update, context, input_path, mode, work)

    except Exception as e:
        await update.message.reply_text(
            f"❌ Image processing failed: {str(e)}"
        )


# =========================================================
# IMAGE PROCESSING
# =========================================================

async def process_image(update, context, input_path, mode, work):
    user_id = update.effective_user.id

    tool = {
        "img_pdf": "Image → PDF",
        "img_compress": "Compress Image",
        "img_convert": "Convert Image",
    }[mode]

    cost = tool_cost(tool)

    if not check_cost(user_id, tool):
        await update.message.reply_text(
            "❌ Not enough credits."
        )
        return

    status = await update.message.reply_text(
        "⚙️ <b>10%</b>\nProcessing image...",
        parse_mode="HTML"
    )

    try:
        image = Image.open(input_path)

        await progress(
            status,
            "⚙️ <b>50%</b>\nProcessing image..."
        )

        if mode == "img_pdf":
            if image.mode != "RGB":
                image = image.convert("RGB")

            output = work / "converted.pdf"

            image.save(
                output,
                "PDF",
                resolution=100
            )

        elif mode == "img_compress":
            image = image.convert("RGB")
            output = work / "compressed.jpg"

            image.save(
                output,
                "JPEG",
                quality=55,
                optimize=True
            )

        else:
            image = image.convert("RGB")
            output = work / "converted.png"

            image.save(
                output,
                "PNG",
                optimize=True
            )

        await progress(
            status,
            "⚙️ <b>90%</b>\nFinalizing..."
        )

        if not spend_credit(user_id, cost) and not is_premium(user_id):
            raise Exception("Credit deduction failed")

        log_usage(user_id, tool)

        await status.delete()

        with open(output, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=output.name,
                caption="✅ Image processing complete!"
            )

    except Exception as e:
        await status.edit_text(
            f"❌ Error: {str(e)}"
        )


# =========================================================
# RESIZE IMAGE
# =========================================================

async def resize_image(update, context, text):
    try:
        parts = text.split()

        if len(parts) != 2:
            raise Exception("Use: 1080 1080")

        width = int(parts[0])
        height = int(parts[1])

        if width < 1 or height < 1 or width > 5000 or height > 5000:
            raise Exception("Invalid dimensions")

        user_id = update.effective_user.id

        if not check_cost(user_id, "Resize Image"):
            await update.message.reply_text(
                "❌ Not enough credits."
            )
            return

        path = context.user_data["resize_image"]
        work = Path(context.user_data["resize_work"])

        image = Image.open(path)
        image = image.resize((width, height))

        output = work / "resized.jpg"
        image.convert("RGB").save(
            output,
            "JPEG",
            quality=90
        )

        if not spend_credit(user_id, tool_cost("Resize Image")) and not is_premium(user_id):
            raise Exception("Credit deduction failed")

        log_usage(user_id, "Resize Image")

        with open(output, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="resized.jpg",
                caption="📐 Image resized successfully!"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Resize failed: {str(e)}"
        )

    finally:
        context.user_data.pop("resize_image", None)
        context.user_data.pop("resize_work", None)


# =========================================================
# ADMIN
# =========================================================

def admin_only(user_id):
    return user_id == ADMIN_ID


async def admin_command(update, context):
    if not admin_only(update.effective_user.id):
        return

    await update.message.reply_text(
        """
👑 <b>ADMIN PANEL</b>

Commands:

/createcode CODE CREDITS USES

Example:
/createcode RAFIM20 20 100

/codes
/disablecode CODE

/addcredits USER_ID AMOUNT
/addpremium USER_ID DAYS
/stats
""",
        parse_mode="HTML"
    )


async def create_code(update, context):
    if not admin_only(update.effective_user.id):
        return

    if len(context.args) != 3:
        await update.message.reply_text(
            "Usage:\n/createcode CODE CREDITS MAX_USES"
        )
        return

    code = context.args[0].upper()

    try:
        credits = int(context.args[1])
        uses = int(context.args[2])
    except:
        await update.message.reply_text("❌ Invalid numbers.")
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
            datetime.utcnow().isoformat()
        ))

        conn.commit()

        await update.message.reply_text(
            f"""
✅ <b>Redeem code created!</b>

🎟️ Code: <code>{code}</code>
💳 Credits: {credits}
👥 Max uses: {uses}
""",
            parse_mode="HTML"
        )

    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "⚠️ That code already exists."
        )

    finally:
        conn.close()


async def codes_command(update, context):
    if not admin_only(update.effective_user.id):
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

    text = "🎟️ <b>REDEEM CODES</b>\n\n"

    for r in rows:
        status = "ON" if r["active"] else "OFF"

        text += (
            f"<code>{r['code']}</code> | "
            f"+{r['credits']} | "
            f"{r['used_count']}/{r['max_uses']} | "
            f"{status}\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


async def disable_code(update, context):
    if not admin_only(update.effective_user.id):
        return

    if len(context.args) != 1:
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
        f"🚫 Code <code>{code}</code> disabled.",
        parse_mode="HTML"
    )


async def add_credits_command(update, context):
    if not admin_only(update.effective_user.id):
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
            "❌ Invalid numbers."
        )
        return

    add_credits(user_id, amount)

    await update.message.reply_text(
        f"✅ Added {amount} credits to {user_id}."
    )


async def add_premium_command(update, context):
    if not admin_only(update.effective_user.id):
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
            "❌ Invalid numbers."
        )
        return

    until = datetime.utcnow() + timedelta(days=days)

    conn = db()

    conn.execute("""
        UPDATE users
        SET premium_until=?
        WHERE user_id=?
    """, (
        until.isoformat(),
        user_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"⭐ Premium added for {days} days."
    )


async def stats_command(update, context):
    if not admin_only(update.effective_user.id):
        return

    conn = db()

    users = conn.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    usage = conn.execute(
        "SELECT COUNT(*) c FROM usage"
    ).fetchone()["c"]

    codes = conn.execute(
        "SELECT COUNT(*) c FROM redeem_codes"
    ).fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        f"""
📊 <b>BOT STATISTICS</b>

👥 Users: <b>{users}</b>
⚙️ Operations: <b>{usage}</b>
🎟️ Redeem codes: <b>{codes}</b>
""",
        parse_mode="HTML"
    )


# =========================================================
# ERRORS
# =========================================================

async def error_handler(update, context):
    print("ERROR:", context.error)


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    init_db()

    Thread(
        target=run_web,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("done", done_command)
    )

    application.add_handler(
        CommandHandler("admin", admin_command)
    )

    application.add_handler(
        CommandHandler("createcode", create_code)
    )

    application.add_handler(
        CommandHandler("codes", codes_command)
    )

    application.add_handler(
        CommandHandler("disablecode", disable_code)
    )

    application.add_handler(
        CommandHandler("addcredits", add_credits_command)
    )

    application.add_handler(
        CommandHandler("addpremium", add_premium_command)
    )

    application.add_handler(
        CommandHandler("stats", stats_command)
    )

    # Callback buttons
    application.add_handler(
        CallbackQueryHandler(callback_handler)
    )

    # Images
    application.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.IMAGE,
            image_handler
        )
    )

    # PDF/documents
    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler
        )
    )

    # Text
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    application.add_error_handler(error_handler)

    print("Rafim PDF Pro started successfully.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
