import os
import sqlite3
import logging
import secrets
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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
# SUPER BOT — FINAL
# =========================================================

# 👉 এখানে তোমার নতুন BotFather TOKEN বসাবে
BOT_TOKEN = "8809150454:AAFCbJ-fAk3wIz6eWnfFNogRFm-0PsWMTQA"

# 👉 তোমার Admin/User ID — আগে থেকেই সেট করা
ADMIN_ID = 8298133943

DB_NAME = "superbot.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        username TEXT,
        joined TEXT,
        messages INTEGER DEFAULT 0,
        points INTEGER DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        referred_by INTEGER DEFAULT 0,
        streak INTEGER DEFAULT 0,
        last_daily TEXT DEFAULT '',
        last_active TEXT DEFAULT ''
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        created TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        done INTEGER DEFAULT 0,
        created TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        minutes INTEGER,
        created TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY,
        points INTEGER,
        uses INTEGER DEFAULT 1,
        used INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS redeemed (
        user_id INTEGER,
        code TEXT,
        UNIQUE(user_id, code)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        reason TEXT,
        created TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS achievements (
        user_id INTEGER,
        achievement TEXT,
        UNIQUE(user_id, achievement)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        created TEXT
    )
    """)

    con.commit()
    con.close()


# =========================================================
# USER SYSTEM
# =========================================================

def register_user(user, referral_id=0):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    )

    exists = cur.fetchone()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not exists:
        cur.execute("""
        INSERT INTO users
        (user_id,name,username,joined,messages,points,referrals,
        referred_by,streak,last_daily,last_active)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            user.id,
            user.first_name or "",
            user.username or "",
            now,
            0,
            0,
            0,
            referral_id if referral_id else 0,
            0,
            "",
            now
        ))

        # Referral reward
        if referral_id and referral_id != user.id:
            cur.execute("""
            UPDATE users
            SET points=points+50,
                referrals=referrals+1
            WHERE user_id=?
            """, (referral_id,))

            cur.execute("""
            INSERT INTO history(user_id,amount,reason,created)
            VALUES(?,?,?,?)
            """, (
                referral_id,
                50,
                "Successful referral",
                now
            ))

    else:
        cur.execute("""
        UPDATE users
        SET messages=messages+1,
            last_active=?
        WHERE user_id=?
        """, (now, user.id))

    con.commit()
    con.close()


