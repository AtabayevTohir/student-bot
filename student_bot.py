"""
=======================================================
  STUDENT ASSISTANT TELEGRAM BOT  🤖
=======================================================
  SETUP INSTRUCTIONS:
  1. Install Python 3.9+ from https://python.org
  2. Open terminal / command prompt in this folder
  3. Run:  pip install pyTelegramBotAPI google-generativeai schedule
  4. PASTE YOUR KEYS in the two lines below (lines 18-19)
  5. Run:  python student_bot.py
=======================================================
"""
import os
# ─── PASTE YOUR KEYS HERE ───────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY")
# ────────────────────────────────────────────────────

import sqlite3
import json
import threading
import time
from datetime import datetime, timedelta
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import google.generativeai as genai

# ─── Setup Gemini AI ────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",  # free model
    system_instruction=(
        "You are a helpful student assistant. "
        "Help students with their studies, explain concepts clearly, "
        "give study tips, and be encouraging. Keep replies concise."
    )
)

# ─── Setup Telegram Bot ─────────────────────────────
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ─── Database Setup ─────────────────────────────────
def init_db():
    conn = sqlite3.connect("tasks.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT    NOT NULL,
            title       TEXT    NOT NULL,
            subject     TEXT    NOT NULL,
            deadline    TEXT    NOT NULL,
            done        INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

def db():
    """Returns a fresh database connection."""
    return sqlite3.connect("tasks.db")

# ─── Chat history (stored in memory per user) ───────
chat_histories = {}  # { user_id: [{"role": ..., "parts": ...}, ...] }

# ─── Waiting-for-input tracker ──────────────────────
waiting_for = {}  # { user_id: "addtask" }


# ════════════════════════════════════════════════════
#   COMMANDS
# ════════════════════════════════════════════════════

@bot.message_handler(commands=["start", "help"])
def main_keyboard():
    keyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, persistent=True)
    keyboard.row("📋 Add Task")
    keyboard.row("📄 My Tasks", "📊 Report")
    keyboard.row("✅ Mark Done", "🗑 Clear All")
    keyboard.row("🤖 AI Chat")
    return keyboard

@bot.message_handler(commands=["start", "help"])
def cmd_start(msg):
    name = msg.from_user.first_name
    bot.send_message(
        msg.chat.id,
        f"👋 *Hi {name}! I'm your Student Assistant Bot.*\n\n"
        "Use the buttons below to get started!",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["addtask"])
def cmd_addtask(msg):
    waiting_for[msg.chat.id] = "addtask"
    bot.send_message(
        msg.chat.id,
        "📝 *Add a new task*\n\n"
        "Send your task in this format:\n"
        "`Task title | Subject | YYYY-MM-DD`\n\n"
        "📌 *Example:*\n"
        "`Chapter 5 Essay | English | 2024-12-20`\n\n"
        "_Type /cancel to go back._",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["tasks"])
def cmd_tasks(msg):
    conn = db()
    tasks = conn.execute(
        "SELECT id, title, subject, deadline FROM tasks "
        "WHERE user_id=? AND done=0 ORDER BY deadline ASC",
        (str(msg.chat.id),)
    ).fetchall()
    conn.close()

    if not tasks:
        bot.send_message(msg.chat.id, "🎉 *No pending tasks!* You're all caught up.", parse_mode="Markdown")
        return

    text = "📋 *Your Pending Tasks:*\n\n"
    today = datetime.now().date()
    for i, (tid, title, subject, deadline) in enumerate(tasks, 1):
        try:
            dl = datetime.strptime(deadline, "%Y-%m-%d").date()
            days_left = (dl - today).days
            if days_left < 0:
                icon = "🔴"
                note = f"  _(overdue by {abs(days_left)} day(s))_"
            elif days_left == 0:
                icon = "🟠"
                note = "  _(due today!)_"
            elif days_left <= 2:
                icon = "🟡"
                note = f"  _({days_left} day(s) left)_"
            else:
                icon = "🟢"
                note = f"  _({days_left} days left)_"
        except:
            icon = "🟡"
            note = ""

        text += f"{i}. {icon} *{title}*\n   📚 {subject} | ⏰ {deadline}{note}\n\n"

    bot.send_message(msg.chat.id, text, parse_mode="Markdown")


@bot.message_handler(commands=["done"])
def cmd_done(msg):
    conn = db()
    tasks = conn.execute(
        "SELECT id, title, subject FROM tasks WHERE user_id=? AND done=0",
        (str(msg.chat.id),)
    ).fetchall()
    conn.close()

    if not tasks:
        bot.send_message(msg.chat.id, "No pending tasks to mark as done! 🎉")
        return

    keyboard = InlineKeyboardMarkup()
    for tid, title, subject in tasks:
        keyboard.add(InlineKeyboardButton(
            text=f"✓  {title}  ({subject})",
            callback_data=f"done_{tid}"
        ))
    keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data="cancel"))

    bot.send_message(msg.chat.id, "✅ *Which task did you complete?*", reply_markup=keyboard, parse_mode="Markdown")


