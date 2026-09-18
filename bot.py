import os
import sqlite3
import logging
from threading import Thread
from datetime import datetime, timedelta

from flask import Flask
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
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
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# তোমার Admin/User ID
ADMIN_ID = 8298133943

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

DB_FILE = "superbot.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# RENDER WEB SERVER
# =========================================================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Rafim Tools Bot is running!"


@web_app.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(
        host="0.0.0.0",
        port=port,
    )


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
            points INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            last_daily TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            note TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            points INTEGER,
            uses INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS redeemed (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY(user_id, code)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            points INTEGER,
            reason TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def ensure_user(user):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, first_name, points, referrals)
        VALUES (?, ?, ?, 0, 0)
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
    ))

    cur.execute("""
        UPDATE users
        SET username=?, first_name=?
        WHERE user_id=?
    """, (
        user.username or "",
        user.first_name or "",
        user.id,
    ))

    conn.commit()
    conn.close()


def add_points(user_id, amount, reason):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE users SET points = points + ? WHERE user_id=?",
        (amount, user_id),
    )

    cur.execute("""
        INSERT INTO history
        (user_id, points, reason, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        amount,
        reason,
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()


def get_points(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT points FROM users WHERE user_id=?",
        (user_id,),
    )

    row = cur.fetchone()
    conn.close()

    return row[0] if row else 0


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    keyboard = [
        ["🤖 AI CHAT", "📚 STUDY HUB"],
        ["⏰ SMART REMINDER", "📝 MY NOTES"],
        ["💎 MY POINTS", "🎁 DAILY REWARD"],
        ["👥 REFER & EARN", "🎟 REDEEM"],
        ["🏆 LEADERBOARD", "🛠 PRO TOOLS"],
        ["🎨 CREATOR", "👥 GROUP AI"],
        ["⚙️ SETTINGS", "❓ HELP"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def inline_menu():
    keyboard = [
        [
            InlineKeyboardButton("🤖 AI CHAT", callback_data="ai"),
            InlineKeyboardButton("📚 STUDY", callback_data="study"),
        ],
        [
            InlineKeyboardButton("💎 POINTS", callback_data="points"),
            InlineKeyboardButton("🎁 DAILY", callback_data="daily"),
        ],
        [
            InlineKeyboardButton("👥 REFER", callback_data="refer"),
            InlineKeyboardButton("🏆 LEADERBOARD", callback_data="leaderboard"),
        ],
        [
            InlineKeyboardButton("📝 NOTES", callback_data="notes"),
            InlineKeyboardButton("⏰ REMINDER", callback_data="reminder"),
        ],
        [
            InlineKeyboardButton("🛠 TOOLS", callback_data="tools"),
            InlineKeyboardButton("⚙️ SETTINGS", callback_data="settings"),
        ],
        [
            InlineKeyboardButton("❓ HELP", callback_data="help"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    # Referral
    if context.args:
        try:
            referrer_id = int(context.args[0])

            if referrer_id != user.id:
                conn = db()
                cur = conn.cursor()

                cur.execute(
                    "SELECT user_id FROM users WHERE user_id=?",
                    (referrer_id,),
                )

                referrer = cur.fetchone()

                if referrer:
                    cur.execute("""
                        UPDATE users
                        SET referrals = referrals + 1,
                            points = points + 10
                        WHERE user_id=?
                    """, (referrer_id,))

                    cur.execute("""
                        INSERT INTO history
                        (user_id, points, reason, created_at)
                        VALUES (?, 10, 'Referral bonus', ?)
                    """, (
                        referrer_id,
                        datetime.now().isoformat(),
                    ))

                    conn.commit()

                conn.close()

        except Exception:
            pass

    text = f"""
✨ <b>WELCOME TO RAFIM TOOLS BOT</b> ✨

🚀 তোমার জন্য একটি Smart Multi-Tool Bot!

━━━━━━━━━━━━━━━━━━
🤖 AI Chat
📚 Study Hub
⏰ Smart Reminder
📝 Notes
💎 Points System
🎁 Daily Reward
👥 Referral
🎟 Redeem
🏆 Leaderboard
🛠 Pro Tools
━━━━━━━━━━━━━━━━━━

👇 নিচের Menu থেকে একটি অপশন নির্বাচন করো।
"""

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )

    await update.message.reply_text(
        "🚀 <b>Quick Menu</b>",
        parse_mode="HTML",
        reply_markup=inline_menu(),
    )


# =========================================================
# POINTS
# =========================================================

async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    pts = get_points(user.id)

    await update.message.reply_text(
        f"""
💎 <b>MY POINTS</b>

⭐ Current Points: <b>{pts}</b>

💡 Points ব্যবহার করে ভবিষ্যতে Reward/Redeem সুবিধা নেওয়া যাবে।
""",
        parse_mode="HTML",
    )


# =========================================================
# DAILY REWARD
# =========================================================

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    today = datetime.now().strftime("%Y-%m-%d")

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT last_daily FROM users WHERE user_id=?",
        (user.id,),
    )

    row = cur.fetchone()

    if row and row[0] == today:
        conn.close()

        await update.message.reply_text(
            "⏳ আজকের Daily Reward তুমি ইতিমধ্যে নিয়ে ফেলেছ।\n\n"
            "🌅 আগামীকাল আবার চেষ্টা করো!"
        )
        return

    cur.execute(
        "UPDATE users SET last_daily=? WHERE user_id=?",
        (today, user.id),
    )

    conn.commit()
    conn.close()

    add_points(
        user.id,
        5,
        "Daily reward",
    )

    await update.message.reply_text(
        "🎁 <b>Daily Reward Received!</b>\n\n"
        "⭐ তুমি পেয়েছো <b>+5 Points</b>!",
        parse_mode="HTML",
    )


# =========================================================
# REFERRAL
# =========================================================

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    bot = await context.bot.get_me()

    link = f"https://t.me/{bot.username}?start={user.id}"

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT referrals FROM users WHERE user_id=?",
        (user.id,),
    )

    row = cur.fetchone()
    referrals = row[0] if row else 0

    conn.close()

    await update.message.reply_text(
        f"""
👥 <b>REFER & EARN</b>

🔗 তোমার Referral Link:

<code>{link}</code>

👤 Successful Referrals: <b>{referrals}</b>

🎁 প্রতি successful referral-এ referrer পাবে <b>+10 Points</b>।
""",
        parse_mode="HTML",
    )


# =========================================================
# NOTES
# =========================================================

async def note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    if not context.args:
        await update.message.reply_text(
            "📝 ব্যবহার:\n\n"
            "<code>/note আগামীকাল ১০টায় পড়তে হবে</code>",
            parse_mode="HTML",
        )
        return

    note_text = " ".join(context.args)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO notes
        (user_id, note, created_at)
        VALUES (?, ?, ?)
    """, (
        user.id,
        note_text,
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ Note saved successfully!"
    )


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT note, created_at
        FROM notes
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (user.id,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "📝 তোমার কোনো Note নেই।"
        )
        return

    text = "📝 <b>MY NOTES</b>\n\n"

    for i, row in enumerate(rows, 1):
        text += f"{i}. {row[0]}\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# =========================================================
# TASKS
# =========================================================

async def task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    if not context.args:
        await update.message.reply_text(
            "ব্যবহার:\n/task আজ Mathematics পড়বো"
        )
        return

    task_text = " ".join(context.args)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tasks
        (user_id, task, done, created_at)
        VALUES (?, ?, 0, ?)
    """, (
        user.id,
        task_text,
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ Task added!"
    )


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, task
        FROM tasks
        WHERE user_id=? AND done=0
        ORDER BY id DESC
        LIMIT 10
    """, (user.id,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "🎉 কোনো pending task নেই!"
        )
        return

    text = "📋 <b>MY TASKS</b>\n\n"

    for task_id, task_text in rows:
        text += f"#{task_id} — {task_text}\n"

    text += "\nসম্পন্ন করতে:\n<code>/taskdone ID</code>"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


async def taskdone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    if not context.args:
        await update.message.reply_text(
            "ব্যবহার: /taskdone 1"
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Task ID সঠিক নয়।"
        )
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tasks
        SET done=1
        WHERE id=? AND user_id=?
    """, (
        task_id,
        user.id,
    ))

    changed = cur.rowcount

    conn.commit()
    conn.close()

    if changed:
        await update.message.reply_text(
            "🎉 Task completed!"
        )
    else:
        await update.message.reply_text(
            "❌ Task পাওয়া যায়নি।"
        )


# =========================================================
# REMINDER
# =========================================================

async def reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job

    await context.bot.send_message(
        chat_id=job.chat_id,
        text=f"⏰ <b>REMINDER</b>\n\n🔔 {job.data}",
        parse_mode="HTML",
    )


async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    if len(context.args) < 2:
        await update.message.reply_text(
            "⏰ ব্যবহার:\n\n"
            "<code>/remind 10m পানি খাও</code>\n"
            "<code>/remind 1h পড়তে বসো</code>",
            parse_mode="HTML",
        )
        return

    duration = context.args[0]
    message = " ".join(context.args[1:])

    seconds = None

    try:
        if duration.endswith("m"):
            seconds = int(duration[:-1]) * 60

        elif duration.endswith("h"):
            seconds = int(duration[:-1]) * 3600

        elif duration.endswith("s"):
            seconds = int(duration[:-1])

    except ValueError:
        pass

    if not seconds or seconds <= 0:
        await update.message.reply_text(
            "❌ সময় সঠিক নয়। যেমন: 10m অথবা 1h"
        )
        return

    context.job_queue.run_once(
        reminder_callback,
        when=seconds,
        chat_id=update.effective_chat.id,
        data=message,
        name=f"reminder_{user.id}_{datetime.now().timestamp()}",
    )

    await update.message.reply_text(
        f"✅ Reminder সেট হয়েছে!\n\n"
        f"⏰ সময়: {duration}\n"
        f"📝 {message}"
    )


# =========================================================
# REDEEM
# =========================================================

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    if not context.args:
        await update.message.reply_text(
            "🎟 ব্যবহার:\n/redeem CODE"
        )
        return

    code = context.args[0].upper()

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT points, uses FROM redeem_codes WHERE code=?",
        (code,),
    )

    row = cur.fetchone()

    if not row:
        conn.close()
        await update.message.reply_text(
            "❌ Invalid redeem code."
        )
        return

    reward, uses = row

    cur.execute(
        "SELECT 1 FROM redeemed WHERE user_id=? AND code=?",
        (user.id, code),
    )

    if cur.fetchone():
        conn.close()
        await update.message.reply_text(
            "⚠️ তুমি এই code আগেই ব্যবহার করেছ।"
        )
        return

    if uses <= 0:
        conn.close()
        await update.message.reply_text(
            "❌ এই code-এর ব্যবহার শেষ।"
        )
        return

    cur.execute(
        "UPDATE redeem_codes SET uses=uses-1 WHERE code=?",
        (code,),
    )

    cur.execute(
        "INSERT INTO redeemed(user_id, code) VALUES (?, ?)",
        (user.id, code),
    )

    conn.commit()
    conn.close()

    add_points(
        user.id,
        reward,
        f"Redeem: {code}",
    )

    await update.message.reply_text(
        f"🎉 <b>Redeem Successful!</b>\n\n"
        f"💎 +{reward} Points",
        parse_mode="HTML",
    )


# =========================================================
# ADMIN ADD CODE
# =========================================================

async def addcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ Admin only."
        )
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "ব্যবহার:\n"
            "/addcode CODE POINTS USES\n\n"
            "উদাহরণ:\n"
            "/addcode BONUS100 100 10"
        )
        return

    code = context.args[0].upper()

    try:
        reward = int(context.args[1])
        uses = int(context.args[2])
    except ValueError:
        await update.message.reply_text(
            "❌ Points এবং uses সংখ্যা হতে হবে।"
        )
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO redeem_codes
        (code, points, uses)
        VALUES (?, ?, ?)
    """, (
        code,
        reward,
        uses,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Redeem code তৈরি হয়েছে!\n\n"
        f"🎟 Code: {code}\n"
        f"💎 Points: {reward}\n"
        f"👥 Uses: {uses}"
    )


# =========================================================
# LEADERBOARD
# =========================================================

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT first_name, username, points
        FROM users
        ORDER BY points DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "🏆 Leaderboard এখনো খালি।"
        )
        return

    text = "🏆 <b>LEADERBOARD</b>\n\n"

    for i, (name, username, pts) in enumerate(rows, 1):
        display = name or username or "User"
        text += f"{i}. {display} — 💎 {pts}\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# =========================================================
