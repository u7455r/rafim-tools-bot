import os
import sqlite3
import threading
import time
import secrets
import string
from datetime import datetime, date

import telebot
from telebot import types
from flask import Flask


# ============================================================
# RAFIM GIVEAWAY BOT
# ALL EXISTING FEATURES
# NEW CHANNEL + GROUP
#
# CHANNEL: @bdgiveaways24
# GROUP:   @bdgivewaychat
# ============================================================


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip())
except Exception:
    ADMIN_ID = 0

# New Channel + Group
CHANNEL_1 = "@bdgiveaways24"
GROUP_1 = "@bdgivewaychat"

SUPPORT_USERNAME = (
    os.getenv("SUPPORT_USERNAME", "rafimhossen")
    .strip()
    .lstrip("@")
)

DB_FILE = os.getenv("DB_FILE", "giveaway_bot.db")


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID is missing")


# ============================================================
# BOT
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    threaded=True
)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Giveaway Bot is running! ✅"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


# ============================================================
# DATABASE
# ============================================================

db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    with db_lock:

        conn = db()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                redeem_code TEXT UNIQUE NOT NULL,
                reward_text TEXT NOT NULL,
                category TEXT DEFAULT 'Giveaway',
                status TEXT DEFAULT 'active',
                used_by INTEGER,
                used_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_lang (
                user_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'bn'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS redeem_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                redeem_code TEXT,
                reward_text TEXT,
                redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_claims (
                user_id INTEGER PRIMARY KEY,
                claim_date TEXT
            )
        """)

        conn.commit()
        conn.close()


init_db()


# ============================================================
# GLOBAL STATES
# ============================================================

admin_states = {}
broadcast_running = False


# ============================================================
# TEXT
# ============================================================

TEXT = {

    "bn": {

        "join_required":
            "🚨 <b>প্রথমে আমাদের Channel এবং Group-এ Join করুন!</b>\n\n"
            "👇 Join করার পর নিচের <b>Verify</b> বাটনে চাপুন।",

        "verified":
            "✅ <b>Verification Successful!</b>\n\n"
            "🎉 এখন আপনি Giveaway Bot-এর সব User Feature ব্যবহার করতে পারবেন।",

        "verify_failed":
            "❌ আপনি এখনো Channel অথবা Group-এ Join করেননি।\n\n"
            "দুটো জায়গায় Join করে আবার Verify করুন।",

        "main":
            "🎉 <b>Welcome to Giveaway Bot!</b>\n\n"
            "🎁 Giveaway ও Redeem Code Claim করুন।\n"
            "⚡ নতুন Code পেলে দ্রুত Redeem করুন!",

        "redeem_prompt":
            "🎁 <b>আপনার Redeem Code পাঠান:</b>\n\n"
            "উদাহরণ: <code>GIVE-XXXXXXXX</code>",

        "invalid_code":
            "❌ <b>Invalid Redeem Code!</b>\n\n"
            "সঠিক Code দিয়ে আবার চেষ্টা করুন।",

        "already_used":
            "⚠️ এই Redeem Code ইতিমধ্যে ব্যবহার করা হয়েছে।",

        "redeem_success":
            "🎉 <b>Redeem Successful!</b>\n\n"
            "🔑 Code: <code>{code}</code>\n"
            "🎁 Reward: <b>{reward}</b>\n\n"
            "✅ আপনার Reward সফলভাবে Claim হয়েছে।",

        "daily_done":
            "⚠️ আপনি আজকের Daily Giveaway ইতিমধ্যে Claim করেছেন।",

        "daily_success":
            "🎉 <b>Daily Giveaway Claimed!</b>\n\n"
            "🎁 আপনার Daily Reward সফলভাবে Claim হয়েছে।",

        "status":
            "📊 <b>My Status</b>\n\n"
            "🆔 User ID: <code>{user_id}</code>\n"
            "👤 Name: {name}\n"
            "🔗 Username: {username}\n"
            "🎁 Redeemed: <b>{count}</b>\n"
            "🎯 Daily: <b>{daily}</b>",

        "help":
            "ℹ️ <b>Help</b>\n\n"
            "🔑 Redeem Code — Giveaway Code Redeem করুন\n"
            "🎁 Daily Giveaway — Daily Reward Claim করুন\n"
            "📊 My Status — আপনার Account Status দেখুন\n"
            "⚙️ Settings — Language পরিবর্তন করুন\n\n"
            "🆘 Support: @{support}",

        "settings":
            "⚙️ <b>Settings</b>\n\n"
            "আপনার Language নির্বাচন করুন।",

        "admin_only":
            "⛔ এই অপশনটি শুধুমাত্র Admin-এর জন্য।",

        "add_reward":
            "🎁 <b>Reward / Token লিখে পাঠান:</b>\n\n"
            "উদাহরণ:\n"
            "<code>Netflix Premium</code>\n"
            "<code>100 Points</code>\n"
            "<code>Crunchyroll Premium</code>\n\n"
            "❌ বাতিল করতে /cancel লিখুন।",

        "broadcast_prompt":
            "📢 <b>Broadcast Message পাঠান:</b>\n\n"
            "❌ বাতিল করতে /cancel লিখুন।",

        "direct_prompt":
            "💬 <b>User ID লিখুন:</b>\n\n"
            "তারপর ওই User-কে Message পাঠাতে পারবেন।\n"
            "❌ বাতিল করতে /cancel লিখুন।",

        "user_not_found":
            "❌ User ID পাওয়া যায়নি।",

        "cancelled":
            "❌ Operation Cancelled.",

        "admin_panel":
            "👑 <b>Admin Panel</b>\n\n"
            "নিচের অপশন থেকে নির্বাচন করুন।"
    },

    "en": {

        "join_required":
            "🚨 <b>Join our Channel and Group first!</b>\n\n"
            "👇 After joining, press <b>Verify</b>.",

        "verified":
            "✅ <b>Verification Successful!</b>\n\n"
            "🎉 You can now use all User Features.",

        "verify_failed":
            "❌ You have not joined the Channel or Group yet.\n\n"
            "Join both and try Verify again.",

        "main":
            "🎉 <b>Welcome to Giveaway Bot!</b>\n\n"
            "🎁 Claim Giveaway and Redeem Codes.\n"
            "⚡ Redeem new codes quickly!",

        "redeem_prompt":
            "🎁 <b>Send your Redeem Code:</b>\n\n"
            "Example: <code>GIVE-XXXXXXXX</code>",

        "invalid_code":
            "❌ <b>Invalid Redeem Code!</b>\n\n"
            "Please try again with a valid code.",

        "already_used":
            "⚠️ This Redeem Code has already been used.",

        "redeem_success":
            "🎉 <b>Redeem Successful!</b>\n\n"
            "🔑 Code: <code>{code}</code>\n"
            "🎁 Reward: <b>{reward}</b>\n\n"
            "✅ Your reward has been successfully claimed.",

        "daily_done":
            "⚠️ You have already claimed today's Daily Giveaway.",

        "daily_success":
            "🎉 <b>Daily Giveaway Claimed!</b>\n\n"
            "🎁 Your Daily Reward has been claimed.",

        "status":
            "📊 <b>My Status</b>\n\n"
            "🆔 User ID: <code>{user_id}</code>\n"
            "👤 Name: {name}\n"
            "🔗 Username: {username}\n"
            "🎁 Redeemed: <b>{count}</b>\n"
            "🎯 Daily: <b>{daily}</b>",

        "help":
            "ℹ️ <b>Help</b>\n\n"
            "🔑 Redeem Code — Redeem Giveaway Code\n"
            "🎁 Daily Giveaway — Claim Daily Reward\n"
            "📊 My Status — View Account Status\n"
            "⚙️ Settings — Change Language\n\n"
            "🆘 Support: @{support}",

        "settings":
            "⚙️ <b>Settings</b>\n\n"
            "Choose your language.",

        "admin_only":
            "⛔ This option is only for Admin.",

        "add_reward":
            "🎁 <b>Send Reward / Token:</b>\n\n"
            "Example:\n"
            "<code>Netflix Premium</code>\n"
            "<code>100 Points</code>\n"
            "<code>Crunchyroll Premium</code>\n\n"
            "❌ Send /cancel to cancel.",

        "broadcast_prompt":
            "📢 <b>Send Broadcast Message:</b>\n\n"
            "❌ Send /cancel to cancel.",

        "direct_prompt":
            "💬 <b>Send User ID:</b>\n\n"
            "Then you can send a message to that user.\n"
            "❌ Send /cancel to cancel.",

        "user_not_found":
            "❌ User ID not found.",

        "cancelled":
            "❌ Operation Cancelled.",

        "admin_panel":
            "👑 <b>Admin Panel</b>\n\n"
            "Choose an option below."
    }
}


# ============================================================
# LANGUAGE
# ============================================================

def get_lang(user_id):

    with db_lock:

        conn = db()

        row = conn.execute(
            "SELECT lang FROM user_lang WHERE user_id=?",
            (user_id,)
        ).fetchone()

        conn.close()

    if row and row["lang"] in ("bn", "en"):
        return row["lang"]

    return "bn"


def set_lang(user_id, lang):

    with db_lock:

        conn = db()

        conn.execute("""
            INSERT INTO user_lang(user_id, lang)
            VALUES (?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET lang=excluded.lang
        """, (
            user_id,
            lang
        ))

        conn.commit()
        conn.close()


def tr(user_id, key, **kwargs):

    lang = get_lang(user_id)

    value = TEXT[lang].get(
        key,
        TEXT["bn"].get(key, key)
    )

    return value.format(**kwargs)


# ============================================================
# USER DATABASE
# ============================================================

def save_user(user):

    with db_lock:

        conn = db()

        conn.execute("""
            INSERT INTO users(
                user_id,
                username,
                first_name,
                last_name,
                joined_at,
                last_seen
            )

            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)

            ON CONFLICT(user_id)

            DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen=CURRENT_TIMESTAMP
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or ""
        ))

        conn.commit()
        conn.close()


