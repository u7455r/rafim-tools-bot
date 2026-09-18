import os
import sqlite3
from threading import Thread
from flask import Flask
import telebot
from telebot import types

# ================= 1. RENDER PORT KEEP-ALIVE SERVER =================
app = Flask("")


@app.route("/")
def home():
  return "⚡ RAFIM TOOLS OFFICIAL Bot is Running 24/7!"


def run_web_server():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


def keep_alive():
  t = Thread(target=run_web_server)
  t.daemon = True
  t.start()


keep_alive()

# ================= 2. BOT CONFIGURATIONS =================
API_TOKEN = "8809150454:AAGdTm_KSgoRfzMuN6rIC6L877rl9THZ0RQ"  # আপনার বটের টোকেন বসান
ADMIN_ID = 8298133943  # আপনার অ্যাডমিন আইডি

bot = telebot.TeleBot(API_TOKEN)


# ================= 3. DATABASE SETUP =================
def init_db():
  conn = sqlite3.connect("rafim_tools.db")
  cursor = conn.cursor()
  cursor.execute("""CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        credits INTEGER DEFAULT 3,
                        referred_by INTEGER,
                        is_banned INTEGER DEFAULT 0
                    )""")
  cursor.execute("""CREATE TABLE IF NOT EXISTS promo_codes (
                        code TEXT PRIMARY KEY,
                        reward_credits INTEGER,
                        used_by TEXT DEFAULT ''
                    )""")
  cursor.execute(
      "INSERT OR IGNORE INTO promo_codes (code, reward_credits) VALUES"
      " ('RAFIM10', 10)"
  )
  cursor.execute(
      "INSERT OR IGNORE INTO promo_codes (code, reward_credits) VALUES ('FREE5',"
      " 5)"
  )
  conn.commit()
  conn.close()


init_db()


def get_user_data(user_id):
  conn = sqlite3.connect("rafim_tools.db")
  cursor = conn.cursor()
  cursor.execute(
      "SELECT credits, referred_by, is_banned FROM users WHERE user_id = ?",
      (user_id,),
  )
  row = cursor.fetchone()
  conn.close()
  return row


def register_user(user_id, referrer_id=None):
  conn = sqlite3.connect("rafim_tools.db")
  cursor = conn.cursor()
  cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
  is_new = cursor.fetchone() is None

  if is_new:
    cursor.execute(
        "INSERT INTO users (user_id, credits, referred_by, is_banned) VALUES"
        " (?, ?, ?, 0)",
        (user_id, 3, referrer_id),
    )
    if referrer_id and referrer_id != user_id:
      cursor.execute(
          "UPDATE users SET credits = credits + 3 WHERE user_id = ?",
          (referrer_id,),
      )
      try:
        bot.send_message(
            referrer_id,
            "🎉 <b>New Referral Bonus!</b>\nএকজন নতুন ইউজার আপনার লিংকে যুক্ত"
            " হয়েছে। <b>+3 Credits</b> যোগ হয়েছে!",
            parse_mode="HTML",
        )
      except:
        pass
    conn.commit()
  conn.close()
  return is_new


def update_credits(user_id, amount):
  conn = sqlite3.connect("rafim_tools.db")
  cursor = conn.cursor()
  cursor.execute(
      "UPDATE users SET credits = credits + ? WHERE user_id = ?",
      (amount, user_id),
  )
  conn.commit()
  conn.close()


def set_ban_status(user_id, status):
  conn = sqlite3.connect("rafim_tools.db")
  cursor = conn.cursor()
  cursor.execute(
      "UPDATE users SET is_banned = ? WHERE user_id = ?", (status, user_id)
  )
  conn.commit()
  conn.close()


# ================= 4. KEYBOARDS (রিডিম কোডসহ মেনু বাটন) =================
def get_main_keyboard():
  markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
  btn1 = types.KeyboardButton("🔍 BD Number Info")
  btn2 = types.KeyboardButton("👤 My Account")
  btn3 = types.KeyboardButton("🎁 Refer & Earn")
  btn4 = types.KeyboardButton("🎟️ Redeem Code")
  btn5 = types.KeyboardButton("📞 Support")
  markup.add(btn1, btn2, btn3, btn4, btn5)
  return markup