# HISTORY
# =========================================================

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT points, reason
        FROM history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (user.id,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "📊 কোনো point history নেই।"
        )
        return

    text = "📊 <b>POINT HISTORY</b>\n\n"

    for pts, reason in rows:
        sign = "+" if pts >= 0 else ""
        text += f"{sign}{pts} — {reason}\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# =========================================================
# FEEDBACK
# =========================================================

async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    if not context.args:
        await update.message.reply_text(
            "💬 ব্যবহার:\n"
            "/feedback তোমার feedback এখানে লিখো"
        )
        return

    message = " ".join(context.args)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO feedback
        (user_id, message, created_at)
        VALUES (?, ?, ?)
    """, (
        user.id,
        message,
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🙏 ধন্যবাদ! তোমার feedback সংরক্ষণ করা হয়েছে।"
    )


# =========================================================
# ID
# =========================================================

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 তোমার Telegram ID:\n\n"
        f"<code>{update.effective_user.id}</code>",
        parse_mode="HTML",
    )


# =========================================================
# HELP
# =========================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
❓ <b>HELP CENTER</b>

🚀 Available Commands:

/start — Bot শুরু
/points — Points দেখুন
/daily — Daily reward
/refer — Referral link
/note — Note তৈরি
/notes — Notes দেখুন
/task — Task তৈরি
/tasks — Tasks দেখুন
/taskdone — Task complete
/remind — Reminder
/redeem — Redeem code
/leaderboard — Ranking
/history — Point history
/id — Telegram ID
/feedback — Feedback

🤖 AI CHAT ও STUDY HUB-এর জন্য Menu ব্যবহার করুন।
"""

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ADMIN
# =========================================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ Admin only."
        )
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT SUM(points) FROM users")
    total_points = cur.fetchone()[0] or 0

    conn.close()

    await update.message.reply_text(
        f"""
👑 <b>ADMIN PANEL</b>

👥 Users: {users}
💎 Total Points: {total_points}

🎟 Create Redeem Code:

<code>/addcode CODE POINTS USES</code>

Example:
<code>/addcode BONUS100 100 10</code>
""",
        parse_mode="HTML",
    )