def is_banned(user_id):

    with db_lock:

        conn = db()

        row = conn.execute(
            "SELECT banned FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

        conn.close()

    return bool(
        row and row["banned"]
    )


def all_user_ids():

    with db_lock:

        conn = db()

        rows = conn.execute(
            "SELECT user_id FROM users WHERE banned=0"
        ).fetchall()

        conn.close()

    return [
        row["user_id"]
        for row in rows
    ]


# ============================================================
# ADMIN
# ============================================================

def is_admin(user_id):
    return user_id == ADMIN_ID


def admin_keyboard():

    kb = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    kb.add(
        types.KeyboardButton("➕ Add Giveaway"),
        types.KeyboardButton("📋 Active Codes")
    )

    kb.add(
        types.KeyboardButton("📊 Statistics"),
        types.KeyboardButton("📢 Broadcast")
    )

    kb.add(
        types.KeyboardButton("💬 Direct User Chat"),
        types.KeyboardButton("🛑 Cancel Broadcast")
    )

    kb.add(
        types.KeyboardButton("🏠 User Menu")
    )

    return kb


def user_keyboard(lang="bn"):

    kb = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    if lang == "en":

        kb.add(
            types.KeyboardButton("🔑 Redeem Code"),
            types.KeyboardButton("⚙️ Settings")
        )

        kb.add(
            types.KeyboardButton("🎁 Daily Giveaway"),
            types.KeyboardButton("📊 My Status")
        )

        kb.add(
            types.KeyboardButton("ℹ️ Help")
        )

    else:

        kb.add(
            types.KeyboardButton("🔑 কোড রিডিম"),
            types.KeyboardButton("⚙️ সেটিংস")
        )

        kb.add(
            types.KeyboardButton("🎁 ডেইলি গিভঅ্যাওয়ে"),
            types.KeyboardButton("📊 আমার স্ট্যাটাস")
        )

        kb.add(
            types.KeyboardButton("ℹ️ সাহায্য")
        )

    return kb


# ============================================================
# FORCE JOIN
# ============================================================

CHANNEL_CHAT = "@bdgiveaways24"
GROUP_CHAT = "@bdgivewaychat"


def get_member(chat_id, user_id):

    try:

        return bot.get_chat_member(
            chat_id,
            user_id
        )

    except Exception:

        return None


def valid_member(member):

    if not member:
        return False

    status = getattr(
        member,
        "status",
        ""
    )

    if status in (
        "creator",
        "administrator",
        "member"
    ):
        return True

    if status == "restricted":

        return bool(
            getattr(
                member,
                "is_member",
                False
            )
        )

    return False


def check_membership(user_id):

    channel_member = get_member(
        CHANNEL_CHAT,
        user_id
    )

    group_member = get_member(
        GROUP_CHAT,
        user_id
    )

    return (
        valid_member(channel_member)
        and valid_member(group_member)
    )


# ============================================================
# NEW JOIN BUTTONS
# ============================================================

def join_keyboard():

    kb = types.InlineKeyboardMarkup(
        row_width=1
    )

    kb.add(
        types.InlineKeyboardButton(
            "📢 Join Channel",
            url="https://t.me/bdgiveaways24"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "👥 Join Group",
            url="https://t.me/bdgivewaychat"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "✅ Verify",
            callback_data="verify_join"
        )
    )

    return kb


def send_join_message(chat_id):

    bot.send_message(
        chat_id,
        tr(
            chat_id,
            "join_required"
        ),
        reply_markup=join_keyboard()
    )


# ============================================================
# ADMIN NEW USER ALERT
# ============================================================

def admin_new_user_alert(user):

    try:

        username = (
            f"@{user.username}"
            if user.username
            else "No Username"
        )

        name = (
            f"{user.first_name or ''} "
            f"{user.last_name or ''}"
        ).strip()

        bot.send_message(
            ADMIN_ID,

            "🆕 <b>New User Verified</b>\n\n"
            f"👤 Name: {name or 'Unknown'}\n"
            f"🔗 Username: {username}\n"
            f"🆔 User ID: <code>{user.id}</code>"
        )

    except Exception:
        pass


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start_command(message):

    save_user(message.from_user)

    user_id = message.from_user.id

    if is_banned(user_id):

        bot.send_message(
            user_id,
            "⛔ You are banned from using this bot."
        )

        return

    if is_admin(user_id):

        bot.send_message(
            user_id,
            tr(
                user_id,
                "admin_panel"
            ),
            reply_markup=admin_keyboard()
        )

        return

    if not check_membership(user_id):

        send_join_message(user_id)

        return

    bot.send_message(
        user_id,
        tr(
            user_id,
            "main"
        ),
        reply_markup=user_keyboard(
            get_lang(user_id)
        )
    )


# ============================================================
# VERIFY
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "verify_join"
)
def verify_join(call):

    user = call.from_user

    save_user(user)

    if is_banned(user.id):

        bot.answer_callback_query(
            call.id,
            "You are banned.",
            show_alert=True
        )

        return

    if check_membership(user.id):

        bot.answer_callback_query(
            call.id,
            "Verified successfully!",
            show_alert=True
        )

        try:

            bot.delete_message(
                call.message.chat.id,
                call.message.message_id
            )

        except Exception:
            pass

        admin_new_user_alert(user)

        bot.send_message(
            user.id,
            tr(
                user.id,
                "verified"
            ),
            reply_markup=user_keyboard(
                get_lang(user.id)
            )
        )

    else:

        bot.answer_callback_query(
            call.id,
            "Please join both first.",
            show_alert=True
        )