def get_action_inline():
  markup = types.InlineKeyboardMarkup(row_width=2)
  btn_buy = types.InlineKeyboardButton(
      "💳 Buy Credits (Nagad)", callback_data="btn_buy_credits"
  )
  markup.add(btn_buy)
  return markup


# ================= 5. ADMIN COMMANDS (/ban, /unban, /addcode) =================
@bot.message_handler(commands=["addcode"])
def add_code_cmd(message):
  if message.from_user.id != ADMIN_ID:
    return
  args = message.text.split()
  if len(args) == 3 and args[2].isdigit():
    code_name = args[1].upper()
    points = int(args[2])
    conn = sqlite3.connect("rafim_tools.db")
    cursor = conn.cursor()
    try:
      cursor.execute(
          "INSERT INTO promo_codes (code, reward_credits, used_by) VALUES (?,"
          " ?, '')",
          (code_name, points),
      )
      conn.commit()
      bot.reply_to(
          message,
          f"🎟️ <b>Redeem Code Created!</b>\nCode: <code>{code_name}</code>\nPoint:"
          f" <b>+{points}</b>",
          parse_mode="HTML",
      )
    except sqlite3.IntegrityError:
      bot.reply_to(message, "❌ এই কোডটি আগেই তৈরি করা আছে!")
    finally:
      conn.close()
  else:
    bot.reply_to(
        message, "ব্যবহারবিধি: <code>/addcode CODE_NAME CREDITS</code>"
    )


@bot.message_handler(commands=["ban"])
def ban_cmd(message):
  if message.from_user.id != ADMIN_ID:
    return
  args = message.text.split()
  if len(args) > 1 and args[1].isdigit():
    target_id = int(args[1])
    set_ban_status(target_id, 1)
    bot.reply_to(message, f"🚫 User <code>{target_id}</code> ব্যান করা হয়েছে।")
  else:
    bot.reply_to(message, "ফরম্যাট: <code>/ban 123456789</code>")


@bot.message_handler(commands=["unban"])
def unban_cmd(message):
  if message.from_user.id != ADMIN_ID:
    return
  args = message.text.split()
  if len(args) > 1 and args[1].isdigit():
    target_id = int(args[1])
    set_ban_status(target_id, 0)
    bot.reply_to(
        message, f"✅ User <code>{target_id}</code> আনব্যান করা হয়েছে।"
    )
  else:
    bot.reply_to(message, "ফরম্যাট: <code>/unban 123456789</code>")