# =========================================================
# MENU HANDLER
# =========================================================

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user

    ensure_user(user)

    if text == "💎 MY POINTS":
        await points(update, context)

    elif text == "🎁 DAILY REWARD":
        await daily(update, context)

    elif text == "👥 REFER & EARN":
        await refer(update, context)

    elif text == "📝 MY NOTES":
        await notes(update, context)

    elif text == "⏰ SMART REMINDER":
        await update.message.reply_text(
            "⏰ Reminder ব্যবহার:\n\n"
            "/remind 10m পানি খাও\n"
            "/remind 1h পড়তে বসো"
        )

    elif text == "🏆 LEADERBOARD":
        await leaderboard(update, context)

    elif text == "🎨 CREATOR":
        await update.message.reply_text(
            "🎨 <b>Creator</b>\n\n"
            "Rafim Tools Bot\n"
            "Built with Python + Telegram Bot API.",
            parse_mode="HTML",
        )

    elif text == "⚙️ SETTINGS":
        await update.message.reply_text(
            "⚙️ Settings\n\n"
            "তোমার bot settings এখানে থাকবে।"
        )

    elif text == "❓ HELP":
        await help_command(update, context)

    elif text == "🛠 PRO TOOLS":
        await update.message.reply_text(
            "🛠 <b>PRO TOOLS</b>\n\n"
            "Calculator\n"
            "Notes\n"
            "Tasks\n"
            "Reminder\n"
            "Points",
            parse_mode="HTML",
        )

    elif text == "📚 STUDY HUB":
        await update.message.reply_text(
            "📚 <b>STUDY HUB</b>\n\n"
            "তোমার পড়াশোনার প্রশ্ন এখানে পাঠাতে পারো।\n\n"
            "🤖 AI integration পরে যোগ করা যাবে।",
            parse_mode="HTML",
        )

    elif text == "🤖 AI CHAT":
        await update.message.reply_text(
            "🤖 <b>AI CHAT</b>\n\n"
            "AI provider এখনো সংযুক্ত করা হয়নি।\n"
            "Bot-এর বাকি সব core features চালু আছে।",
            parse_mode="HTML",
        )

    elif text == "🎟 REDEEM":
        await update.message.reply_text(
            "🎟 ব্যবহার:\n\n"
            "/redeem CODE"
        )

    elif text == "👥 GROUP AI":
        await update.message.reply_text(
            "👥 Group AI mode প্রস্তুত করা হয়েছে।"
        )