# ============================================================
# LANGUAGE
# ============================================================

def language_keyboard():

    kb = types.InlineKeyboardMarkup(
        row_width=2
    )

    kb.add(
        types.InlineKeyboardButton(
            "🇧🇩 বাংলা",
            callback_data="lang_bn"
        ),
        types.InlineKeyboardButton(
            "🇬🇧 English",
            callback_data="lang_en"
        )
    )

    return kb


@bot.callback_query_handler(
    func=lambda call:
        call.data in (
            "lang_bn",
            "lang_en"
        )
)
def language_callback(call):

    lang = (
        "bn"
        if call.data == "lang_bn"
        else "en"
    )

    set_lang(
        call.from_user.id,
        lang
    )

    bot.answer_callback_query(
        call.id,
        "Language changed."
    )

    try:

        bot.edit_message_text(
            TEXT[lang]["settings"],
            call.message.chat.id,
            call.message.message_id
        )

    except Exception:
        pass

    bot.send_message(
        call.from_user.id,
        TEXT[lang]["main"],
        reply_markup=user_keyboard(lang)
    )


# ============================================================
# SETTINGS
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text in (
            "⚙️ সেটিংস",
            "⚙️ Settings"
        )
)
def settings_handler(message):

    if not check_membership(
        message.from_user.id
    ):

        send_join_message(
            message.chat.id
        )

        return

    bot.send_message(
        message.chat.id,
        tr(
            message.from_user.id,
            "settings"
        ),
        reply_markup=language_keyboard()
    )


