# HN Daily

**A personalized AI podcast generator for Hacker News.** HN Daily picks a story from today's front page that matches your interests, reads the article and the comment thread, and turns it into a 12–15 minute two-host podcast episode as an MP3. A small web UI streams progress while an episode is generated, keeps a history of past episodes, and collects feedback that updates a listener profile over time.

## How it works

```
HN front page → story selection → article + comments → briefing doc → podcast script → TTS → MP3
```

1. **Scrape** – Fetches the top 30 front-page stories and their comment threads from the Hacker News Algolia API. Article text is extracted with `trafilatura`.
2. **Select** – Claude Haiku picks the story that best fits your stated interests and has the most discussion potential.
3. **Research** – If the article can't be extracted (paywall, JS-heavy site), it falls back to Claude's web search tool for context.
4. **Brief** – Claude Haiku pulls the main debate themes out of the comments. Claude Sonnet then writes a structured briefing: background, key points, community perspectives with counterarguments, and on-air questions.
5. **Script** – Claude Haiku turns the briefing into a dialogue between two hosts: **Jordan**, the curious generalist, and **Alex**, the expert. It follows a fixed structure: hook → plain-English explainer → stakes → community debate → nuance → takeaway.
6. **Voice** – Each line goes through text-to-speech with a separate voice per host (OpenAI TTS, or free `edge-tts`), and `pydub` stitches the chunks into one MP3 with natural pauses.
7. **Learn** – Feedback submitted in the UI is attached to that episode in `history.json`. A persona agent then updates `persona.json` with topic and style preferences. It's deliberately conservative: confidence only rises after repeated consistent signals, and a single negative comment can't push a topic out of your interests.

## Features

- 🎧 End-to-end generation from a single interests prompt
- 🌐 Flask web UI with live progress over Server-Sent Events
- 📡 RSS feed at `/feed.xml`, so you can subscribe in a podcast app on your local network
- 🕓 Episode history and per-episode feedback
- 🧠 Listener persona that evolves from your feedback
- 💸 Cost-aware model routing: Haiku for the cheap steps, Sonnet only for the briefing, and a switchable TTS backend (free or paid)

## Tech stack

Python · Flask · Anthropic API (Claude Sonnet 4.6, Haiku 4.5, web search tool) · OpenAI TTS / edge-tts · pydub · trafilatura · HN Algolia API · vanilla HTML/CSS/JS

## Project structure

| File | Purpose |
|---|---|
| `main.py` | CLI pipeline: story selection, briefing generation, web search fallback |
| `hn_scraper.py` | Front page, comment, and article-text fetching |
| `script_generator.py` | Briefing → two-host script, parsed into `(speaker, text)` tuples |
| `tts.py` | Script → per-line audio → merged MP3; switchable TTS backend |
| `persona_agent.py` | History logging, feedback storage, listener-persona updates |
| `server.py` | Flask server: UI, SSE generation endpoint, history, feedback, RSS |
| `index.html` | Web front end |

## Setup

**Requirements:** Python 3.10+ and `ffmpeg` (needed by pydub)

```bash
git clone https://github.com/tanyaaravind/hn_news.git
cd hn_news
python -m venv venv && source venv/bin/activate
pip install anthropic openai edge-tts pydub trafilatura requests flask python-dotenv
```

Create a `.env` file:

```
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here   # only needed if TTS_BACKEND = "openai"
```

To run it for free (apart from the Claude calls), set `TTS_BACKEND = "edge"` in `tts.py`.

## Usage

**Web UI**
```bash
python server.py
```
Open http://localhost:5000. To use the RSS feed from another device, set `HOST` in `server.py` to your machine's local IP.

**Command line**
```bash
python main.py
```
Enter your interests (e.g. `AI, open source, privacy`). The output goes to `outputs/`:
- `podcast_source.md`: the briefing
- `podcast_script.txt`: the script
- `podcast.mp3`: the episode

## Roadmap

- Feed the learned persona directly into story selection and script style
- Multi-story episodes with transitions
- Parallel TTS generation to cut render time
- Scheduled daily episodes
