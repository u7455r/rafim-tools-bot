import sqlite3
import telebot
from telebot import types

# Configurations
API_TOKEN = '8809150454:AAFVoJIP2RzwABlYAKcG9EtTnNA4nkfwwdU'  # @BotFather থেকে পাওয়া টোকেন
ADMIN_ID = 8298133943  # আপনার টেলিগ্রাম অ্যাডমিন আইডি

bot = telebot.TeleBot(API_TOKEN)


# Database Setup
def init_db():
  conn = sqlite3.connect('rafim_tools.db')
  cursor = conn.cursor()
  # User Table
  cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        credits INTEGER DEFAULT 3,
                        referred_by INTEGER,
                        is_banned INTEGER DEFAULT 0
                    )''')
  # Promo Code Table
  cursor.execute('''CREATE TABLE IF NOT EXISTS promo_codes (
                        code TEXT PRIMARY KEY,
                        reward_credits INTEGER,
                        used_by TEXT DEFAULT ''
                    )''')
  # Default Codes
  cursor.execute(
      "INSERT OR IGNORE INTO promo_codes (code, reward_credits) VALUES"
      " ('RAFIM10', 10)"
  )
  cursor.execute(
      "INSERT OR IGNORE INTO promo_codes (code, reward_credits) VALUES ('FREE5',"
      ' 5)'
  )
  conn.commit()
  conn.close()


init_db()


def get_user_data(user_id):
  conn = sqlite3.connect('rafim_tools.db')
  cursor = conn.cursor()
  cursor.execute(
      'SELECT credits, referred_by, is_banned FROM users WHERE user_id = ?',
      (user_id,),
  )
  row = cursor.fetchone()
  conn.close()
  return row


def register_user(user_id, referrer_id=None):
  conn = sqlite3.connect('rafim_tools.db')
  cursor = conn.cursor()
  cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
  is_new = cursor.fetchone() is None

  if is_new:
    cursor.execute(
        'INSERT INTO users (user_id, credits, referred_by, is_banned) VALUES'
        ' (?, ?, ?, 0)',
        (user_id, 3, referrer_id),
    )
    if referrer_id and referrer_id != user_id:
      cursor.execute(
          'UPDATE users SET credits = credits + 3 WHERE user_id = ?',
          (referrer_id,),
      )
      try:
        bot.send_message(
            referrer_id,
            '🎉 <b>New Referral Joined!</b>\nআপনার রেফারেল লিংকে একজন জয়েন করেছে।'
            ' <b>+3 Credits</b> যুক্ত হয়েছে!',
            parse_mode='HTML',
        )
      except:
        pass
    conn.commit()
  conn.close()
  return is_new


def update_credits(user_id, amount):
  conn = sqlite3.connect('rafim_tools.db')
  cursor = conn.cursor()
  cursor.execute(
      'UPDATE users SET credits = credits + ? WHERE user_id = ?',
      (amount, user_id),
  )
  conn.commit()
  conn.close()


def set_ban_status(user_id, status):
  conn = sqlite3.connect('rafim_tools.db')
  cursor = conn.cursor()
  cursor.execute(
      'UPDATE users SET is_banned = ? WHERE user_id = ?", (status, user_id)'
  )
  conn.commit()
  conn.close()


# Keyboards
def get_main_keyboard():
  markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
  btn1 = types.KeyboardButton('🔍 BD Number Info')
  btn2 = types.KeyboardButton('👤 My Account')
  btn3 = types.KeyboardButton('🎁 Refer & Earn')
  btn4 = types.KeyboardButton('📞 Support')
  markup.add(btn1, btn2, btn3, btn4)
  return markup


def get_action_inline():
  markup = types.InlineKeyboardMarkup(row_width=2)
  btn_buy = types.InlineKeyboardButton(
      '💳 Buy Credits (Nagad)', callback_data='btn_buy_credits'
  )
  btn_redeem = types.InlineKeyboardButton(
      '🎟️ Redeem Code', callback_data='btn_redeem_code'
  )
  markup.add(btn_buy, btn_redeem)
  return markup


# ================= ADMIN BAN / UNBAN =================
@bot.message_handler(commands=['ban'])
def ban_command(message):
  if message.from_user.id != ADMIN_ID:
    return
  args = message.text.split()
  if len(args) > 1 and args[1].isdigit():
    target_id = int(args[1])
    set_ban_status(target_id, 1)
    bot.reply_to(
        message,
        f'🚫 <b>User {target_id} কে সফলভাবে ব্যান করা হয়েছে!</b>',
        parse_mode='HTML',
    )
    try:
      bot.send_message(
          target_id,
          '❌ <b>আপনাকে অ্যাডমিন কর্তৃক ব্যান করা হয়েছে!</b>',
          parse_mode='HTML',
      )
    except:
      pass
  else:
    bot.reply_to(message, 'সঠিক ফরম্যাট: <code>/ban 123456789</code>')


@bot.message_handler(commands=['unban'])
def unban_command(message):
  if message.from_user.id != ADMIN_ID:
    return
  args = message.text.split()
  if len(args) > 1 and args[1].isdigit():
    target_id = int(args[1])
    set_ban_status(target_id, 0)
    bot.reply_to(
        message,
        f'✅ <b>User {target_id} কে আনব্যান করা হয়েছে!</b>',
        parse_mode='HTML',
    )
    try:
      bot.send_message(
          target_id,
          '🎉 <b>আপনার ব্যান তুলে নেওয়া হয়েছে। আপনি এখন বট ব্যবহার করতে পারবেন।</b>',
          parse_mode='HTML',
      )
    except:
      pass
  else:
    bot.reply_to(message, 'সঠিক ফরম্যাট: <code>/unban 123456789</code>')


# ================= START COMMAND =================
@bot.message_handler(commands=['start'])
def send_welcome(message):
  user_id = message.from_user.id
  user_name = message.from_user.first_name
  username = (
      f'@{message.from_user.username}'
      if message.from_user.username
      else 'No Username'
  )

  args = message.text.split()
  referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

  # ইউজার রেজিস্ট্রেশন ও অ্যাডমিন নোটিফিকেশন
  is_new = register_user(user_id, referrer_id)

  # নতুন ইউজার বট স্টার্ট করলেই অ্যাডমিনের কাছে অ্যালার্ট যাবে
  if is_new and user_id != ADMIN_ID:
    try:
      admin_alert = f"""🔔 <b>NEW USER JOINED!</b>
━━━━━━━━━━━━━━━━━━━━
👤 <b>Name:</b> {message.from_user.full_name}
🆔 <b>User ID:</b> <code>{user_id}</code>
🔗 <b>Username:</b> {username}
👥 <b>Referred By:</b> {referrer_id if referrer_id else 'Direct'}"""
      bot.send_message(ADMIN_ID, admin_alert, parse_mode='HTML')
    except:
      pass

  user_data = get_user_data(user_id)
  if user_data and user_data[2] == 1:
    bot.send_message(
        user_id,
        '❌ <b>আপনাকে এই বট থেকে ব্যান করা হয়েছে।</b>',
        parse_mode='HTML',
    )
    return

  welcome_text = f"""╭━━━〔 ⚡ <b>RAFIM TOOLS OFFICIAL</b> ⚡ 〕━━━╮

👋 <b>স্বাগতম, {user_name}!</b>

🔍 <b>BD Number Info</b> — বাংলাদেশি নম্বরের প্রিফিক্স ও অপারেটর তথ্য
👤 <b>My Account</b> — প্রোফাইল স্ট্যাটাস ও পয়েন্ট
🎁 <b>Refer & Earn</b> — বন্ধুদের ইনভাইট করে ফ্রি পয়েন্ট অর্জন
📞 <b>Support</b> — যেকোনো প্রয়োজনে সরাসরি সহায়তা

⚠️ <b>Disclaimer & নোটিশ:</b>
<i>এই বটটি কেবল প্রোগ্রামিং প্রজেক্ট ও শিক্ষামূলক প্রদর্শনের (Educational Purpose) উদ্দেশ্যে তৈরি করা হয়েছে। এটি কোনো সরকারি/টেলিকম ডেটাবেজ নয় এবং এতে কারো ব্যক্তিগত সংবেদনশীল তথ্য সংরক্ষণ করা হয় না।</i>

📌 <i>নিচের মেনু ব্যবহার করুন অথবা ১১ ডিজিটের নম্বর লিখুন:</i>
╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"""

  bot.send_message(
      user_id,
      welcome_text,
      parse_mode='HTML',
      reply_markup=get_main_keyboard(),
  )


# ================= MENU ACTIONS =================
@bot.message_handler(func=lambda msg: True)
def handle_menu_click(message):
  user_id = message.from_user.id
  user_data = get_user_data(user_id)

  if user_data and user_data[2] == 1:
    bot.send_message(
        user_id,
        '❌ <b>আপনি ব্যান থাকায় বট ব্যবহার করতে পারবেন না।</b>',
        parse_mode='HTML',
    )
    return

  credits = user_data[0] if user_data else 0
  text = message.text.strip()

  if text == '🔍 BD Number Info':
    if credits <= 0:
      bot.send_message(
          user_id,
          '⚠️ <b>সার্চ লিমিট শেষ!</b>\nপয়েন্ট রিচার্জ করতে নিচের বাটন চাপুন:',
          parse_mode='HTML',
          reply_markup=get_action_inline(),
      )
      return
    msg = bot.send_message(
        user_id,
        '📌 <b>১১ ডিজিটের মোবাইল নম্বরটি পাঠান:</b>\n<i>যেমন: 017XXXXXXXX</i>',
        parse_mode='HTML',
    )
    bot.register_next_step_handler(msg, process_lookup)

  elif text == '👤 My Account':
    status_tag = '💎 VIP User' if credits >= 10 else '🟢 Active Member'
    acc_text = f"""╭━━━〔 👤 <b>USER DASHBOARD</b> 〕━━━╮

🆔 <b>User ID:</b> <code>{user_id}</code>
👤 <b>Name:</b> {message.from_user.full_name}
⚡ <b>Status:</b> {status_tag}
💰 <b>Available Credits:</b> {credits} Points

╰━━━━━━━━━━━━━━━━━━━━━━━━━╯"""
    bot.send_message(
        user_id, acc_text, parse_mode='HTML', reply_markup=get_action_inline()
    )

  elif text == '🎁 Refer & Earn':
    bot_username = bot.get_me().username
    refer_link = f'https://t.me/{bot_username}?start={user_id}'
    ref_text = f"""╭━━━〔 🎁 <b>REFER & REWARD</b> 〕━━━╮

আপনার বন্ধুদের নিচের লিংকে ইনভাইট করুন। কেউ জয়েন করলেই আপনি পাবেন <b>+৩ ক্রেডিট</b> একদম ফ্রি!

🔗 <b>আপনার পার্সোনাল রেফার লিংক:</b>
<code>{refer_link}</code>

╰━━━━━━━━━━━━━━━━━━━━━━━━━╯"""
    bot.send_message(user_id, ref_text, parse_mode='HTML')

  elif text == '📞 Support':
    support_text = """╭━━━〔 📞 <b>CUSTOMER SUPPORT</b> 〕━━━╮

যেকোনো সমস্যা বা সহায়তার জন্য সরাসরি যোগাযোগ করুন:
👤 <b>Official Admin:</b> @RafimToolsAdmin

⏰ <i>Active Hours: 10:00 AM - 11:00 PM</i>
╰━━━━━━━━━━━━━━━━━━━━━━━━━╯"""
    bot.send_message(user_id, support_text, parse_mode='HTML')

  elif len(text) == 11 and text.isdigit() and text.startswith('01'):
    process_lookup_direct(message, text)


# ================= CALLBACKS =================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
  user_id = call.message.chat.id
  user_data = get_user_data(user_id)
  if user_data and user_data[2] == 1:
    bot.answer_callback_query(call.id, 'আপনি ব্যান আছেন!', show_alert=True)
    return

  if call.data == 'btn_buy_credits':
    payment_info = """╭━━━〔 💳 <b>BUY CREDITS - NAGAD</b> 〕━━━╮

🔥 <b>প্যাকেজসমূহ:</b>
• ১০ ক্রেডিট = ৫০ ৳
• ২৫ ক্রেডিট = ১০০ ৳
• ৬০ ক্রেডিট = ২০০ ৳

📌 <b>Nagad Personal (Send Money):</b>
<code>01726836941</code>

টাকা পাঠানোর পর <b>TrxID</b> নিচে লিখে সেন্ড করুন:
╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"""
    msg = bot.send_message(user_id, payment_info, parse_mode='HTML')
    bot.register_next_step_handler(msg, receive_trx_id)

  elif call.data == 'btn_redeem_code':
    msg = bot.send_message(
        user_id,
        '🎟️ <b>আপনার রিডিম কোডটি পাঠান:</b>\n<i>যেমন:'
        ' <code>RAFIM10</code></i>',
        parse_mode='HTML',
    )
    bot.register_next_step_handler(msg, process_redeem_code)

  elif call.data.startswith('aprv_'):
    parts = call.data.split('_')
    amount = int(parts[1])
    target_user = int(parts[2])

    update_credits(target_user, amount)
    try:
      bot.send_message(
          target_user,
          f'🎉 <b>পেমেন্ট সফল হয়েছে!</b>\nআপনার একাউন্টে <b>+{amount} ক্রেডিট</b>'
          ' যোগ করা হয়েছে।',
          parse_mode='HTML',
      )
    except:
      pass
    bot.edit_message_text(
        f'✅ <b>Approved {amount} Credits for:</b> <code>{target_user}</code>',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode='HTML',
    )


# ================= LOOKUP LOGIC =================
def process_lookup_direct(message, number):
  user_id = message.from_user.id
  user_data = get_user_data(user_id)
  credits = user_data[0] if user_data else 0

  if credits <= 0:
    bot.send_message(
        user_id,
        '⚠️ <b>সার্চ ক্রেডিট শেষ!</b> ক্রেডিট যোগ করতে রিচার্জ বা রেফার করুন।',
        parse_mode='HTML',
        reply_markup=get_action_inline(),
    )
    return

  update_credits(user_id, -1)
  user_data = get_user_data(user_id)

  op_prefix = number[:3]
  operators = {
      '017': ('Grameenphone', 'Dhaka & Central Zone'),
      '013': ('Grameenphone (New)', 'Nationwide Zone'),
      '019': ('Banglalink Digital', 'Western & Central Region'),
      '014': ('Banglalink (New)', 'Nationwide Zone'),
      '018': ('Robi Axiata', 'Chittagong & Nationwide'),
      '016': ('Airtel (Robi)', 'Metropolitan Zone'),
      '015': ('Teletalk Bangladesh', 'Government / State Network'),
  }

  op_name, region_info = operators.get(
      op_prefix, ('Unknown Operator', 'Bangladesh Zone')
  )

  result_card = f"""╭━━━〔 ⚡ <b>NUMBER DETAILS</b> ⚡ 〕━━━╮

📱 <b>Target Number:</b> <code>{number}</code>
🏢 <b>Operator:</b> {op_name}
📍 <b>HLR Routing Location:</b> {region_info}
🌐 <b>Country:</b> Bangladesh 🇧🇩
📡 <b>Network Status:</b> Operational / Active

🔒 <i>Disclaimer: তথ্যটি শিক্ষামূলক উদ্দেশ্যে প্রদর্শিত এবং পাবলিক নেটওয়ার্ক প্রিফিক্স অনুযায়ী সিমুলেটেড।</i>

💳 <i>অবশিষ্ট ক্রেডিট: {user_data[0]}</i>
╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"""

  bot.send_message(user_id, result_card, parse_mode='HTML')


def process_lookup(message):
  number = message.text.strip()
  if len(number) == 11 and number.isdigit() and number.startswith('01'):
    process_lookup_direct(message, number)
  else:
    bot.send_message(
        message.chat.id,
        '❌ <b>ভুল নম্বর ফরম্যাট!</b> সঠিক ১১ ডিজিটের নম্বর দিন।',
        parse_mode='HTML',
    )


# ================= PAYMENT HANDLER =================
def receive_trx_id(message):
  user_id = message.from_user.id
  trx = message.text.strip()

  bot.send_message(
      user_id,
      '✅ <b>TrxID গৃহীত হয়েছে!</b> অ্যাডমিন যাচাই করে ক্রেডিট যোগ করে দেবেন।',
      parse_mode='HTML',
  )

  markup = types.InlineKeyboardMarkup(row_width=2)
  markup.add(
      types.InlineKeyboardButton(
          '+10 Credits', callback_data=f'aprv_10_{user_id}'
      ),
      types.InlineKeyboardButton(
          '+25 Credits', callback_data=f'aprv_25_{user_id}'
      ),
      types.InlineKeyboardButton(
          '+60 Credits', callback_data=f'aprv_60_{user_id}'
      ),
  )

  admin_notice = f"""🚨 <b>NEW PAYMENT SUBMITTED</b>
━━━━━━━━━━━━━━━━━━━━
👤 User: {message.from_user.first_name} (<code>{user_id}</code>)
💳 Method: <b>Nagad (01726836941)</b>
📝 TrxID: <code>{trx}</code>

অ্যাপ্রুভ করতে বাটন চাপুন:"""

  bot.send_message(
      ADMIN_ID, admin_notice, parse_mode='HTML', reply_markup=markup
  )


# ================= REDEEM CODE HANDLER =================
def process_redeem_code(message):
  user_id = message.from_user.id
  code = message.text.strip().upper()

  conn = sqlite3.connect('rafim_tools.db')
  cursor = conn.cursor()
  cursor.execute(
      'SELECT reward_credits, used_by FROM promo_codes WHERE code = ?', (code,)
  )
  row = cursor.fetchone()

  if row:
    reward, used_by = row
    used_list = used_by.split(',') if used_by else []

    if str(user_id) in used_list:
      bot.send_message(
          user_id,
          '❌ <b>ইতিমধ্যে ব্যবহৃত!</b> আপনি আগেই এই কোডটি নিয়েছেন।',
          parse_mode='HTML',
      )
    else:
      used_list.append(str(user_id))
      new_used_str = ','.join(used_list)
      cursor.execute(
          'UPDATE promo_codes SET used_by = ? WHERE code = ?',
          (new_used_str, code),
      )
      cursor.execute(
          'UPDATE users SET credits = credits + ? WHERE user_id = ?',
          (reward, user_id),
      )
      conn.commit()
      bot.send_message(
          user_id,
          f'🎉 <b>সফল!</b> <code>{code}</code> কোড থেকে <b>+{reward} ক্রেডিট</b>'
          ' যোগ করা হয়েছে!',
          parse_mode='HTML',
      )
  else:
    bot.send_message(
        user_id, '❌ <b>ভুল কোড!</b> সঠিক রিডিম কোড দিন।', parse_mode='HTML'
    )

  conn.close()


if __name__ == '__main__':
  bot.infinity_polling()