# ============================================================
# HELP
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text in (
            "ℹ️ সাহায্য",
            "ℹ️ Help"
        )
)
def help_handler(message):

    if not check_membership(
        message.from_user.id
    ):

        send_join_message(
            message.chat.id
        )

        return

    bot.send_message(
        message.chat.id,

        tr(
            message.from_user.id,
            "help",
            support=SUPPORT_USERNAME
        ),

        reply_markup=user_keyboard(
            get_lang(
                message.from_user.id
            )
        )
    )


# ============================================================
# REDEEM BUTTON
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text in (
            "🔑 কোড রিডিম",
            "🔑 Redeem Code"
        )
)
def redeem_button(message):

    if not check_membership(
        message.from_user.id
    ):

        send_join_message(
            message.chat.id
        )

        return

    bot.send_message(
        message.chat.id,
        tr(
            message.from_user.id,
            "redeem_prompt"
        )
    )


# ============================================================
# REDEEM CODE
# ============================================================

@bot.message_handler(
    func=lambda m:
        isinstance(m.text, str)
        and m.text.upper().startswith("GIVE-")
)
def redeem_code(message):

    user_id = message.from_user.id

    save_user(
        message.from_user
    )

    if is_banned(user_id):
        return

    if not check_membership(user_id):

        send_join_message(
            message.chat.id
        )

        return

    code = message.text.strip().upper()

    with db_lock:

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM giveaways
            WHERE redeem_code=?
        """, (code,)).fetchone()

        if not row:

            conn.close()

            bot.send_message(
                user_id,
                tr(
                    user_id,
                    "invalid_code"
                )
            )

            return

        if row["status"] != "active":

            conn.close()

            bot.send_message(
                user_id,
                tr(
                    user_id,
                    "already_used"
                )
            )

            return

        now = datetime.utcnow().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        updated = conn.execute("""
            UPDATE giveaways

            SET
                status='used',
                used_by=?,
                used_at=?

            WHERE
                redeem_code=?
                AND status='active'
        """, (
            user_id,
            now,
            code
        )).rowcount

        if updated != 1:

            conn.close()

            bot.send_message(
                user_id,
                tr(
                    user_id,
                    "already_used"
                )
            )

            return

        conn.execute("""
            INSERT INTO redeem_history(
                user_id,
                redeem_code,
                reward_text
            )

            VALUES (?, ?, ?)
        """, (
            user_id,
            code,
            row["reward_text"]
        ))

        conn.commit()
        conn.close()

    bot.send_message(
        user_id,

        tr(
            user_id,
            "redeem_success",
            code=code,
            reward=row["reward_text"]
        )
    )


# ============================================================
# DAILY GIVEAWAY
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text in (
            "🎁 ডেইলি গিভঅ্যাওয়ে",
            "🎁 Daily Giveaway"
        )
)
def daily_giveaway(message):

    user_id = message.from_user.id

    if not check_membership(user_id):

        send_join_message(
            message.chat.id
        )

        return

    today = date.today().isoformat()

    with db_lock:

        conn = db()

        claim = conn.execute("""
            SELECT claim_date
            FROM daily_claims
            WHERE user_id=?
        """, (
            user_id,
        )).fetchone()

        if (
            claim
            and claim["claim_date"] == today
        ):

            conn.close()

            bot.send_message(
                user_id,
                tr(
                    user_id,
                    "daily_done"
                )
            )

            return

        conn.execute("""
            INSERT INTO daily_claims(
                user_id,
                claim_date
            )

            VALUES (?, ?)

            ON CONFLICT(user_id)

            DO UPDATE SET
                claim_date=excluded.claim_date
        """, (
            user_id,
            today
        ))

        conn.commit()
        conn.close()

    bot.send_message(
        user_id,
        tr(
            user_id,
            "daily_success"
        )
    )


# ============================================================
# MY STATUS
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.text in (
            "📊 আমার স্ট্যাটাস",
            "📊 My Status"
        )
)
def my_status(message):

    user_id = message.from_user.id

    if not check_membership(user_id):

        send_join_message(
            message.chat.id
        )

        return

    with db_lock:

        conn = db()

        user = conn.execute("""
            SELECT *
            FROM users
            WHERE user_id=?
        """, (
            user_id,
        )).fetchone()

        count_row = conn.execute("""
            SELECT COUNT(*) AS total
            FROM redeem_history
            WHERE user_id=?
        """, (
            user_id,
        )).fetchone()

        daily = conn.execute("""
            SELECT claim_date
            FROM daily_claims
            WHERE user_id=?
        """, (
            user_id,
        )).fetchone()

        conn.close()

    name = (
        f"{user['first_name'] or ''} "
        f"{user['last_name'] or ''}"
    ).strip()

    username = (
        f"@{user['username']}"
        if user["username"]
        else "No Username"
    )

    daily_text = (
        "Claimed"
        if (
            daily
            and daily["claim_date"]
            == date.today().isoformat()
        )
        else "Not Claimed"
    )

    bot.send_message(

        user_id,

        tr(
            user_id,
            "status",

            user_id=user_id,

            name=name or "Unknown",

            username=username,

            count=count_row["total"],

            daily=daily_text
        )
    )


# ============================================================
# ADMIN USER MENU
# ============================================================

@bot.message_handler(
    func=lambda m:
        is_admin(m.from_user.id)
        and m.text == "🏠 User Menu"
)
def admin_user_menu(message):

    bot.send_message(
        message.chat.id,

        tr(
            message.from_user.id,
            "main"
        ),

        reply_markup=user_keyboard(
            get_lang(
                message.from_user.id
            )
        )
    )


# ============================================================
# ADMIN ADD GIVEAWAY
# ============================================================

@bot.message_handler(
    func=lambda m:
        is_admin(m.from_user.id)
        and m.text == "➕ Add Giveaway"
)
def add_giveaway_start(message):

    admin_states[
        message.from_user.id
    ] = {
        "action": "add_reward"
    }

    bot.send_message(
        message.chat.id,
        TEXT["bn"]["add_reward"]
    )


# ============================================================
# GENERATE CODE
# ============================================================

def generate_redeem_code():

    alphabet = (
        string.ascii_uppercase
        + string.digits
    )

    while True:

        code = (
            "GIVE-"
            + "".join(
                secrets.choice(alphabet)
                for _ in range(8)
            )
        )

        with db_lock:

            conn = db()

            row = conn.execute("""
                SELECT id
                FROM giveaways
                WHERE redeem_code=?
            """, (
                code,
            )).fetchone()

            conn.close()

        if not row:
            return code


# ============================================================
# ACTIVE CODES
# ============================================================

@bot.message_handler(
    func=lambda m:
        is_admin(m.from_user.id)
        and m.text == "📋 Active Codes"
)
def active_codes(message):

    with db_lock:

        conn = db()

        rows = conn.execute("""
            SELECT
                redeem_code,
                reward_text,
                created_at
            FROM giveaways
            WHERE status='active'
            ORDER BY id DESC
            LIMIT 50
        """).fetchall()

        conn.close()

    if not rows:

        bot.send_message(
            message.chat.id,
            "📋 <b>Active Codes</b>\n\n"
            "❌ No active codes."
        )

        return

    text = (
        "📋 <b>Active Codes</b>\n\n"
    )

    for i, row in enumerate(
        rows,
        1
    ):

        text += (
            f"{i}. "
            f"<code>{row['redeem_code']}</code>\n"
            f"🎁 {row['reward_text']}\n"
            f"🕒 {row['created_at']}\n\n"
        )

    bot.send_message(
        message.chat.id,
        text
    )


# ============================================================
# STATISTICS
# ============================================================

@bot.message_handler(
    func=lambda m:
        is_admin(m.from_user.id)
        and m.text == "📊 Statistics"
)
def admin_statistics(message):

    with db_lock:

        conn = db()

        users = conn.execute(
            "SELECT COUNT(*) AS c FROM users"
        ).fetchone()["c"]

        active = conn.execute("""
            SELECT COUNT(*) AS c
            FROM giveaways
            WHERE status='active'
        """).fetchone()["c"]

        used = conn.execute("""
            SELECT COUNT(*) AS c
            FROM giveaways
            WHERE status='used'
        """).fetchone()["c"]

        redeemed = conn.execute("""
            SELECT COUNT(*) AS c
            FROM redeem_history
        """).fetchone()["c"]

        conn.close()

    bot.send_message(

        message.chat.id,

        "📊 <b>Bot Statistics</b>\n\n"

        f"👥 Total Users: <b>{users}</b>\n"

        f"🎁 Active Codes: <b>{active}</b>\n"

        f"✅ Used Codes: <b>{used}</b>\n"

        f"🔑 Total Redeems: <b>{redeemed}</b>"
    )


# ============================================================
# BROADCAST START
# ============================================================

@bot.message_handler(
    func=lambda m:
        is_admin(m.from_user.id)
        and m.text == "📢 Broadcast"
)
def broadcast_start(message):

    admin_states[
        message.from_user.id
    ] = {
        "action": "broadcast"
    }

    bot.send_message(
        message.chat.id,
        TEXT["bn"]["broadcast_prompt"]
    )


# ============================================================
# CANCEL BROADCAST
# ============================================================

@bot.message_handler(
    func=lambda m:
        is_admin(m.from_user.id)
        and m.text == "🛑 Cancel Broadcast"
)
def cancel_broadcast(message):

    global broadcast_running

    broadcast_running = False

    bot.send_message(
        message.chat.id,
        "🛑 <b>Broadcast cancellation requested.</b>"
    )


# ============================================================
# DIRECT CHAT
# ============================================================

@bot.message_handler(
    func=lambda m:
        is_admin(m.from_user.id)
        and m.text == "💬 Direct User Chat"
)
def direct_chat_start(message):

    admin_states[
        message.from_user.id
    ] = {
        "action": "direct_user_id"
    }

    bot.send_message(
        message.chat.id,
        TEXT["bn"]["direct_prompt"]
    )


# ============================================================
# /CANCEL
# ============================================================

@bot.message_handler(commands=["cancel"])
def cancel_operation(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    admin_states.pop(
        message.from_user.id,
        None
    )

    bot.send_message(
        message.chat.id,
        TEXT["bn"]["cancelled"],
        reply_markup=admin_keyboard()
    )


# ============================================================
# /ENDCHAT
# ============================================================

@bot.message_handler(commands=["endchat"])
def end_chat(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    admin_states.pop(
        message.from_user.id,
        None
    )

    bot.send_message(
        message.chat.id,
        "✅ Direct User Chat ended.",
        reply_markup=admin_keyboard()
    )


# ============================================================
# BROADCAST WORKER
# ============================================================

def broadcast_worker(
    admin_id,
    message
):

    global broadcast_running

    users = all_user_ids()

    total = len(users)

    success = 0
    failed = 0

    broadcast_running = True

    progress_message = bot.send_message(

        admin_id,

        "📢 <b>Broadcast Started</b>\n\n"

        f"👥 Total: {total}\n"

        "📤 Processed: 0\n"

        "✅ Success: 0\n"

        "❌ Failed: 0\n"

        "📊 Progress: 0%"
    )

    processed = 0

    for user_id in users:

        if not broadcast_running:
            break

        processed += 1

        try:

            bot.copy_message(
                user_id,
                admin_id,
                message.message_id
            )

            success += 1

        except Exception:

            failed += 1

        if (
            processed % 10 == 0
            or processed == total
        ):

            percent = (
                int(
                    processed
                    * 100
                    / total
                )
                if total
                else 100
            )

            try:

                bot.edit_message_text(

                    "📢 <b>Broadcast Running...</b>\n\n"

                    f"👥 Total: {total}\n"

                    f"📤 Processed: {processed}\n"

                    f"✅ Success: {success}\n"

                    f"❌ Failed: {failed}\n"

                    f"📊 Progress: {percent}%",

                    admin_id,

                    progress_message.message_id
                )

            except Exception:
                pass

        time.sleep(0.05)

    cancelled = not broadcast_running

    broadcast_running = False

    try:

        bot.edit_message_text(

            "📢 <b>Broadcast Finished</b>\n\n"

            f"👥 Total: {total}\n"

            f"📤 Processed: {processed}\n"

            f"✅ Success: {success}\n"

            f"❌ Failed: {failed}\n"

            f"🛑 Cancelled: "
            f"{'Yes' if cancelled else 'No'}",

            admin_id,

            progress_message.message_id
        )

    except Exception:
        pass


# ============================================================
# ADMIN INPUT
# ============================================================

@bot.message_handler(
    func=lambda m:
        is_admin(m.from_user.id)
)
def admin_input(message):

    user_id = message.from_user.id

    state = admin_states.get(
        user_id
    )

    if not state:
        return

    action = state.get(
        "action"
    )

    # --------------------------------------------------------
    # ADD GIVEAWAY
    # --------------------------------------------------------

    if action == "add_reward":

        reward = (
            message.text or ""
        ).strip()

        if reward.lower() == "/cancel":

            admin_states.pop(
                user_id,
                None
            )

            bot.send_message(
                user_id,
                TEXT["bn"]["cancelled"],
                reply_markup=admin_keyboard()
            )

            return

        if not reward:

            bot.send_message(
                user_id,
                "❌ Reward empty রাখা যাবে না।"
            )

            return

        code = generate_redeem_code()

        with db_lock:

            conn = db()

            conn.execute("""
                INSERT INTO giveaways(
                    redeem_code,
                    reward_text,
                    category,
                    status
                )

                VALUES (
                    ?,
                    ?,
                    'Giveaway',
                    'active'
                )
            """, (
                code,
                reward
            ))

            conn.commit()
            conn.close()

        admin_states.pop(
            user_id,
            None
        )

        bot.send_message(

            user_id,

            "🎉 <b>Giveaway Created!</b>\n\n"

            f"🔑 Redeem Code:\n"
            f"<code>{code}</code>\n\n"

            f"🎁 Reward:\n"
            f"<b>{reward}</b>\n\n"

            "✅ Code is now active.",

            reply_markup=admin_keyboard()
        )

        return

    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------

    if action == "broadcast":

        admin_states.pop(
            user_id,
            None
        )

        threading.Thread(
            target=broadcast_worker,
            args=(
                user_id,
                message
            ),
            daemon=True
        ).start()

        return

    # --------------------------------------------------------
    # DIRECT USER ID
    # --------------------------------------------------------

    if action == "direct_user_id":

        try:

            target_id = int(
                (message.text or "").strip()
            )

        except Exception:

            bot.send_message(
                user_id,
                "❌ Invalid User ID."
            )

            return

        with db_lock:

            conn = db()

            row = conn.execute("""
                SELECT user_id
                FROM users
                WHERE user_id=?
            """, (
                target_id,
            )).fetchone()

            conn.close()

        if not row:

            bot.send_message(
                user_id,
                TEXT["bn"]["user_not_found"]
            )

            return

        admin_states[user_id] = {
            "action": "direct_message",
            "target_id": target_id
        }

        bot.send_message(

            user_id,

            "💬 <b>User Found!</b>\n\n"

            f"🆔 User ID: "
            f"<code>{target_id}</code>\n\n"

            "এখন Message পাঠান।\n"
            "শেষ করতে /endchat লিখুন।"
        )

        return

    # --------------------------------------------------------
    # DIRECT MESSAGE
    # --------------------------------------------------------

    if action == "direct_message":

        target_id = state.get(
            "target_id"
        )

        try:

            bot.copy_message(
                target_id,
                user_id,
                message.message_id
            )

            bot.send_message(
                user_id,
                "✅ Message sent successfully."
            )

        except Exception:

            bot.send_message(
                user_id,
                "❌ Message could not be sent."
            )

        return


# ============================================================
# USER MESSAGE
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.from_user.id != ADMIN_ID
)
def user_message(message):

    user_id = message.from_user.id

    save_user(
        message.from_user
    )

    if is_banned(user_id):
        return

    if message.text == "/admin":

        bot.send_message(
            user_id,
            tr(
                user_id,
                "admin_only"
            )
        )

        return

    if not check_membership(user_id):

        send_join_message(
            user_id
        )

        return

    try:

        username = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else "No Username"
        )

        header = (

            "📩 <b>User Message</b>\n\n"

            f"👤 "
            f"{message.from_user.first_name or ''}\n"

            f"🔗 {username}\n"

            f"🆔 "
            f"<code>{user_id}</code>"
        )

        bot.send_message(
            ADMIN_ID,
            header
        )

        if message.content_type == "text":

            bot.send_message(
                ADMIN_ID,
                message.text
            )

        else:

            try:

                bot.copy_message(
                    ADMIN_ID,
                    user_id,
                    message.message_id
                )

            except Exception:

                bot.send_message(
                    ADMIN_ID,
                    "📎 User sent a non-text message."
                )

    except Exception:
        pass


# ============================================================
# /USERS
# ============================================================

@bot.message_handler(commands=["users"])
def users_command(message):

    if not is_admin(
        message.from_user.id
    ):

        bot.send_message(
            message.chat.id,
            tr(
                message.from_user.id,
                "admin_only"
            )
        )

        return

    with db_lock:

        conn = db()

        rows = conn.execute("""
            SELECT
                user_id,
                username,
                first_name,
                last_name,
                last_seen
            FROM users
            ORDER BY last_seen DESC
            LIMIT 30
        """).fetchall()

        conn.close()

    if not rows:

        bot.send_message(
            message.chat.id,
            "👥 No users found."
        )

        return

    text = "👥 <b>Recent Users</b>\n\n"

    for row in rows:

        username = (
            f"@{row['username']}"
            if row["username"]
            else "No Username"
        )

        name = (
            f"{row['first_name'] or ''} "
            f"{row['last_name'] or ''}"
        ).strip()

        text += (

            f"👤 "
            f"{name or 'Unknown'}\n"

            f"🔗 {username}\n"

            f"🆔 "
            f"<code>{row['user_id']}</code>\n"

            f"🕒 {row['last_seen']}\n\n"
        )

    bot.send_message(
        message.chat.id,
        text
    )


# ============================================================
# /ADMIN
# ============================================================

@bot.message_handler(commands=["admin"])
def admin_command(message):

    if not is_admin(
        message.from_user.id
    ):

        bot.send_message(
            message.chat.id,
            tr(
                message.from_user.id,
                "admin_only"
            )
        )

        return

    bot.send_message(

        message.chat.id,

        tr(
            message.from_user.id,
            "admin_panel"
        ),

        reply_markup=admin_keyboard()
    )


# ============================================================
# /HEALTH
# ============================================================

@bot.message_handler(commands=["health"])
def health_command(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    bot.send_message(

        message.chat.id,

        "✅ <b>Bot is Online</b>\n\n"

        "📢 Channel:\n"
        "<code>@bdgiveaways24</code>\n\n"

        "👥 Group:\n"
        "<code>@bdgivewaychat</code>\n\n"

        f"🗄 Database:\n"
        f"<code>{DB_FILE}</code>"
    )


# ============================================================
# START BOT
# ============================================================

def start_bot():

    while True:

        try:

            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True
            )

        except Exception as e:

            print(
                "Polling error:",
                repr(e)
            )

            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print(
        "======================================"
    )

    print(
        "RAFIM GIVEAWAY BOT"
    )

    print(
        "======================================"
    )

    print(
        "CHANNEL: @bdgiveaways24"
    )

    print(
        "GROUP: @bdgivewaychat"
    )

    print(
        "ADMIN ID:",
        ADMIN_ID
    )

    print(
        "DATABASE:",
        DB_FILE
    )

    print(
        "======================================"
    )

    start_bot()