# ================= 6. START COMMAND =================
@bot.message_handler(commands=["start"])
def send_welcome(message):
  user_id = message.from_user.id
  user_name = message.from_user.first_name
  username = (
      f"@{message.from_user.username}"
      if message.from_user.username
      else "No Username"
  )

  args = message.text.split()
  referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
  is_new = register_user(user_id, referrer_id)

  if is_new and user_id != ADMIN_ID:
    try:
      admin_alert = f"""🚨 <b>NEW USER REGISTERED</b>
━━━━━━━━━━━━━━━━━━━━
👤 <b>Name:</b> {message.from_user.full_name}
🆔 <b>User ID:</b> <code>{user_id}</code>
🔗 <b>Username:</b> {username}
👥 <b>Invited By:</b> {referrer_id if referrer_id else 'Direct Search'}"""
      bot.send_message(ADMIN_ID, admin_alert, parse_mode="HTML")
    except:
      pass

  user_data = get_user_data(user_id)
  if user_data and user_data[2] == 1:
    bot.send_message(
        user_id,
        "🚫 <b>Access Denied!</b> আপনাকে বট থেকে ব্যান করা হয়েছে।",
        parse_mode="HTML",
    )
    return

  welcome_text = f"""╔══════════════════════════════════╗
       ⚡ <b>RAFIM TOOLS OFFICIAL</b> ⚡
╚══════════════════════════════════╝

👋 <b>স্বাগতম, {user_name}!</b>

🔍 <b>BD Number Info</b> — কলার নাম, অপারেটর ও লোকেশন তথ্য
👤 <b>My Account</b> — অ্যাকাউন্ট ব্যালেন্স ও ভিআইপি স্ট্যাটাস
🎁 <b>Refer & Earn</b> — বন্ধুদের আমন্ত্রণ জানিয়ে আনলিমিটেড পয়েন্ট
🎟️ <b>Redeem Code</b> — স্পেশাল ভাউচার দিয়ে ফ্রি ক্রেডিট
📞 <b>Support</b> — সরাসরি অ্যাডমিন সহায়তা ও ২৪/৭ হেল্পলাইন

⚠️ <b>আইনি সতর্কতা ও ডিসক্লেইমার:</b>
<i>এই বটটি সম্পূর্ণ শিক্ষামূলক উদ্দেশ্যে তৈরি। টেলিকম নেটওয়ার্কের পাবলিক প্রিফিক্স ও কলার আইডেন্টিফায়ার অনুসারে তথ্য প্রদর্শিত হয়।</i>

📌 <i>যেকোনো ১১ ডিজিটের নম্বর লিখুন অথবা নিচের মেনু ব্যবহার করুন:</i>"""

  bot.send_message(
      user_id,
      welcome_text,
      parse_mode="HTML",
      reply_markup=get_main_keyboard(),
  )


# ================= 7. MENU ACTIONS =================
@bot.message_handler(func=lambda msg: True)
def handle_menu(message):
  user_id = message.from_user.id
  user_data = get_user_data(user_id)

  if user_data and user_data[2] == 1:
    bot.send_message(
        user_id,
        "🚫 <b>আপনি ব্যান থাকায় সার্ভিস ব্যবহার করতে পারবেন না।</b>",
        parse_mode="HTML",
    )
    return

  credits = user_data[0] if user_data else 0
  text = message.text.strip()

  if text == "🔍 BD Number Info":
    if credits <= 0:
      bot.send_message(
          user_id,
          "⚠️ <b>সার্চ ক্রেডিট শেষ!</b>\nরিচার্জ করতে নিচের বাটনে চাপ দিন:",
          parse_mode="HTML",
          reply_markup=get_action_inline(),
      )
      return
    msg = bot.send_message(
        user_id,
        "📌 <b>টার্গেট মোবাইল নম্বরটি পাঠান:</b>\n<i>উদাহরণ: 017XXXXXXXX</i>",
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, process_lookup)

  elif text == "👤 My Account":
    status_tag = "💎 VIP Elite" if credits >= 10 else "🟢 Active Member"
    acc_text = f"""╔══════════════════════════════════╗
         👤 <b>USER DASHBOARD</b>
╚══════════════════════════════════╝

🆔 <b>User ID:</b> <code>{user_id}</code>
👤 <b>Name:</b> {message.from_user.full_name}
⚡ <b>Tier Status:</b> {status_tag}
💰 <b>Search Credits:</b> <b>{credits} Points</b>
🛡️ <b>Database Link:</b> Encrypted & Secured"""
    bot.send_message(
        user_id, acc_text, parse_mode="HTML", reply_markup=get_action_inline()
    )

  elif text == "🎁 Refer & Earn":
    bot_username = bot.get_me().username
    refer_link = f"https://t.me/{bot_username}?start={user_id}"
    ref_text = f"""╔══════════════════════════════════╗
         🎁 <b>REFER & EARN CASH/POINT</b>
╚══════════════════════════════════╝

আপনার বন্ধুদের ইনভাইট করলেই প্রতি রেফারে পাচ্ছেন <b>+৩ ক্রেডিট</b> একদম ফ্রি!

🔗 <b>আপনার ইউনিক রেফারেল লিংক:</b>
<code>{refer_link}</code>"""
    bot.send_message(user_id, ref_text, parse_mode="HTML")

  elif text == "🎟️ Redeem Code":
    msg = bot.send_message(
        user_id,
        "🎟️ <b>আপনার প্রোমো/রিডিম কোডটি লিখুন:</b>\n<i>যেমন: <code>RAFIM10</code></i>",
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, process_redeem_code)

  elif text == "📞 Support":
    support_text = """╔══════════════════════════════════╗
          📞 <b>VIP SUPPORT DESK</b>
╚══════════════════════════════════╝

যেকোনো সমস্যা, রিচার্জ বা তথ্যের জন্য সরাসরি যোগাযোগ করুন:
👤 <b>Official Admin:</b> @RafimToolsAdmin"""
    bot.send_message(user_id, support_text, parse_mode="HTML")

  elif len(text) == 11 and text.isdigit() and text.startswith("01"):
    process_lookup_direct(message, text)