def get_user(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()

    con.close()

    return result


def add_points(user_id, amount, reason):
    con = db()
    cur = con.cursor()

    cur.execute("""
    UPDATE users
    SET points=points+?
    WHERE user_id=?
    """, (amount, user_id))

    cur.execute("""
    INSERT INTO history(user_id,amount,reason,created)
    VALUES(?,?,?,?)
    """, (
        user_id,
        amount,
        reason,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    con.commit()
    con.close()


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    keyboard = [
        [
            InlineKeyboardButton("🤖 AI CHAT", callback_data="ai"),
            InlineKeyboardButton("📚 STUDY", callback_data="study"),
        ],
        [
            InlineKeyboardButton("⏰ REMINDER", callback_data="reminder"),
            InlineKeyboardButton("📝 NOTES", callback_data="notes"),
        ],
        [
            InlineKeyboardButton("✅ TASKS", callback_data="tasks"),
            InlineKeyboardButton("🎁 REDEEM", callback_data="redeem"),
        ],
        [
            InlineKeyboardButton("💰 MY POINTS", callback_data="points"),
            InlineKeyboardButton("🎁 DAILY", callback_data="daily"),
        ],
        [
            InlineKeyboardButton("👥 REFER", callback_data="refer"),
            InlineKeyboardButton("🏆 LEADERBOARD", callback_data="leaderboard"),
        ],
        [
            InlineKeyboardButton("🏅 ACHIEVEMENTS", callback_data="achievements"),
            InlineKeyboardButton("🛠 TOOLS", callback_data="tools"),
        ],
        [
            InlineKeyboardButton("🎨 CREATOR", callback_data="creator"),
            InlineKeyboardButton("👥 GROUP AI", callback_data="groupai"),
        ],
        [
            InlineKeyboardButton("⚙️ SETTINGS", callback_data="settings"),
            InlineKeyboardButton("❓ HELP", callback_data="help"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    referral_id = 0

    if context.args:

        arg = context.args[0]

        if arg.startswith("ref_"):
            try:
                referral_id = int(arg.replace("ref_", ""))
            except:
                referral_id = 0

    register_user(user, referral_id)

    text = f"""
╔══════════════════════╗
       🤖 SUPER BOT
╚══════════════════════╝

👋 Hello, {user.first_name}!

🚀 Welcome to your all-in-one Super Bot.

✨ এখানে তুমি পাবে:

🤖 AI Assistant
📚 Study Helper
⏰ Smart Reminder
📝 Personal Notes
✅ Task Manager
🎁 Redeem Rewards
💰 Points System
👥 Referral System
🎁 Daily Reward
🏆 Leaderboard
🏅 Achievements
🎨 Creator Tools
👥 Group AI
🛠 Useful Tools
⚙️ Settings

👇 নিচের Menu থেকে একটি অপশন নির্বাচন করো।
"""

    await update.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# =========================================================
# CALLBACK MENU
# =========================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "ai":

        await query.message.reply_text(
            "🤖 AI CHAT\n\n"
            "আমাকে যেকোনো প্রশ্ন লিখে পাঠাও।\n\n"
            "উদাহরণ:\n"
            "• Python কী?\n"
            "• একটা গল্প লিখো\n"
            "• Math বুঝিয়ে দাও\n\n"
            "ℹ️ AI API যুক্ত করলে এখানে real AI response চালু করা যাবে।"
        )

    elif query.data == "study":

        await query.message.reply_text(
            "📚 STUDY MODE\n\n"
            "আমি তোমার পড়াশোনার কাজে সাহায্য করতে পারি।\n\n"
            "উদাহরণ:\n"
            "/study Photosynthesis\n"
            "/study Newton's laws"
        )

    elif query.data == "reminder":

        await query.message.reply_text(
            "⏰ REMINDER\n\n"
            "ব্যবহার:\n"
            "/remind 10m পানি খাও\n"
            "/remind 1h পড়তে বসো\n\n"
            "m = minute\n"
            "h = hour"
        )

    elif query.data == "notes":

        await query.message.reply_text(
            "📝 NOTES\n\n"
            "/note তোমার লেখা\n"
            "/notes\n\n"
            "নোট মুছতে চাইলে পরে ID ব্যবহার করা যাবে।"
        )

    elif query.data == "tasks":

        await query.message.reply_text(
            "✅ TASK MANAGER\n\n"
            "/task Homework করা\n"
            "/tasks\n"
            "/taskdone ID"
        )

    elif query.data == "redeem":

        await query.message.reply_text(
            "🎁 REDEEM\n\n"
            "Admin থেকে পাওয়া code ব্যবহার করো:\n\n"
            "/redeem CODE"
        )

    elif query.data == "points":

        user = get_user(user_id)

        points = user[5] if user else 0

        await query.message.reply_text(
            f"💰 YOUR POINTS\n\n"
            f"⭐ Points: {points}\n\n"
            f"Points সংগ্রহ করতে Daily Reward ও Referral ব্যবহার করো।"
        )

    elif query.data == "daily":

        await daily(update, context, from_button=True)

    elif query.data == "refer":

        me = await context.bot.get_me()

        link = f"https://t.me/{me.username}?start=ref_{user_id}"

        await query.message.reply_text(
            "👥 REFERRAL SYSTEM\n\n"
            "তোমার Referral Link:\n\n"
            f"{link}\n\n"
            "🎁 Valid referral = 50 points"
        )

    elif query.data == "leaderboard":

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT name, points
        FROM users
        ORDER BY points DESC
        LIMIT 10
        """)

        rows = cur.fetchall()
        con.close()

        text = "🏆 LEADERBOARD\n\n"

        if not rows:
            text += "এখনো কেউ নেই।"

        for i, row in enumerate(rows, 1):
            text += f"{i}. {row[0]} — ⭐ {row[1]}\n"

        await query.message.reply_text(text)

    elif query.data == "achievements":

        con = db()
        cur = con.cursor()

        cur.execute("""
        SELECT achievement
        FROM achievements
        WHERE user_id=?
        """, (user_id,))

        rows = cur.fetchall()
        con.close()

        if not rows:
            text = "🏅 এখনো কোনো achievement unlock হয়নি।"
        else:
            text = "🏅 YOUR ACHIEVEMENTS\n\n"

            for row in rows:
                text += f"🏆 {row[0]}\n"

        await query.message.reply_text(text)

    elif query.data == "tools":

        await query.message.reply_text(
            "🛠 TOOLS\n\n"
            "🔹 /id — তোমার Telegram ID\n"
            "🔹 /history — Points history\n"
            "🔹 /feedback — Feedback পাঠাও\n"
            "🔹 /stats — নিজের stats"
        )

    elif query.data == "creator":

        await query.message.reply_text(
            "🎨 CREATOR TOOLS\n\n"
            "এখানে ভবিষ্যতে থাকবে:\n"
            "🖼 Caption Generator\n"
            "✍️ Bio Generator\n"
            "📢 Post Generator\n"
            "🎬 Video Idea Generator\n"
            "📝 Hashtag Generator"
        )

    elif query.data == "groupai":

        await query.message.reply_text(
            "👥 GROUP AI\n\n"
            "Group-এ আমাকে mention করলে AI assistant হিসেবে ব্যবহার করা যাবে।\n\n"
            "উদাহরণ:\n"
            "@YourBot Python কী?"
        )

    elif query.data == "settings":

        await query.message.reply_text(
            "⚙️ SETTINGS\n\n"
            "Settings system এখানে রাখা হয়েছে।\n"
            "ভবিষ্যতে language, notifications ও theme যোগ করা যাবে।"
        )

    elif query.data == "help":

        await query.message.reply_text(
            "❓ SUPER BOT HELP\n\n"
            "/start — Main Menu\n"
            "/daily — Daily reward\n"
            "/redeem CODE — Redeem\n"
            "/note TEXT — Save note\n"
            "/notes — Show notes\n"
            "/task TEXT — Add task\n"
            "/tasks — Show tasks\n"
            "/taskdone ID — Complete task\n"
            "/remind 10m TEXT — Reminder\n"
            "/points — Points\n"
            "/history — History\n"
            "/refer — Referral\n"
            "/leaderboard — Leaderboard\n"
            "/id — Telegram ID\n"
            "/feedback TEXT — Feedback"
        )


# =========================================================
# DAILY REWARD
# =========================================================

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button=False):

    user_id = update.effective_user.id

    user = get_user(user_id)

    if not user:
        return

    today = datetime.now().strftime("%Y-%m-%d")

    if user[9] == today:

        text = "🎁 আজকের Daily Reward তুমি ইতিমধ্যে নিয়েছো।"

    else:

        streak = user[7] + 1

        reward = 20 + min(streak * 5, 50)

        con = db()
        cur = con.cursor()

        cur.execute("""
        UPDATE users
        SET points=points+?,
            streak=?,
            last_daily=?
        WHERE user_id=?
        """, (
            reward,
            streak,
            today,
            user_id
        ))

        cur.execute("""
        INSERT INTO history(user_id,amount,reason,created)
        VALUES(?,?,?,?)
        """, (
            user_id,
            reward,
            "Daily reward",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        con.commit()
        con.close()

        text = (
            "🎁 DAILY REWARD\n\n"
            f"⭐ +{reward} Points\n"
            f"🔥 Streak: {streak}\n\n"
            "আগামীকাল আবার Daily Reward নিতে পারো।"
        )

    if from_button:

        await update.callback_query.message.reply_text(text)

    else:

        await update.message.reply_text(text)


# =========================================================
# POINTS
# =========================================================

async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):

    register_user(update.effective_user)

    user = get_user(update.effective_user.id)

    await update.message.reply_text(
        f"💰 YOUR POINTS\n\n"
        f"⭐ Points: {user[5]}\n"
        f"👥 Referrals: {user[6]}\n"
        f"🔥 Streak: {user[7]}"
    )


# =========================================================
# REFERRAL
# =========================================================

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    me = await context.bot.get_me()

    link = f"https://t.me/{me.username}?start=ref_{user_id}"

    await update.message.reply_text(
        "👥 YOUR REFERRAL LINK\n\n"
        f"{link}\n\n"
        "🎁 প্রতি valid referral-এ 50 points পাওয়া যাবে।"
    )


# =========================================================
# REDEEM
# =========================================================

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "🎁 ব্যবহার:\n/redeem CODE"
        )
        return

    code = context.args[0].upper()

    user_id = update.effective_user.id

    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT points, uses, used FROM redeem_codes WHERE code=?",
        (code,)
    )

    row = cur.fetchone()

    if not row:

        con.close()

        await update.message.reply_text(
            "❌ এই redeem code পাওয়া যায়নি।"
        )

        return

    points_value, uses, used = row

    if used >= uses:

        con.close()

        await update.message.reply_text(
            "❌ এই code-এর সব ব্যবহার শেষ।"
        )

        return

    cur.execute("""
    SELECT 1
    FROM redeemed
    WHERE user_id=? AND code=?
    """, (
        user_id,
        code
    ))

    if cur.fetchone():

        con.close()

        await update.message.reply_text(
            "❌ তুমি এই code আগে ব্যবহার করেছো।"
        )

        return

    cur.execute("""
    INSERT INTO redeemed(user_id,code)
    VALUES(?,?)
    """, (
        user_id,
        code
    ))

    cur.execute("""
    UPDATE redeem_codes
    SET used=used+1
    WHERE code=?
    """, (code,))

    cur.execute("""
    UPDATE users
    SET points=points+?
    WHERE user_id=?
    """, (
        points_value,
        user_id
    ))

    cur.execute("""
    INSERT INTO history(user_id,amount,reason,created)
    VALUES(?,?,?,?)
    """, (
        user_id,
        points_value,
        f"Redeemed {code}",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    con.commit()
    con.close()

    await update.message.reply_text(
        f"🎉 Redeem Successful!\n\n"
        f"🎁 Code: {code}\n"
        f"⭐ +{points_value} Points"
    )


# =========================================================
# ADMIN ADD CODE
# =========================================================

async def addcode(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text("⛔ Admin only.")

        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "/addcode CODE POINTS [USES]\n\n"
            "Example:\n"
            "/addcode WELCOME100 100 10"
        )

        return

    code = context.args[0].upper()

    try:
        point_value = int(context.args[1])
        uses = int(context.args[2]) if len(context.args) >= 3 else 1
    except:

        await update.message.reply_text(
            "❌ Points/uses অবশ্যই number হতে হবে।"
        )

        return

    con = db()
    cur = con.cursor()

    try:

        cur.execute("""
        INSERT INTO redeem_codes(code,points,uses,used)
        VALUES(?,?,?,0)
        """, (
            code,
            point_value,
            uses
        ))

        con.commit()

        await update.message.reply_text(
            f"✅ Redeem code তৈরি হয়েছে!\n\n"
            f"Code: {code}\n"
            f"Points: {point_value}\n"
            f"Uses: {uses}"
        )

    except sqlite3.IntegrityError:

        await update.message.reply_text(
            "❌ এই code আগে থেকেই আছে।"
        )

    finally:

        con.close()


# =========================================================
# NOTES
# =========================================================

async def note(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "/note তোমার note লিখো"
        )

        return

    text_value = " ".join(context.args)

    con = db()
    cur = con.cursor()

    cur.execute("""
    INSERT INTO notes(user_id,text,created)
    VALUES(?,?,?)
    """, (
        update.effective_user.id,
        text_value,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    con.commit()
    con.close()

    await update.message.reply_text(
        "📝 Note saved successfully!"
    )


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):

    con = db()
    cur = con.cursor()

    cur.execute("""
    SELECT id,text,created
    FROM notes
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 20
    """, (
        update.effective_user.id,
    ))

    rows = cur.fetchall()

    con.close()

    if not rows:

        await update.message.reply_text(
            "📝 তোমার কোনো note নেই।"
        )

        return

    text = "📝 YOUR NOTES\n\n"

    for row in rows:

        text += f"#{row[0]} — {row[1]}\n"

    await update.message.reply_text(text)


# =========================================================
# TASKS
# =========================================================

async def task(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "/task তোমার task লিখো"
        )

        return

    task_text = " ".join(context.args)

    con = db()
    cur = con.cursor()

    cur.execute("""
    INSERT INTO tasks(user_id,text,done,created)
    VALUES(?,?,0,?)
    """, (
        update.effective_user.id,
        task_text,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    con.commit()
    con.close()

    await update.message.reply_text(
        "✅ Task added!"
    )


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):

    con = db()
    cur = con.cursor()

    cur.execute("""
    SELECT id,text,done
    FROM tasks
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 30
    """, (
        update.effective_user.id,
    ))

    rows = cur.fetchall()

    con.close()

    if not rows:

        await update.message.reply_text(
            "✅ কোনো task নেই।"
        )

        return

    text = "✅ YOUR TASKS\n\n"

    for row in rows:

        status = "✅" if row[2] else "⏳"

        text += f"{status} #{row[0]} — {row[1]}\n"

    await update.message.reply_text(text)


async def taskdone(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "/taskdone ID"
        )

        return

    try:
        task_id = int(context.args[0])
    except:

        await update.message.reply_text(
            "❌ ID number হতে হবে।"
        )

        return

    con = db()
    cur = con.cursor()

    cur.execute("""
    UPDATE tasks
    SET done=1
    WHERE id=? AND user_id=?
    """, (
        task_id,
        update.effective_user.id
    ))

    con.commit()

    changed = cur.rowcount

    con.close()

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

def parse_time(value):

    try:

        if value.endswith("m"):

            return int(value[:-1]) * 60

        if value.endswith("h"):

            return int(value[:-1]) * 3600

        if value.endswith("s"):

            return int(value[:-1])

    except:

        return None

    return None


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):

    job = context.job

    await context.bot.send_message(
        chat_id=job.chat_id,
        text=f"⏰ REMINDER\n\n{job.data}"
    )


async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) < 2:

        await update.message.reply_text(
            "ব্যবহার:\n"
            "/remind 10m পানি খাও\n"
            "/remind 1h পড়তে বসো"
        )

        return

    seconds = parse_time(context.args[0])

    if not seconds:

        await update.message.reply_text(
            "❌ সময় সঠিক নয়। উদাহরণ: 10m বা 1h"
        )

        return

    text_value = " ".join(context.args[1:])

    context.job_queue.run_once(
        reminder_job,
        seconds,
        chat_id=update.effective_chat.id,
        data=text_value
    )

    await update.message.reply_text(
        f"⏰ Reminder set!\n\n"
        f"সময়: {context.args[0]}\n"
        f"কাজ: {text_value}"
    )


# =========================================================
# HISTORY
# =========================================================

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):

    con = db()
    cur = con.cursor()

    cur.execute("""
    SELECT amount,reason,created
    FROM history
    WHERE user_id=?
    ORDER BY id DESC
    LIMIT 20
    """, (
        update.effective_user.id,
    ))

    rows = cur.fetchall()

    con.close()

    if not rows:

        await update.message.reply_text(
            "📜 কোনো point history নেই।"
        )

        return

    text = "📜 POINT HISTORY\n\n"

    for amount, reason, created in rows:

        sign = "+" if amount >= 0 else ""

        text += f"{sign}{amount} ⭐ — {reason}\n"

    await update.message.reply_text(text)


# =========================================================
# LEADERBOARD
# =========================================================

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):

    con = db()
    cur = con.cursor()

    cur.execute("""
    SELECT name,points
    FROM users
    ORDER BY points DESC
    LIMIT 10
    """)

    rows = cur.fetchall()

    con.close()

    text = "🏆 TOP USERS\n\n"

    for i, row in enumerate(rows, 1):

        text += f"{i}. {row[0]} — ⭐ {row[1]}\n"

    await update.message.reply_text(text)


# =========================================================
# USER ID
# =========================================================

async def userid(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        f"🆔 Your Telegram ID:\n\n"
        f"`{update.effective_user.id}`",
        parse_mode="Markdown"
    )


# =========================================================
# FEEDBACK
# =========================================================

async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "/feedback তোমার feedback লিখো"
        )

        return

    text_value = " ".join(context.args)

    con = db()
    cur = con.cursor()

    cur.execute("""
    INSERT INTO feedback(user_id,text,created)
    VALUES(?,?,?)
    """, (
        update.effective_user.id,
        text_value,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    con.commit()
    con.close()

    await update.message.reply_text(
        "❤️ তোমার feedback নেওয়া হয়েছে। ধন্যবাদ!"
    )


# =========================================================
# ADMIN PANEL
# =========================================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ এই command শুধু Admin-এর জন্য।"
        )

        return

    con = db()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    cur.execute("SELECT SUM(points) FROM users")
    total_points = cur.fetchone()[0] or 0

    con.close()

    await update.message.reply_text(
        "👑 ADMIN PANEL\n\n"
        f"👥 Users: {total_users}\n"
        f"⭐ Total Points: {total_points}\n\n"
        "🎁 Redeem code তৈরি:\n"
        "/addcode CODE POINTS USES\n\n"
        "Example:\n"
        "/addcode SUPER100 100 10"
    )


# =========================================================
# USER STATS
# =========================================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = get_user(update.effective_user.id)

    if not user:

        await update.message.reply_text(
            "❌ User profile পাওয়া যায়নি।"
        )

        return

    await update.message.reply_text(
        "📊 YOUR STATS\n\n"
        f"👤 Name: {user[1]}\n"
        f"💬 Messages: {user[4]}\n"
        f"⭐ Points: {user[5]}\n"
        f"👥 Referrals: {user[6]}\n"
        f"🔥 Streak: {user[7]}"
    )


# =========================================================
# TEXT / GROUP AI PLACEHOLDER
# =========================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    user = update.effective_user

    register_user(user)

    text_value = update.message.text or ""

    # Group mention detection
    if update.effective_chat.type in ["group", "supergroup"]:

        me = await context.bot.get_me()

        if f"@{me.username}".lower() not in text_value.lower():

            return

        clean = text_value.replace(
            f"@{me.username}",
            ""
        ).strip()

        await update.message.reply_text(
            "🤖 Super Bot received your message!\n\n"
            f"💬 You said:\n{clean}\n\n"
            "ℹ️ Real AI response চালু করতে AI provider API যুক্ত করতে হবে।"
        )

        return

    # Private chat
    await update.message.reply_text(
        "🤖 SUPER BOT\n\n"
        "তোমার message পেয়েছি!\n\n"
        "AI Chat ব্যবহার করতে নিচের 🤖 AI CHAT button চাপো।"
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):

    logger.error(
        "Update caused error: %s",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if BOT_TOKEN == "PASTE_YOUR_NEW_BOT_TOKEN_HERE":

        print(
            "\n❌ BOT TOKEN বসানো হয়নি!\n"
            "bot.py-এর উপরের BOT_TOKEN লাইনে "
            "তোমার নতুন BotFather token বসাও।\n"
        )

        return

    init_db()

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
        CommandHandler("daily", daily)
    )

    application.add_handler(
        CommandHandler("points", points)
    )

    application.add_handler(
        CommandHandler("refer", refer)
    )

    application.add_handler(
        CommandHandler("redeem", redeem)
    )

    application.add_handler(
        CommandHandler("addcode", addcode)
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
        CommandHandler("history", history)
    )

    application.add_handler(
        CommandHandler("leaderboard", leaderboard)
    )

    application.add_handler(
        CommandHandler("id", userid)
    )

    application.add_handler(
        CommandHandler("feedback", feedback)
    )

    application.add_handler(
        CommandHandler("admin", admin)
    )

    application.add_handler(
        CommandHandler("stats", stats)
    )

    # Buttons
    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    # Messages
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    application.add_error_handler(error_handler)

    print("================================")
    print("🤖 SUPER BOT IS RUNNING")
    print("👑 ADMIN ID:", ADMIN_ID)
    print("================================")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