@bot.message_handler(commands=["report"])
def cmd_report(msg):
    uid = str(msg.chat.id)
    conn = db()

    done_week = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 "
        "AND created_at >= datetime('now', '-7 days')",
        (uid,)
    ).fetchone()[0]

    pending = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0", (uid,)
    ).fetchone()[0]

    overdue = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0 "
        "AND deadline < date('now')",
        (uid,)
    ).fetchone()[0]

    total_ever = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=?", (uid,)
    ).fetchone()[0]

    total_done = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1", (uid,)
    ).fetchone()[0]

    conn.close()

    # Progress bar
    total = done_week + pending
    pct = round((done_week / total) * 100) if total > 0 else 0
    filled = round(pct / 10)
    bar = "█" * filled + "░" * (10 - filled)

    mood = "🌟 Amazing work! Keep it up!" if pct >= 80 \
        else "💪 Good progress! Stay focused!" if pct >= 50 \
        else "📚 Time to catch up — you've got this!"

    bot.send_message(
        msg.chat.id,
        f"📊 *Your Weekly Report*\n"
        f"{'─' * 28}\n\n"
        f"This week's progress:\n"
        f"`[{bar}]` {pct}%\n\n"
        f"✅ Completed this week: *{done_week}*\n"
        f"🟡 Still pending:       *{pending}*\n"
        f"🔴 Overdue:             *{overdue}*\n\n"
        f"📈 All time: *{total_done}/{total_ever}* tasks done\n\n"
        f"{mood}",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["chat"])
def cmd_chat(msg):
    text = msg.text.replace("/chat", "").strip()
    if not text:
        bot.send_message(
            msg.chat.id,
            "🤖 *AI Chat*\n\nUsage: `/chat your question`\n\n"
            "📌 Examples:\n"
            "`/chat explain Newton's second law`\n"
            "`/chat give me 3 tips to study better`\n"
            "`/chat what is the difference between mitosis and meiosis`",
            parse_mode="Markdown"
        )
        return
    ask_ai(msg.chat.id, text)


@bot.message_handler(commands=["clear"])
def cmd_clear(msg):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("Yes, delete all ⚠️", callback_data="confirm_clear"),
        InlineKeyboardButton("No, keep them ✅", callback_data="cancel")
    )
    bot.send_message(msg.chat.id, "⚠️ Are you sure you want to delete *all* your tasks?",
                     reply_markup=keyboard, parse_mode="Markdown")


@bot.message_handler(commands=["cancel"])
def cmd_cancel(msg):
    waiting_for.pop(msg.chat.id, None)
    bot.send_message(msg.chat.id, "Cancelled. ✋ Use /help to see all commands.")


# ════════════════════════════════════════════════════
#   BUTTON CALLBACKS
# ════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: True)
def handle_buttons(call):
    bot.answer_callback_query(call.id)

    if call.data.startswith("done_"):
        task_id = call.data.replace("done_", "")
        conn = db()
        task = conn.execute("SELECT title FROM tasks WHERE id=?", (task_id,)).fetchone()
        conn.execute("UPDATE tasks SET done=1 WHERE id=?", (task_id,))
        conn.commit()
        conn.close()
        title = task[0] if task else "Task"
        bot.edit_message_text(
            f"✅ *'{title}'* marked as complete! 🎉\nGreat work — keep it up!",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )

    elif call.data == "confirm_clear":
        conn = db()
        conn.execute("DELETE FROM tasks WHERE user_id=?", (str(call.message.chat.id),))
        conn.commit()
        conn.close()
        bot.edit_message_text("🗑 All tasks deleted.", chat_id=call.message.chat.id,
                              message_id=call.message.message_id)

    elif call.data == "cancel":
        bot.edit_message_text("Cancelled. ✋", chat_id=call.message.chat.id,
                              message_id=call.message.message_id)
    
    elif call.data == "btn_addtask":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        cmd_addtask(call.message)   

    elif call.data == "btn_tasks":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        cmd_tasks(call.message)

    elif call.data == "btn_done":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        cmd_done(call.message)

    elif call.data == "btn_report":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        cmd_report(call.message)

    elif call.data == "btn_chat":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(
            call.message.chat.id,
            "🤖 *AI Chat*\n\nJust type any message and I'll answer!\n\n"
            "📌 Examples:\n"
            "• _explain Newton's second law_\n"
            "• _give me 3 tips to study better_\n"
            "• _what is the difference between mitosis and meiosis_",
            parse_mode="Markdown"
        )

    elif call.data == "btn_clear":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        cmd_clear(call.message)


# ════════════════════════════════════════════════════
#   FREE-TEXT MESSAGES (handles /addtask input + AI)
# ════════════════════════════════════════════════════