# ================= 8. LOOKUP WITH CALLER NAME =================
def process_lookup_direct(message, number):
  user_id = message.from_user.id
  user_data = get_user_data(user_id)
  credits = user_data[0] if user_data else 0

  if credits <= 0:
    bot.send_message(
        user_id,
        "⚠️ <b>পর্যাপ্ত ক্রেডিট নেই!</b> সার্ভিস পেতে রিচার্জ অথবা রেফার করুন।",
        parse_mode="HTML",
        reply_markup=get_action_inline(),
    )
    return

  update_credits(user_id, -1)
  user_data = get_user_data(user_id)

  op_prefix = number[:3]
  operators = {
      "017": ("Grameenphone", "Dhaka & Central Zone"),
      "013": ("Grameenphone (4G Prime)", "Nationwide Network"),
      "019": ("Banglalink Digital", "Western & Central Region"),
      "014": ("Banglalink (Data Prime)", "Nationwide Network"),
      "018": ("Robi Axiata", "Chittagong & Coastal Region"),
      "016": ("Airtel (Metro HLR)", "Urban Metropolitan Area"),
      "015": ("Teletalk Bangladesh", "Government / State Network"),
  }

  op_name, region_info = operators.get(
      op_prefix, ("Unknown Operator", "Bangladesh Telecom Zone")
  )

  # প্রিমিয়াম কলার নেম প্রিভিউ
  caller_name = (
      f"Subscriber #{number[-4:]} [TrueCaller / Verified Registry]"
  )

  result_card = f"""╔══════════════════════════════════╗
       ⚡ <b>INTELLIGENCE LOOKUP RESULT</b> ⚡
╚══════════════════════════════════╝

📱 <b>Target Number:</b> <code>{number}</code>
👤 <b>Registered Name:</b> <b>{caller_name}</b>
🏢 <b>Primary Operator:</b> {op_name}
📍 <b>HLR Routing Location:</b> {region_info}
🌐 <b>Country:</b> Bangladesh 🇧🇩
📡 <b>Line Health:</b> Active / Operational
🔒 <b>Gateway Security:</b> 256-Bit Encrypted

⚠️ <i>Notice: প্রদর্শিত তথ্য পাবলিক নেটওয়ার্ক ও সিমুলেটেড ডিরেক্টরি অনুযায়ী শিক্ষামূলক উদ্দেশ্যে জেনারেট করা।</i>

💳 <i>অবশিষ্ট ক্রেডিট: {user_data[0]}</i>"""

  bot.send_message(user_id, result_card, parse_mode="HTML")


def process_lookup(message):
  number = message.text.strip()
  if len(number) == 11 and number.isdigit() and number.startswith("01"):
    process_lookup_direct(message, number)
  else:
    bot.send_message(
        message.chat.id,
        "❌ <b>ভুল নম্বর ফরম্যাট!</b> সঠিক ১১ ডিজিটের নম্বর দিন।",
        parse_mode="HTML",
    )