# =========================================================
# INLINE BUTTON HANDLER
# =========================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    user = query.from_user
    ensure_user(user)

    if query.data == "points":
        pts = get_points(user.id)

        await query.message.reply_text(
            f"💎 তোমার Points: {pts}"
        )

    elif query.data == "daily":
        today = datetime.now().strftime("%Y-%m-%d")

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT last_daily FROM users WHERE user_id=?",
            (user.id,),
        )

        row = cur.fetchone()

        if row and row[0] == today:
            conn.close()

            await query.message.reply_text(
                "⏳ আজকের Daily Reward নেওয়া হয়েছে।"
            )
            return

        cur.execute(
            "UPDATE users SET last_daily=? WHERE user_id=?",
            (today, user.id),
        )

        conn.commit()
        conn.close()

        add_points(
            user.id,
            5,
            "Daily reward",
        )

        await query.message.reply_text(
            "🎁 +5 Points received!"
        )

    elif query.data == "refer":
        bot = await context.bot.get_me()

        link = f"https://t.me/{bot.username}?start={user.id}"

        await query.message.reply_text(
            f"👥 তোমার Referral Link:\n\n"
            f"<code>{link}</code>",
            parse_mode="HTML",
        )

    elif query.data == "notes":
        await notes_from_query(query, user.id)

    elif query.data == "reminder":
        await query.message.reply_text(
            "/remind 10m পানি খাও"
        )

    elif query.data == "leaderboard":
        await leaderboard_from_query(query)

    elif query.data == "study":
        await query.message.reply_text(
            "📚 Study Hub প্রস্তুত।"
        )

    elif query.data == "ai":
        await query.message.reply_text(
            "🤖 AI Chat প্রস্তুত। AI provider সংযুক্ত করা হলে এখানে AI response আসবে।"
        )

    elif query.data == "tools":
        await query.message.reply_text(
            "🛠 Tools: Notes, Tasks, Reminder, Points."
        )

    elif query.data == "settings":
        await query.message.reply_text(
            "⚙️ Settings"
        )

    elif query.data == "help":
        await query.message.reply_text(
            "/help"
        )