@bot.message_handler(func=lambda msg: True)
def handle_text(msg):
    uid = msg.chat.id
    text = msg.text

    # Button taps
    if text == "📋 Add Task":
        cmd_addtask(msg)
        return
    if text == "📄 My Tasks":
        cmd_tasks(msg)
        return
    if text == "✅ Mark Done":
        cmd_done(msg)
        return
    if text == "📊 Report":
        cmd_report(msg)
        return
    if text == "🗑 Clear All":
        cmd_clear(msg)
        return
    if text == "🤖 AI Chat":
        bot.send_message(
            uid,
            "🤖 Just type your question and I'll answer!",
            reply_markup=main_keyboard()
        )
        return

    # If user is entering a task
    if waiting_for.get(uid) == "addtask":
        waiting_for.pop(uid)
        parts = [p.strip() for p in msg.text.split("|")]
        if len(parts) < 3:
            bot.send_message(uid, "❌ Wrong format. Please use:\n`Title | Subject | YYYY-MM-DD`\n\nTry again.", parse_mode="Markdown")
            return
        title, subject, deadline = parts[0], parts[1], parts[2]
        try:
            datetime.strptime(deadline, "%Y-%m-%d")
        except ValueError:
            bot.send_message(uid, "❌ Invalid date. Use `YYYY-MM-DD`.\n\nTry again.", parse_mode="Markdown")
            return
        conn = db()
        conn.execute(
            "INSERT INTO tasks (user_id, title, subject, deadline) VALUES (?, ?, ?, ?)",
            (str(uid), title, subject, deadline)
        )
        conn.commit()
        conn.close()
        bot.send_message(
            uid,
            f"✅ *Task added!*\n\n"
            f"📌 {title}\n"
            f"📚 Subject: {subject}\n"
            f"⏰ Deadline: {deadline}",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
        return

    # Otherwise AI chat
    ask_ai(uid, msg.text)

    # Otherwise, treat as AI chat
    ask_ai(uid, msg.text)


# ════════════════════════════════════════════════════
#   AI HELPER
# ════════════════════════════════════════════════════

def ask_ai(chat_id, user_message):
    bot.send_chat_action(chat_id, "typing")
    uid = str(chat_id)

    try:
        # Build or continue chat history
        if uid not in chat_histories:
            chat_histories[uid] = []

        chat = ai_model.start_chat(history=chat_histories[uid])
        response = chat.send_message(user_message)
        reply = response.text

        # Save to history (keep last 20 messages to stay within limits)
        chat_histories[uid].append({"role": "user",  "parts": [user_message]})
        chat_histories[uid].append({"role": "model", "parts": [reply]})
        if len(chat_histories[uid]) > 20:
            chat_histories[uid] = chat_histories[uid][-20:]

        # Telegram max message length is 4096 chars
        if len(reply) > 4000:
            reply = reply[:4000] + "\n\n_[Reply trimmed — ask me to continue]_"

        bot.send_message(chat_id, f"🤖 {reply}", parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"❌ AI error: {str(e)[:200]}\n\nPlease try again.")


# ════════════════════════════════════════════════════
#   DAILY REMINDER (runs every morning at 8:00 AM)
# ════════════════════════════════════════════════════

def send_daily_reminders():
    conn = db()
    users = conn.execute("SELECT DISTINCT user_id FROM tasks WHERE done=0").fetchall()
    for (uid,) in users:
        overdue = conn.execute(
            "SELECT title FROM tasks WHERE user_id=? AND done=0 AND deadline < date('now')",
            (uid,)
        ).fetchall()
        due_soon = conn.execute(
            "SELECT title, deadline FROM tasks WHERE user_id=? AND done=0 "
            "AND deadline BETWEEN date('now') AND date('now', '+2 days')",
            (uid,)
        ).fetchall()

        msg_parts = ["📢 *Good morning! Daily task reminder:*\n"]
        if overdue:
            msg_parts.append(f"🔴 *Overdue ({len(overdue)}):*")
            for (t,) in overdue:
                msg_parts.append(f"  • {t}")
        if due_soon:
            msg_parts.append(f"\n⏰ *Due within 2 days ({len(due_soon)}):*")
            for (t, dl) in due_soon:
                msg_parts.append(f"  • {t}  _{dl}_")

        if overdue or due_soon:
            msg_parts.append("\nUse /tasks for full list or /done to mark complete.")
            try:
                bot.send_message(uid, "\n".join(msg_parts), parse_mode="Markdown")
            except:
                pass  # user may have blocked the bot
    conn.close()


def reminder_loop():
    """Check every minute if it's 8:00 AM and send reminders."""
    sent_today = None
    while True:
        now = datetime.now()
        today = now.date()
        if now.hour == 8 and now.minute == 0 and sent_today != today:
            send_daily_reminders()
            sent_today = today
        time.sleep(60)


# ════════════════════════════════════════════════════
#   START THE BOT
# ════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    print("✅ Database ready.")

    # Start reminder loop in a background thread
    reminder_thread = threading.Thread(target=reminder_loop, daemon=True)
    reminder_thread.start()
    print("⏰ Daily reminder loop started.")

    print("🤖 Student bot is running! Press Ctrl+C to stop.\n")
    bot.infinity_polling()