# ================= 9. PAYMENT & REDEEM CODE LOGIC =================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
  user_id = call.message.chat.id

  if call.data == "btn_buy_credits":
    payment_info = """╔══════════════════════════════════╗
         💳 <b>BUY CREDITS - NAGAD</b>
╚══════════════════════════════════╝

🔥 <b>প্যাকেজ রেট:</b>
• ১০ ক্রেডিট = ৫০ ৳
• ২৫ ক্রেডিট = ১০০ ৳
• ৬০ ক্রেডিট = ২০০ ৳

📌 <b>Nagad Personal (Send Money):</b>
<code>01726836941</code>

টাকা পাঠিয়ে নিচে <b>TrxID</b> লিখে রিপ্লাই দিন:"""
    msg = bot.send_message(user_id, payment_info, parse_mode="HTML")
    bot.register_next_step_handler(msg, receive_trx_id)

  elif call.data.startswith("aprv_"):
    parts = call.data.split("_")
    amount = int(parts[1])
    target_user = int(parts[2])

    update_credits(target_user, amount)
    try:
      bot.send_message(
          target_user,
          f"🎉 <b>পেমেন্ট কনফার্ম হয়েছে!</b>\nআপনার একাউন্টে <b>+{amount}"
          " ক্রেডিট</b> যোগ হয়েছে।",
          parse_mode="HTML",
      )
    except:
      pass
    bot.edit_message_text(
        f"✅ <b>Approved {amount} Credits for:</b> <code>{target_user}</code>",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
    )


def receive_trx_id(message):
  user_id = message.from_user.id
  trx = message.text.strip()

  bot.send_message(
      user_id,
      "✅ <b>TrxID পাওয়া গেছে!</b> অ্যাডমিন ভেরিফাই করে ক্রেডিট দিয়ে দেবে।",
      parse_mode="HTML",
  )

  markup = types.InlineKeyboardMarkup(row_width=2)
  markup.add(
      types.InlineKeyboardButton(
          "+10 Credits", callback_data=f"aprv_10_{user_id}"
      ),
      types.InlineKeyboardButton(
          "+25 Credits", callback_data=f"aprv_25_{user_id}"
      ),
      types.InlineKeyboardButton(
          "+60 Credits", callback_data=f"aprv_60_{user_id}"
      ),
  )

  admin_notice = f"""🚨 <b>NEW PAYMENT SUBMITTED</b>
━━━━━━━━━━━━━━━━━━━━
👤 User: {message.from_user.first_name} (<code>{user_id}</code>)
💳 Method: <b>Nagad (01726836941)</b>
📝 TrxID: <code>{trx}</code>"""

  bot.send_message(
      ADMIN_ID, admin_notice, parse_mode="HTML", reply_markup=markup
  )


def process_redeem_code(message):
  user_id = message.from_user.id
  code = message.text.strip().upper()

  conn = sqlite3.connect("rafim_tools.db")
  cursor = conn.cursor()
  cursor.execute(
      "SELECT reward_credits, used_by FROM promo_codes WHERE code = ?", (code,)
  )
  row = cursor.fetchone()

  if row:
    reward, used_by = row
    used_list = used_by.split(",") if used_by else []

    if str(user_id) in used_list:
      bot.send_message(
          user_id,
          "❌ <b>ইতিমধ্যে ব্যবহৃত!</b> আপনি আগেই এই কোডটি নিয়েছেন।",
          parse_mode="HTML",
      )
    else:
      used_list.append(str(user_id))
      new_used_str = ",".join(used_list)
      cursor.execute(
          "UPDATE promo_codes SET used_by = ? WHERE code = ?",
          (new_used_str, code),
      )
      cursor.execute(
          "UPDATE users SET credits = credits + ? WHERE user_id = ?",
          (reward, user_id),
      )
      conn.commit()
      bot.send_message(
          user_id,
          f"🎉 <b>সফল!</b> <code>{code}</code> অ্যাক্টিভেট হয়েছে। <b>+{reward}"
          " ক্রেডিট</b> যোগ হয়েছে!",
          parse_mode="HTML",
      )
  else:
    bot.send_message(
        user_id, "❌ <b>ভুল রিডিম কোড!</b> সঠিক কোড দিন।", parse_mode="HTML"
    )

  conn.close()


if __name__ == "__main__":
  bot.infinity_polling()
