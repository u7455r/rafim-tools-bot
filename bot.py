import os
import re
import sqlite3
import secrets
import string
import tempfile
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, date

from flask import Flask
from threading import Thread

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

ADMIN_ID = 8298133943
SUPPORT_USERNAME = "rafimhossen"

BOT_NAME = "Rafim PDF Pro"
DB_FILE = "rafim_pdf_pro.db"

FREE_CREDITS = 10
DAILY_BONUS = 2
REFERRAL_BONUS = 5

# Tool costs
COSTS = {
    "pdf_txt": 1,
    "pdf_jpg": 2,
    "pdf_word": 3,
    "compress": 2,
    "merge": 2,
    "split": 2,
    "extract": 2,
    "pdf_xps": 3,
    "jpg_pdf": 2,
    "png_pdf": 2,
    "compress_image": 1,
}

BASE = Path(__file__).resolve().parent
TMP_DIR = BASE / "tmp"
TMP_DIR.mkdir(exist_ok=True)

# =========================================================
# DATABASE
# =========================================================

def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            credits INTEGER DEFAULT 10,
            premium_credits INTEGER DEFAULT 0,
            plan TEXT DEFAULT 'FREE',
            referred_by INTEGER,
            referrals INTEGER DEFAULT 0,
            total_used INTEGER DEFAULT 0,
            last_daily TEXT,
            joined_at TEXT
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            user_id INTEGER,
            credits INTEGER,
            redeemed_at TEXT,
            UNIQUE(code, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tool TEXT,
            cost INTEGER,
            created_at TEXT
        )
    """)

    con.commit()
    con.close()


def ensure_user(tg_user, referred_by=None):
    con = db()
    cur = con.cursor()

    row = cur.execute(
        "SELECT * FROM users WHERE user_id=?",
        (tg_user.id,)
    ).fetchone()

    if row:
        cur.execute("""
            UPDATE users
            SET username=?, first_name=?
            WHERE user_id=?
        """, (
            tg_user.username or "",
            tg_user.first_name or "",
            tg_user.id
        ))
        con.commit()
        con.close()
        return False

    now = datetime.utcnow().isoformat()

    cur.execute("""
        INSERT INTO users
        (user_id, username, first_name, credits, joined_at, referred_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        tg_user.id,
        tg_user.username or "",
        tg_user.first_name or "",
        FREE_CREDITS,
        now,
        referred_by
    ))

    # Referral reward
    if referred_by and referred_by != tg_user.id:
        parent = cur.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (referred_by,)
        ).fetchone()

        if parent:
            cur.execute("""
                UPDATE users
                SET credits=credits+?, referrals=referrals+1
                WHERE user_id=?
            """, (REFERRAL_BONUS, referred_by))

    con.commit()
    con.close()
    return True


def get_user(user_id):
    con = db()
    row = con.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    con.close()
    return row


