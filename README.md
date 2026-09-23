# STEM Homework Helper Bot

A Telegram bot that marks G1-G3 STEM questions (A Math, E Math, POA,
Chemistry, Physics, Biology) exam-style: step-by-step mark scheme analysis,
missing steps, common errors, tips, and a full model answer. Accepts both
typed questions and photos of handwritten working.

## 1. Install Python

If you don't already have Python installed, download it from
https://python.org (3.10 or newer). During install on Windows, tick
"Add Python to PATH".

## 2. Get your two free tokens

**Telegram bot token**
1. Open Telegram, search for `@BotFather`, start a chat.
2. Send `/newbot`, follow the prompts (name, then a username ending in `bot`).
3. BotFather replies with a token that looks like `123456789:AAExxxxxxxx`.

**Gemini API key**
1. Go to https://aistudio.google.com
2. Sign in with a Google account, click "Get API key" -> "Create API key".
3. Copy the key it gives you.

## 3. Set up the project

Open a terminal in this folder and run:

```bash
python -m venv venv

# Activate it:
venv\Scripts\activate       # Windows
source venv/bin/activate    # Mac/Linux

pip install -r requirements.txt
```

Then copy `.env.example` to a new file called `.env`, and paste your two
tokens in:

```
TELEGRAM_BOT_TOKEN=123456789:AAExxxxxxxx
GEMINI_API_KEY=AIzaSyxxxxxxxx
```

## 4. Run it

```bash
python bot.py
```

Leave this running, then open Telegram, find your bot by the username you
gave it, and send `/start`. Try a text question, then try a photo of some
working. Press Ctrl+C in the terminal to stop the bot.

## 5. Put it online 24/7 (so it works when your laptop is off)

1. Create a free GitHub account and push this folder as a new repository
   (do NOT push your `.env` file — GitHub will warn you if you try; leave
   it out).
2. Go to https://render.com, sign up, "New" -> "Web Service", connect your
   GitHub repo.
3. Under "Environment", add `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY` as
   environment variables (same values as your local `.env`).
4. Set the start command to `python bot.py`. Deploy.

Render's free tier may put the bot to sleep after inactivity (a message
might take a few extra seconds to get a reply after a quiet period) — fine
for a personal/small-scale student tool. If you outgrow that, Railway.app
is a solid paid-but-cheap alternative with no sleeping.

## Customizing

- **Change how strict the daily limit is:** edit `MAX_REQUESTS_PER_DAY` near
  the top of `bot.py`.
- **Change the feedback style or subjects covered:** edit the `SYSTEM_PROMPT`
  string in `bot.py` — this single block of text controls everything the AI
  says, so tweak wording, add/remove subjects, or change the structure here.
- **Swap the AI model:** change `MODEL_NAME` in `bot.py`. Check
  https://ai.google.dev/gemini-api/docs/models for current model names and
  which are free-tier eligible.

## Important note for your users

This bot's feedback is AI-generated and inspired by how MOE mark schemes
work — it is not an official or guaranteed-accurate marking. Make sure your
`/start` message (already included) makes that clear so students don't treat
it as authoritative for graded work.
