import os
import subprocess
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from bot.auth import is_allowed
from bot.services import SERVICES

def sh(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    return out.strip()

async def cmd_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not is_allowed(update.effective_chat.id):
        return
    kb = [[InlineKeyboardButton(s.title, callback_data=f"svc:{s.key}")] for s in SERVICES.values()]
    await update.message.reply_text("Скрипты:", reply_markup=InlineKeyboardMarkup(kb))

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.message or not q.message.chat:
        return
    if not is_allowed(q.message.chat.id):
        await q.answer("No access", show_alert=True)
        return
    await q.answer()
    data = q.data or ""

    if data == "back":
        kb = [[InlineKeyboardButton(s.title, callback_data=f"svc:{s.key}")] for s in SERVICES.values()]
        await q.edit_message_text("Скрипты:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("svc:"):
        key = data.split(":", 1)[1]
        s = SERVICES.get(key)
        if not s:
            await q.edit_message_text("Неизвестно")
            return
        kb = [
            [InlineKeyboardButton("▶️ Start", callback_data=f"act:start:{key}"),
             InlineKeyboardButton("⏹ Stop", callback_data=f"act:stop:{key}")],
            [InlineKeyboardButton("✅ Status", callback_data=f"act:status:{key}"),
             InlineKeyboardButton("📜 Logs(80)", callback_data=f"act:logs:{key}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
        ]
        await q.edit_message_text(f"Выбран: {s.title}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("act:"):
        _, act, key = data.split(":", 2)
        s = SERVICES.get(key)
        if not s:
            await q.edit_message_text("Неизвестно")
            return

        if act == "start":
            out = sh(["systemctl", "start", s.unit])
            await q.edit_message_text(out or "OK")
            return
        if act == "stop":
            out = sh(["systemctl", "stop", s.unit])
            await q.edit_message_text(out or "OK")
            return
        if act == "status":
            out = sh(["systemctl", "status", s.unit, "--no-pager", "-n", "30"])
            await q.edit_message_text(f"```\n{out[-3500:]}\n```", parse_mode="Markdown")
            return
        if act == "logs":
            out = sh(["journalctl", "-u", s.unit, "--no-pager", "-n", "80"])
            await q.edit_message_text(f"```\n{out[-3500:]}\n```", parse_mode="Markdown")
            return

def main():
    load_dotenv()
    token = os.environ["TG_BOT_TOKEN"].strip()
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("api", cmd_api))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.run_polling()

if __name__ == "__main__":
    main()
