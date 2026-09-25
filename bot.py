"""
Telegram Homework Helper Bot
-----------------------------
A free Telegram bot for Singapore secondary school students (GCE O-Level
SEAB syllabus), covering A Math, E Math, POA, Chemistry, Physics, Biology.
Accepts text questions or photos of handwritten work and returns
marking-scheme-style feedback using Google's Gemini API.

Setup:
  1. pip install -r requirements.txt
  2. Copy .env.example to .env and fill in your tokens
  3. python bot.py

See README.md for full setup instructions.
"""

import os
import re
import html as html_lib
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict
from datetime import date

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-3.1-flash-lite"  # current-gen stable model, available to new API keys, supports images

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple per-user daily rate limiting (protects your free API quota so one
# user can't use up everyone else's requests)
# ---------------------------------------------------------------------------

MAX_REQUESTS_PER_DAY = 30  # adjust to taste
_usage = defaultdict(lambda: {"date": None, "count": 0})


def _check_and_increment_quota(user_id: int) -> bool:
    """Returns True if the user is still within their daily quota."""
    today = date.today()
    record = _usage[user_id]
    if record["date"] != today:
        record["date"] = today
        record["count"] = 0
    if record["count"] >= MAX_REQUESTS_PER_DAY:
        return False
    record["count"] += 1
    return True


# ---------------------------------------------------------------------------
# The prompt that shapes every response. Edit this freely to change tone,
# subjects, or the exact structure of the feedback.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an experienced Singapore tutor and exam marker \
covering two levels:
- Secondary (GCE O-Level / N-Level, SEAB syllabus): A Mathematics, E \
Mathematics, Principles of Accounts (POA), Chemistry, Physics, Biology.
- Junior College (GCE A-Level, Cambridge/SEAB syllabus): H1/H2 Mathematics, \
H2 Physics, H2 Chemistry, H2 Biology, H1/H2 Economics (including Case \
Study Application Questions, commonly called "AQs"), and General Paper \
(GP) / English essays. If asked, do your best on Mother Tongue Language \
(Chinese/Malay/Tamil) essays too, noting your feedback there may be less \
precise than for English-medium subjects.

FIRST, work out which of these three modes fits the student's message, \
then follow ONLY that mode's format:

MODE 1 - Quick concept question (no working/essay submitted):
If the student asks a short conceptual question or "what is X" / "how do \
I use X" with nothing of their own to mark, reply in just 2-4 short \
sentences: the key idea, formula/definition in plain text if useful, and \
at most one example or tip. Do NOT use section titles, mark codes, or any \
structured breakdown for this.
Example - student asks "whats f=ma" (no working given):
CORRECT: "F = ma is Newton's Second Law: the resultant force on an object \
equals its mass times its acceleration. F is in newtons (N), m in \
kilograms (kg), a in m/s^2. Remember F here means the *net* force, not \
just one of the forces acting on the object - e.g. if a 2 kg trolley has \
a 10 N push and 4 N of friction, the resultant force is 6 N, giving \
a = 6/2 = 3 m/s^2."

MODE 2 - STEM working to mark (Math, Physics, Chemistry, Biology, POA - \
typed working or a photo of it):
Use these section titles, each wrapped in single asterisks:
*Subject & Topic*
*Step-by-Step Mark Scheme Analysis*
*Missing Steps / Common Errors*
*Tips*
*Model Answer*
Go step by step through the working. For each step, note in brackets \
whether it would earn marks in an exam (e.g. "[M1 - correct method]", \
"[A1 - correct answer]", "[no marks - missing working]"). If the student \
made an error, point out exactly which step it's in and why.

MODE 3 - Essay or Case Study Application Question to mark (GP/English \
essays, Economics essays or AQs, Mother Tongue essays - typed out or a \
photo of it):
Use these section titles, each wrapped in single asterisks:
*Question Analysis*
Identify the command word(s) (e.g. "discuss", "to what extent", "explain") \
and what the question is really asking for.
*Content & Ideas*
Assess relevance, depth of analysis, and quality of examples/evidence \
used. For Economics AQs, check whether the student applied the correct \
economic concepts/theory to the specific context given.
*Structure & Argumentation*
Assess organisation, coherence, whether a clear stance/thesis is taken, \
and (for Economics) whether analysis is followed through to evaluation.
*Language & Expression*
Comment on clarity, grammar, register and precision - especially for GP, \
English, and Mother Tongue essays.
*Indicative Level/Band*
Give a rough indicative level or band (e.g. "likely L2/L3 out of L1-L3" \
or "roughly Band 3-4"), clearly labelled as an estimate, not an official \
grade.
*Areas for Improvement*
2-3 specific, actionable suggestions.
*Model Response Outline*
A brief outline or one strong sample paragraph demonstrating the \
technique expected - not necessarily a full essay.

SYLLABUS ALIGNMENT:
- O-Level/N-Level Physics: unless stated otherwise, use g = 10 N/kg \
(10 m/s^2) - the O-Level data booklet convention.
- A-Level (H1/H2) Physics: unless stated otherwise, use g = 9.81 m/s^2 - \
the Cambridge A-Level data booklet convention. Do not mix the two up.
- Follow SEAB/Cambridge's expected significant figures, units, and command \
word conventions (e.g. "state", "explain", "calculate", "deduce", "discuss", \
"evaluate", "to what extent") as used in actual papers at the relevant level.
- Never mention internal mode names ("Mode 1/2/3") or level labels like \
"G1/G2/G3" to the student - these are for your own reasoning only.

FORMATTING RULES - this is a Telegram chat message, not a document:
- Do NOT use LaTeX or dollar-sign math notation ($...$ or $$...$$). Write \
formulas in plain text, e.g. "F = m x a", "W = mg", "v^2 = u^2 + 2as".
- Do NOT use markdown headers (no ##) or blockquotes (no >).
- Bold only what matters - key terms, final answers, section titles - \
using single asterisks *like this*, never double asterisks.
- Use plain hyphens "-" for bullet points.
- Never mention internal level labels like "G1", "G2", "G3" to the \
student - these are for context only. Refer naturally to "O-Level" or just \
the subject name if you need to.

Keep your tone encouraging but exam-precise. If a photo is unclear or a \
question is ambiguous, say so and ask for clarification rather than \
guessing.
"""

# Model is created once with the system prompt as its permanent instruction,
# separate from the conversation itself - this leaves the actual message
# history free to be just the back-and-forth with the student.
model = genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_PROMPT)

# ---------------------------------------------------------------------------
# Per-user conversation memory: each Telegram user gets their own ongoing
# Gemini chat session, so follow-up questions ("what about part b?") have
# access to what was discussed earlier instead of starting from scratch.
# Sessions live only in memory - they reset if the bot restarts, and a user
# can also clear their own with /reset.
# ---------------------------------------------------------------------------

_chat_sessions: dict[int, "genai.ChatSession"] = {}
MAX_HISTORY_TURNS = 20  # trim old history so token usage doesn't grow forever


def _get_chat(user_id: int):
    chat = _chat_sessions.get(user_id)
    if chat is None:
        chat = model.start_chat(history=[])
        _chat_sessions[user_id] = chat
    elif len(chat.history) > MAX_HISTORY_TURNS * 2:
        # chat.history can't be reassigned directly (it's read-only), so we
        # start a fresh session seeded with just the trimmed history instead.
        trimmed = chat.history[-MAX_HISTORY_TURNS * 2:]
        chat = model.start_chat(history=trimmed)
        _chat_sessions[user_id] = chat
    return chat


# ---------------------------------------------------------------------------
# Safety-net cleanup: even with the instructions above, an AI model can
# sometimes slip back into LaTeX or double-asterisk markdown. Rather than
# relying purely on the prompt, we clean the text in code before sending,
# converting it to Telegram's actual HTML formatting.
# ---------------------------------------------------------------------------

def _strip_latex(text: str) -> str:
    text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1/\2)", text)
    text = re.sub(r"\\text\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\mathbf\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\times", "x", text)
    text = re.sub(r"\\cdot", "x", text)
    text = re.sub(r"\\approx", "~", text)
    text = re.sub(r"\\circ", "deg", text)
    text = re.sub(r"\\Sigma", "sum", text)
    # Remove $ / $$ math delimiters but keep the inner content
    text = re.sub(r"\${1,2}([^$]+?)\${1,2}", r"\1", text)
    # Catch-all: drop any remaining LaTeX-style backslash commands
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("{", "").replace("}", "")
    return text


def _to_telegram_html(text: str) -> str:
    # Escape real HTML special characters first, so our own <b> tags
    # (added below) are the only HTML Telegram will see.
    text = html_lib.escape(text, quote=False)
    # Convert markdown bold (** or __) to real bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Convert single-asterisk bold (our prompt's preferred style) to real bold
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<b>\1</b>", text)
    # Markdown headers -> bold line
    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    # Strip blockquote markers and markdown horizontal rules
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    # Normalize markdown bullets ("* " / "+ ") to plain hyphens
    text = re.sub(r"^[\*\+]\s+", "- ", text, flags=re.MULTILINE)
    return text.strip()


def sanitize_for_telegram(text: str) -> str:
    return _to_telegram_html(_strip_latex(text))


async def send_reply(update: Update, text: str) -> None:
    safe_text = sanitize_for_telegram(text)
    try:
        await update.message.reply_text(safe_text, parse_mode=ParseMode.HTML)
    except Exception:
        logger.warning("HTML send failed, falling back to plain text")
        plain = re.sub(r"<[^>]+>", "", safe_text)
        await update.message.reply_text(plain)


# ---------------------------------------------------------------------------
# Handlers - each of these runs automatically when a matching message
# arrives. This is the core pattern of python-telegram-bot.
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! I can help with:\n"
        "- O-Level/N-Level: A Math, E Math, POA, Chemistry, Physics, Biology\n"
        "- A-Level (JC): H1/H2 Math, Physics, Chemistry, Biology, Economics "
        "(including Case Study AQs), and GP/English essays\n\n"
        "Send me a question as text, or a photo of your working/essay, and "
        "I'll mark it exam-style with a model answer. I'll remember our "
        "conversation, so you can ask follow-up questions naturally - send "
        "/reset any time to start a fresh topic.\n\n"
        "Note: I'm an AI tutor, not an official MOE/Cambridge marker - "
        "always check against your teacher's guidance for anything graded."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    _chat_sessions.pop(user_id, None)
    await update.message.reply_text("Cleared! Starting fresh on your next question.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _check_and_increment_quota(user_id):
        await update.message.reply_text(
            "You've hit today's question limit - try again tomorrow!"
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    question = update.message.text

    try:
        chat = _get_chat(user_id)
        response = chat.send_message(question)
        await send_reply(update, response.text)
    except Exception:
        logger.exception("Gemini call failed")
        await update.message.reply_text(
            "Sorry, something went wrong generating feedback. Please try again."
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _check_and_increment_quota(user_id):
        await update.message.reply_text(
            "You've hit today's question limit - try again tomorrow!"
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)

    # Telegram sends multiple resolutions of the same photo; the last one
    # in the list is the largest/highest quality.
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    caption = update.message.caption or (
        "Here is a photo of my working - please mark it."
    )

    try:
        chat = _get_chat(user_id)
        response = chat.send_message(
            [
                caption,
                {"mime_type": "image/jpeg", "data": bytes(photo_bytes)},
            ]
        )
        await send_reply(update, response.text)
    except Exception:
        logger.exception("Gemini call failed")
        await update.message.reply_text(
            "Sorry, something went wrong reading that photo. Please try "
            "again with a clear, well-lit, non-blurry photo."
        )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send me a text question or a photo of your working to get started!"
    )


# ---------------------------------------------------------------------------
# Entry point - wires the handlers up and starts the bot listening for
# messages (polling mode: no public server needed to run this locally).
# ---------------------------------------------------------------------------

def _run_health_server() -> None:
    """A minimal HTTP server that just replies 200 OK to anything. Free
    hosting platforms (e.g. Render) require an app to bind to a port and
    respond to web requests to consider it 'alive' - this satisfies that
    requirement while the real work (Telegram polling) happens separately."""
    port = int(os.environ.get("PORT", 8080))

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")

        def log_message(self, format, *args):
            pass  # silence per-request logging, it's just noise

    HTTPServer(("0.0.0.0", port), _Handler).serve_forever()


def main() -> None:
    threading.Thread(target=_run_health_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.ALL, unknown))

    logger.info(f"Bot starting (polling mode)... [CODE VERSION: v4-gemini2.5flash] [MODEL: {MODEL_NAME}]")
    app.run_polling()


if __name__ == "__main__":
    main()