def spend_credit(user_id, cost):
    con = db()
    cur = con.cursor()

    row = cur.execute(
        "SELECT credits, premium_credits FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not row:
        con.close()
        return False

    total = row["credits"] + row["premium_credits"]

    if total < cost:
        con.close()
        return False

    normal = row["credits"]
    premium = row["premium_credits"]

    if normal >= cost:
        normal -= cost
    else:
        remaining = cost - normal
        normal = 0
        premium -= remaining

    cur.execute("""
        UPDATE users
        SET credits=?, premium_credits=?, total_used=total_used+?
        WHERE user_id=?
    """, (normal, premium, cost, user_id))

    con.commit()
    con.close()
    return True


def log_usage(user_id, tool, cost):
    con = db()
    con.execute("""
        INSERT INTO usage(user_id, tool, cost, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        tool,
        cost,
        datetime.utcnow().isoformat()
    ))
    con.commit()
    con.close()


# =========================================================
# KEYBOARDS
# =========================================================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📄 PDF Tools", "🖼️ Image Tools"],
        ["💎 Premium", "👤 My Account"],
        ["🎁 Daily Bonus", "👥 Refer & Earn"],
        ["🎟️ Redeem Code", "📊 History"],
        ["🆘 Support"],
    ],
    resize_keyboard=True,
    is_persistent=True
)

PDF_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🔄 PDF → Word", callback_data="pdf_word"),
        InlineKeyboardButton("📝 PDF → TXT", callback_data="pdf_txt"),
    ],
    [
        InlineKeyboardButton("🖼️ PDF → JPG", callback_data="pdf_jpg"),
        InlineKeyboardButton("📦 Compress PDF", callback_data="compress"),
    ],
    [
        InlineKeyboardButton("🔗 Merge PDF", callback_data="merge"),
        InlineKeyboardButton("✂️ Split PDF", callback_data="split"),
    ],
    [
        InlineKeyboardButton("📑 Extract Pages", callback_data="extract"),
        InlineKeyboardButton("🔄 PDF → XPS", callback_data="pdf_xps"),
    ],
    [
        InlineKeyboardButton("⬅️ Back", callback_data="back_main")
    ]
])

IMAGE_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📸 JPG → PDF", callback_data="jpg_pdf"),
        InlineKeyboardButton("🖼️ PNG → PDF", callback_data="png_pdf"),
    ],
    [
        InlineKeyboardButton("📦 Compress Image", callback_data="compress_image"),
    ],
    [
        InlineKeyboardButton("⬅️ Back", callback_data="back_main")
    ]
])


# =========================================================
# TEXT
# =========================================================

WELCOME = """
🚀✨ <b>WELCOME TO RAFIM PDF PRO</b> ✨🚀

━━━━━━━━━━━━━━━━━━━━

📄 <b>Your Smart PDF Workspace</b>

⚡ Convert • Merge • Split
📦 Compress • Extract
🖼️ PDF → Images
📝 PDF → Text
🔄 PDF → XPS

🎁 <b>NEW USER BONUS UNLOCKED!</b>
💰 You received <b>10 Free Credits</b>.

🔥 Fast • Simple • Powerful
🛡️ Your files are processed temporarily.

━━━━━━━━━━━━━━━━━━━━

👇 <b>Choose your next action:</b>
"""


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    referred_by = None

    if args:
        try:
            referred_by = int(args[0])
        except ValueError:
            referred_by = None

    new_user = ensure_user(update.effective_user, referred_by)

    if new_user and referred_by and referred_by != update.effective_user.id:
        await update.message.reply_text(
            f"🎉 <b>Welcome!</b>\n\n"
            f"🎁 You received <b>{FREE_CREDITS} Free Credits</b>.\n"
            f"👥 Your referral was recorded successfully.",
            parse_mode="HTML"
        )

    await update.message.reply_text(
        WELCOME,
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD
    )


# =========================================================
# PDF / IMAGE MENUS
# =========================================================

async def show_pdf_tools(message):
    await message.reply_text(
        """
📄🔥 <b>PDF TOOLBOX UNLOCKED!</b>

━━━━━━━━━━━━━━━━━━━━

🛠️ Everything you need for your PDF.

🔄 Convert
📝 Extract text
🖼️ Create images
📦 Compress
🔗 Merge
✂️ Split
🔐 Protect
🔄 XPS conversion

💰 <b>Credit cost is shown before processing.</b>

👇 <b>Select a tool:</b>
""",
        parse_mode="HTML",
        reply_markup=PDF_KEYBOARD
    )


async def show_image_tools(message):
    await message.reply_text(
        """
🖼️✨ <b>IMAGE WORKSHOP</b>

━━━━━━━━━━━━━━━━━━━━

📸 Turn images into useful documents.

📄 JPG → PDF
📄 PNG → PDF
📦 Compress images

⚡ Simple • Fast • Clean

👇 <b>Select a tool:</b>
""",
        parse_mode="HTML",
        reply_markup=IMAGE_KEYBOARD
    )


# =========================================================
# ACCOUNT
# =========================================================

async def account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)

    await update.message.reply_text(
        f"""
👤✨ <b>YOUR DIGITAL ACCOUNT</b>

━━━━━━━━━━━━━━━━━━━━

🆔 User ID:
<code>{u['user_id']}</code>

🎁 Free Credits: <b>{u['credits']}</b>
💎 Premium Credits: <b>{u['premium_credits']}</b>

⭐ Plan: <b>{u['plan']}</b>
📊 Total Used: <b>{u['total_used']}</b>
👥 Referrals: <b>{u['referrals']}</b>

━━━━━━━━━━━━━━━━━━━━

🔥 Keep earning credits with
🎁 Daily Bonus
👥 Refer & Earn
🎟️ Redeem Codes
""",
        parse_mode="HTML"
    )


# =========================================================
# DAILY BONUS
# =========================================================

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)

    today = date.today().isoformat()

    if u["last_daily"] == today:
        await update.message.reply_text(
            """
⏰🎁 <b>DAILY BONUS ALREADY CLAIMED!</b>

━━━━━━━━━━━━━━━━━━━━

✨ You already collected today's reward.

🔄 Come back tomorrow for another bonus!
""",
            parse_mode="HTML"
        )
        return

    con = db()
    con.execute("""
        UPDATE users
        SET credits=credits+?, last_daily=?
        WHERE user_id=?
    """, (DAILY_BONUS, today, uid))
    con.commit()
    con.close()

    await update.message.reply_text(
        f"""
🎉🎁 <b>DAILY BONUS CLAIMED!</b>

━━━━━━━━━━━━━━━━━━━━

💰 Reward: <b>+{DAILY_BONUS} Credits</b>

🔥 Your balance has been updated.

🚀 Come back tomorrow and claim again!
""",
        parse_mode="HTML"
    )


# =========================================================
# REFERRAL
# =========================================================

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)

    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={uid}"

    await update.message.reply_text(
        f"""
👥🚀 <b>INVITE • EARN • REPEAT!</b>

━━━━━━━━━━━━━━━━━━━━

🎁 Invite friends and earn
<b>+{REFERRAL_BONUS} Credits</b> for each valid referral.

👥 Your Referrals: <b>{u['referrals']}</b>

🔗 <b>Your Personal Invite Link:</b>

<code>{link}</code>

📢 Share it with your friends and grow your balance! 🔥
""",
        parse_mode="HTML"
    )


# =========================================================
# REDEEM CODE
# =========================================================

async def redeem_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_redeem"] = True

    await update.message.reply_text(
        """
🎟️💎 <b>REDEEM CENTER</b>

━━━━━━━━━━━━━━━━━━━━

🎁 Have a promotional code?

🔐 Send your code below.

✨ Example:
<code>RAFIM20</code>

💰 If the code is valid, your Credits will be added instantly.
""",
        parse_mode="HTML"
    )


async def redeem_code(uid, code):
    code = code.strip().upper()

    con = db()
    cur = con.cursor()

    code_row = cur.execute("""
        SELECT * FROM redeem_codes
        WHERE code=? AND active=1
    """, (code,)).fetchone()

    if not code_row:
        con.close()
        return False, "❌ Invalid or inactive redeem code."

    if code_row["used_count"] >= code_row["max_uses"]:
        con.close()
        return False, "⛔ This redeem code has reached its maximum uses."

    already = cur.execute("""
        SELECT 1 FROM redemptions
        WHERE code=? AND user_id=?
    """, (code, uid)).fetchone()

    if already:
        con.close()
        return False, "⚠️ You have already used this code."

    cur.execute("""
        UPDATE users
        SET credits=credits+?
        WHERE user_id=?
    """, (code_row["credits"], uid))

    cur.execute("""
        UPDATE redeem_codes
        SET used_count=used_count+1
        WHERE code=?
    """, (code,))

    cur.execute("""
        INSERT INTO redemptions(code, user_id, credits, redeemed_at)
        VALUES (?, ?, ?, ?)
    """, (
        code,
        uid,
        code_row["credits"],
        datetime.utcnow().isoformat()
    ))

    con.commit()
    con.close()

    return True, (
        f"🎉 <b>REDEEM SUCCESSFUL!</b>\n\n"
        f"🎟️ Code: <code>{code}</code>\n"
        f"💰 Reward: <b>+{code_row['credits']} Credits</b>\n\n"
        f"🚀 Your balance has been updated!"
    )


# =========================================================
# ADMIN REDEEM
# =========================================================

async def create_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            """
👨‍💼🎟️ <b>Create Redeem Code</b>

Format:

<code>/createcode CODE CREDITS [USES]</code>

Example:

<code>/createcode RAFIM20 20 100</code>

🎁 This creates:
💰 20 Credits
👥 Maximum 100 uses
""",
            parse_mode="HTML"
        )
        return

    code = context.args[0].upper()

    try:
        credits = int(context.args[1])
        uses = int(context.args[2]) if len(context.args) >= 3 else 1

        if credits <= 0 or uses <= 0:
            raise ValueError

    except ValueError:
        await update.message.reply_text("❌ Credits and uses must be positive numbers.")
        return

    con = db()

    try:
        con.execute("""
            INSERT INTO redeem_codes
            (code, credits, max_uses, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            code,
            credits,
            uses,
            datetime.utcnow().isoformat()
        ))
        con.commit()

    except sqlite3.IntegrityError:
        con.close()
        await update.message.reply_text("⚠️ That code already exists.")
        return

    con.close()

    await update.message.reply_text(
        f"""
🎉🎟️ <b>REDEEM CODE CREATED!</b>

━━━━━━━━━━━━━━━━━━━━

🔐 Code:
<code>{code}</code>

💰 Reward: <b>{credits} Credits</b>
👥 Max Uses: <b>{uses}</b>
🟢 Status: <b>ACTIVE</b>

━━━━━━━━━━━━━━━━━━━━

📢 Give this code to your users.
""",
        parse_mode="HTML"
    )


async def redeem_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    con = db()
    rows = con.execute("""
        SELECT * FROM redeem_codes
        ORDER BY created_at DESC
        LIMIT 30
    """).fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("🎟️ No redeem codes yet.")
        return

    text = "🎟️ <b>REDEEM CODE MANAGER</b>\n\n"

    for r in rows:
        status = "🟢" if r["active"] else "🔴"
        text += (
            f"{status} <code>{r['code']}</code>\n"
            f"💰 {r['credits']} credits | "
            f"👥 {r['used_count']}/{r['max_uses']}\n\n"
        )

    await update.message.reply_text(text, parse_mode="HTML")


async def disable_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "Use: /disablecode RAFIM20"
        )
        return

    code = context.args[0].upper()

    con = db()
    cur = con.cursor()

    cur.execute("""
        UPDATE redeem_codes
        SET active=0
        WHERE code=?
    """, (code,))

    changed = cur.rowcount
    con.commit()
    con.close()

    if changed:
        await update.message.reply_text(
            f"🔴 Redeem code <code>{code}</code> disabled.",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ Code not found.")


# =========================================================
# SUPPORT / PREMIUM / HISTORY
# =========================================================

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 Contact @rafimhossen",
                url=f"https://t.me/{SUPPORT_USERNAME}"
            )
        ]
    ])

    await update.message.reply_text(
        """
🆘💙 <b>NEED HELP?</b>

━━━━━━━━━━━━━━━━━━━━

💬 Having a problem?
❓ Need help with a tool?
🐛 Found an error?

👨‍💻 Contact our support directly.

👇 Tap below to contact Support.
""",
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """
💎🚀 <b>PREMIUM ZONE</b>

━━━━━━━━━━━━━━━━━━━━

⚡ More Credits
📦 Higher file limits
🚀 Premium tools
🔥 Priority features

━━━━━━━━━━━━━━━━━━━━

💳 <b>Payment system is ready to connect.</b>

No payment secret is stored inside this code.

📌 Premium activation can currently be handled by Admin.
""",
        parse_mode="HTML"
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    con = db()

    rows = con.execute("""
        SELECT tool, cost, created_at
        FROM usage
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (update.effective_user.id,)).fetchall()

    con.close()

    if not rows:
        await update.message.reply_text(
            "📊✨ <b>No usage history yet.</b>\n\n🚀 Use a tool to see your activity here.",
            parse_mode="HTML"
        )
        return

    text = "📊✨ <b>RECENT ACTIVITY</b>\n\n"

    for r in rows:
        text += (
            f"🛠️ {r['tool']}\n"
            f"💰 Cost: {r['cost']} credits\n"
            f"🕐 {r['created_at'][:19]}\n\n"
        )

    await update.message.reply_text(text, parse_mode="HTML")


# =========================================================
# FILE PROCESSING
# =========================================================

def pdf_to_txt(src, dst):
    import fitz

    doc = fitz.open(src)

    with open(dst, "w", encoding="utf-8") as f:
        for page in doc:
            f.write(page.get_text())
            f.write("\n\n")

    doc.close()


def pdf_to_jpg(src, outdir):
    import fitz

    doc = fitz.open(src)
    outputs = []

    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        out = outdir / f"page_{i+1}.jpg"
        pix.save(out)
        outputs.append(out)

    doc.close()
    return outputs


def jpg_to_pdf(src, dst):
    from PIL import Image

    img = Image.open(src).convert("RGB")
    img.save(dst, "PDF")


def compress_image(src, dst):
    from PIL import Image

    img = Image.open(src).convert("RGB")
    img.save(dst, "JPEG", quality=55, optimize=True)


def compress_pdf(src, dst):
    result = subprocess.run(
        [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.5",
            "-dPDFSETTINGS=/ebook",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={dst}",
            str(src),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr or "Ghostscript compression failed.")


def pdf_to_xps(src, dst):
    result = subprocess.run(
        [
            "gs",
            "-sDEVICE=xpswrite",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            f"-sOutputFile={dst}",
            str(src),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr or "PDF to XPS failed.")


# =========================================================
# CALLBACKS
# =========================================================

TOOL_NAMES = {
    "pdf_txt": ("📝 PDF → TXT", 1),
    "pdf_jpg": ("🖼️ PDF → JPG", 2),
    "pdf_word": ("🔄 PDF → Word", 3),
    "compress": ("📦 Compress PDF", 2),
    "merge": ("🔗 Merge PDF", 2),
    "split": ("✂️ Split PDF", 2),
    "extract": ("📑 Extract Pages", 2),
    "pdf_xps": ("🔄 PDF → XPS", 3),
    "jpg_pdf": ("📸 JPG → PDF", 2),
    "png_pdf": ("🖼️ PNG → PDF", 2),
    "compress_image": ("📦 Compress Image", 1),
}


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "back_main":
        await query.message.reply_text(
            "🏠✨ <b>MAIN MENU</b>\n\n👇 Choose your next action:",
            parse_mode="HTML",
            reply_markup=MAIN_KEYBOARD
        )
        return

    if data in TOOL_NAMES:
        name, cost = TOOL_NAMES[data]

        context.user_data["selected_tool"] = data

        await query.message.reply_text(
            f"""
{name} 🚀

━━━━━━━━━━━━━━━━━━━━

💰 Cost: <b>{cost} Credits</b>

📎 Send your file now.

⚡ I'll process it and return the result.

⬅️ To cancel, use the Main Menu.
""",
            parse_mode="HTML"
        )


# =========================================================
# DOCUMENT HANDLER
# =========================================================

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tool = context.user_data.get("selected_tool")

    if not tool:
        await update.message.reply_text(
            "📎✨ First choose a tool from 📄 PDF Tools or 🖼️ Image Tools."
        )
        return

    name, cost = TOOL_NAMES.get(tool, ("Tool", 1))

    u = get_user(uid)

    available = u["credits"] + u["premium_credits"]

    if available < cost:
        await update.message.reply_text(
            f"""
⚠️💰 <b>NOT ENOUGH CREDITS</b>

━━━━━━━━━━━━━━━━━━━━

🛠️ Tool: {name}
💳 Required: <b>{cost}</b>
💰 Available: <b>{available}</b>

🎁 Claim Daily Bonus
👥 Refer & Earn
🎟️ Redeem a Code
💎 Get Premium
""",
            parse_mode="HTML"
        )
        return

    doc = update.message.document

    filename = doc.file_name or "document"
    suffix = Path(filename).suffix.lower()

    if tool.startswith("pdf_") or tool in {
        "compress", "merge", "split", "extract"
    }:
        if suffix != ".pdf":
            await update.message.reply_text(
                "❌📄 Please send a PDF file for this tool."
            )
            return

    if tool in {"jpg_pdf", "png_pdf", "compress_image"}:
        if suffix not in {".jpg", ".jpeg", ".png"}:
            await update.message.reply_text(
                "❌🖼️ Please send a JPG or PNG image."
            )
            return

    work = Path(tempfile.mkdtemp(dir=TMP_DIR))

    try:
        await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

        source = work / filename
        tg_file = await doc.get_file()

        await tg_file.download_to_drive(source)

        progress = await update.message.reply_text(
            f"""
⚡🔥 <b>PROCESSING STARTED</b>

📄 <b>{filename}</b>

🔄 <b>10%</b>
▰░░░░░░░░░

🧩 Reading your file...
""",
            parse_mode="HTML"
        )

        await progress.edit_text(
            f"""
⚙️ <b>PROCESSING YOUR FILE</b>

📄 <b>{filename}</b>

🔄 <b>30%</b>
▰▰▰░░░░░░░

🛠️ Preparing conversion...
""",
            parse_mode="HTML"
        )

        output_files = []

        if tool == "pdf_txt":
            out = work / f"{Path(filename).stem}.txt"
            pdf_to_txt(source, out)
            output_files = [out]

        elif tool == "pdf_jpg":
            output_files = pdf_to_jpg(source, work)

        elif tool == "compress":
            out = work / f"{Path(filename).stem}_compressed.pdf"
            compress_pdf(source, out)
            output_files = [out]

        elif tool == "pdf_xps":
            out = work / f"{Path(filename).stem}.xps"
            pdf_to_xps(source, out)
            output_files = [out]

        elif tool in {"jpg_pdf", "png_pdf"}:
            out = work / f"{Path(filename).stem}.pdf"
            jpg_to_pdf(source, out)
            output_files = [out]

        elif tool == "compress_image":
            out = work / f"{Path(filename).stem}_compressed.jpg"
            compress_image(source, out)
            output_files = [out]

        else:
            await progress.edit_text(
                "🚧 This tool is included in the menu and database system, but its processing module is not enabled in this starter build."
            )
            return

        await progress.edit_text(
            """
🚀 <b>FINALIZING...</b>

🔄 <b>90%</b>
▰▰▰▰▰▰▰▰▰░

📦 Preparing your download...
""",
            parse_mode="HTML"
        )

        if not spend_credit(uid, cost):
            await progress.edit_text(
                "⚠️ Credits changed while processing. Please try again."
            )
            return

        log_usage(uid, tool, cost)

        await progress.edit_text(
            f"""
🎉✅ <b>MISSION COMPLETE!</b>

━━━━━━━━━━━━━━━━━━━━

📄 Your file is ready!

🚀 Processing completed successfully.
💰 Credits Used: <b>{cost}</b>

👇 <b>Your download is below.</b>
""",
            parse_mode="HTML"
        )

        for output in output_files:
            if output.exists():
                with open(output, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        caption=f"🎉✨ <b>{output.name}</b>\n💎 Powered by {BOT_NAME}",
                        parse_mode="HTML"
                    )

    except Exception as e:
        await update.message.reply_text(
            f"""
❌⚠️ <b>PROCESSING FAILED</b>

Something went wrong while processing the file.

🛠️ Please try again with another file.

🆘 If the problem continues, contact:
@{SUPPORT_USERNAME}
""",
            parse_mode="HTML"
        )

    finally:
        shutil.rmtree(work, ignore_errors=True)
        context.user_data.pop("selected_tool", None)


# =========================================================
# TEXT ROUTER
# =========================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id

    ensure_user(update.effective_user)

    # Redeem input
    if context.user_data.get("waiting_redeem"):
        context.user_data["waiting_redeem"] = False

        ok, msg = redeem_code(uid, text)

        await update.message.reply_text(
            msg,
            parse_mode="HTML"
        )
        return

    if text == "📄 PDF Tools":
        await show_pdf_tools(update.message)

    elif text == "🖼️ Image Tools":
        await show_image_tools(update.message)

    elif text == "💎 Premium":
        await premium(update, context)

    elif text == "👤 My Account":
        await account(update, context)

    elif text == "🎁 Daily Bonus":
        await daily(update, context)

    elif text == "👥 Refer & Earn":
        await referral(update, context)

    elif text == "🎟️ Redeem Code":
        await redeem_prompt(update, context)

    elif text == "📊 History":
        await history(update, context)

    elif text == "🆘 Support":
        await support(update, context)

    else:
        await update.message.reply_text(
            """
🤖✨ <b>Rafim PDF Pro is ready!</b>

📄 Choose a PDF tool
🖼️ Choose an Image tool
🎁 Claim your bonus
🎟️ Redeem a code

👇 Use the menu below.
""",
            parse_mode="HTML",
            reply_markup=MAIN_KEYBOARD
        )


# =========================================================
# ADMIN
# =========================================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    con = db()

    users = con.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    usage = con.execute(
        "SELECT COUNT(*) AS c FROM usage"
    ).fetchone()["c"]

    con.close()

    await update.message.reply_text(
        f"""
👨‍💼🔥 <b>ADMIN CONTROL CENTER</b>

━━━━━━━━━━━━━━━━━━━━

👥 Users: <b>{users}</b>
📊 Tool Uses: <b>{usage}</b>

🎟️ Redeem commands:

➕ <code>/createcode RAFIM20 20 100</code>
📋 <code>/codes</code>
🔴 <code>/disablecode RAFIM20</code>

━━━━━━━━━━━━━━━━━━━━

💎 Admin ID:
<code>{ADMIN_ID}</code>
""",
        parse_mode="HTML"
    )


# =========================================================
# HEALTH SERVER FOR RENDER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Rafim PDF Pro is running 🚀"


@app.route("/health")
def health():
    return {"status": "ok"}


def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


# =========================================================
# MAIN
# =========================================================

def main():
    init_db()

    Thread(target=run_web, daemon=True).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))

    # Redeem admin commands
    application.add_handler(CommandHandler("createcode", create_redeem))
    application.add_handler(CommandHandler("codes", redeem_list))
    application.add_handler(CommandHandler("disablecode", disable_redeem))

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    application.add_handler(
        __import__(
            "telegram.ext"
        ).CallbackQueryHandler(callback_handler)
    )

    print("🚀 Rafim PDF Pro started!")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