async def notes_from_query(query, user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT note
        FROM notes
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (user_id,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await query.message.reply_text(
            "📝 কোনো Note নেই।"
        )
        return

    text = "📝 <b>MY NOTES</b>\n\n"

    for i, row in enumerate(rows, 1):
        text += f"{i}. {row[0]}\n"

    await query.message.reply_text(
        text,
        parse_mode="HTML",
    )


async def leaderboard_from_query(query):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT first_name, username, points
        FROM users
        ORDER BY points DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    conn.close()

    text = "🏆 <b>LEADERBOARD</b>\n\n"

    for i, (name, username, pts) in enumerate(rows, 1):
        display = name or username or "User"
        text += f"{i}. {display} — 💎 {pts}\n"

    await query.message.reply_text(
        text,
        parse_mode="HTML",
    )


# =========================================================
# GROUP AI / NORMAL TEXT
# =========================================================

async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    message = update.message.text

    # শুধু mention/reply করলে response
    bot = await context.bot.get_me()

    if f"@{bot.username}" not in message:
        return

    await update.message.reply_text(
        "🤖 Group AI mode active.\n\n"
        "AI provider এখনো সংযুক্ত করা হয়নি।"
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():
    init_db()

    # Render HTTP server
    web_thread = Thread(
        target=run_web,
        daemon=True,
    )

    web_thread.start()

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
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("points", points)
    )

    application.add_handler(
        CommandHandler("daily", daily)
    )

    application.add_handler(
        CommandHandler("refer", refer)
    )

    application.add_handler(
        CommandHandler("note", note)
    )

    application.add_handler(
        CommandHandler("notes", notes)
    )

    application.add_handler(
        CommandHandler("task", task)
    )

    application.add_handler(
        CommandHandler("tasks", tasks)
    )

    application.add_handler(
        CommandHandler("taskdone", taskdone)
    )

    application.add_handler(
        CommandHandler("remind", remind)
    )

    application.add_handler(
        CommandHandler("redeem", redeem)
    )

    application.add_handler(
        CommandHandler("addcode", addcode)
    )

    application.add_handler(
        CommandHandler("leaderboard", leaderboard)
    )

    application.add_handler(
        CommandHandler("history", history)
    )

    application.add_handler(
        CommandHandler("feedback", feedback)
    )

    application.add_handler(
        CommandHandler("id", my_id)
    )

    application.add_handler(
        CommandHandler("admin", admin)
    )

    # Inline buttons
    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    # Reply keyboard
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            menu_handler,
        )
    )

    # Group mention
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.ChatType.GROUPS,
            group_message,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("Rafim Tools Bot started successfully!")

    # Telegram polling
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
