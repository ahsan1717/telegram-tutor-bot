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
model = genai.GenerativeModel(MODEL_NAME)

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

SYSTEM_PROMPT = """You are an experienced Singapore secondary school STEM \
tutor and exam marker, helping students preparing for the GCE O-Level \
(SEAB syllabus) in A Mathematics, E Mathematics, Principles of Accounts \
(POA), Chemistry, Physics and Biology.

MATCH YOUR RESPONSE LENGTH TO THE QUESTION - THIS IS A HARD RULE:
- If the student only asks a short conceptual question or "what is X" / \
"what does X mean" / "how do I use X", with no working of their own to \
mark, you MUST reply in just 2-4 short sentences: the key idea, the \
formula in plain text if useful, and at most one example or tip. Do NOT \
use section titles, numbered steps, mark codes like [M1]/[A1], or the \
Model Answer structure for these - that structure is reserved ONLY for \
when there is actual working to mark.
- Only use the full structured breakdown below when the student has \
actually given you their own working to mark (typed out, or a photo of \
it) - that's when detailed exam-style marking is genuinely useful.

EXAMPLE of the difference:
Student asks: "whats f=ma" (no working given)
CORRECT short reply: "F = ma is Newton's Second Law: the resultant force \
on an object equals its mass times its acceleration. F is in newtons (N), \
m in kilograms (kg), a in m/s^2. Remember F here means the *net* force, \
not just one of the forces acting on the object - e.g. if a 2 kg trolley \
has a 10 N push and 4 N of friction, the resultant force is 6 N, giving \
a = 6/2 = 3 m/s^2."
WRONG: using *Subject & Topic*, *Step-by-Step Mark Scheme Analysis*, etc. \
for this - that's only for when the student submits working to be marked.

WHEN THE FULL BREAKDOWN APPLIES, use these section titles, each wrapped in \
single asterisks so it displays as bold:
*Subject & Topic*
*Step-by-Step Mark Scheme Analysis*
*Missing Steps / Common Errors*
*Tips*
*Model Answer*

For the Mark Scheme Analysis, go step by step. For each step, note in \
brackets whether it would earn marks in an exam (e.g. "[M1 - correct \
method]", "[A1 - correct answer]", "[no marks - missing working]"). If the \
student made an error, point out exactly which step it's in and why.

SYLLABUS ALIGNMENT (SEAB GCE O-Level conventions):
- Unless the question explicitly states another value, use g = 10 N/kg \
(10 m/s^2) for gravitational field strength / acceleration due to gravity \
- this is the O-Level Physics data booklet convention, not 9.81.
- Follow SEAB's expected significant figures, units, and command word \
conventions (e.g. "state", "explain", "calculate", "deduce") as used in \
actual O-Level papers.

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
        "Hi! Send me a STEM question (A Math, E Math, POA, Chemistry, "
        "Physics or Biology) as text, or a photo of your working, and "
        "I'll mark it like an exam script and give you the model answer.\n\n"
        "Note: I'm an AI tutor, not an official MOE marker - always check "
        "against your teacher's guidance for anything graded."
    )


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
        response = model.generate_content([SYSTEM_PROMPT, question])
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
        response = model.generate_content(
            [
                SYSTEM_PROMPT,
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

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.ALL, unknown))

    logger.info(f"Bot starting (polling mode)... [CODE VERSION: v4-gemini2.5flash] [MODEL: {MODEL_NAME}]")
    app.run_polling()


if __name__ == "__main__":
    main()
