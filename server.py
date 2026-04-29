"""
server.py
Flask server for HN Daily UI.
Serves index.html and streams pipeline progress via Server-Sent Events.

Usage: python server.py
Then open http://localhost:5000
"""

import json
import os
import queue
import threading
from datetime import date
from flask import Flask, Response, request, send_from_directory

from dotenv import load_dotenv
from main import select_stories, generate_briefing_silent, websearch_fallback
from hn_scraper import fetch_front_page, fetch_comments, fetch_article_text
from script_generator import generate_script
from tts import script_to_audio

load_dotenv()

OUTPUTS_DIR = "outputs"
os.makedirs(OUTPUTS_DIR, exist_ok=True)

HOST = "10.48.17.144"
PORT = 5000
BASE_URL = f"http://{HOST}:{PORT}"

app = Flask(__name__, static_folder=".")


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/outputs/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUTS_DIR, filename, as_attachment=False)


@app.route("/feed.xml")
def rss_feed():
    from email.utils import formatdate
    import os

    mp3_path = os.path.join(OUTPUTS_DIR, "podcast.mp3")
    md_path  = os.path.join(OUTPUTS_DIR, "podcast_source.md")

    items_xml = ""
    if os.path.exists(mp3_path):
        stat     = os.stat(mp3_path)
        size     = stat.st_size
        pub_date = formatdate(stat.st_mtime)

        title = "HN Daily"
        if os.path.exists(md_path):
            with open(md_path) as f:
                first_line = f.readline().strip()
                if first_line.startswith("#"):
                    title = first_line.lstrip("#").strip()

        items_xml = f"""
    <item>
      <title>{title}</title>
      <description>Your daily HN podcast — two stories, two hosts, ~15 minutes.</description>
      <pubDate>{pub_date}</pubDate>
      <enclosure url="{BASE_URL}/outputs/podcast.mp3" length="{size}" type="audio/mpeg"/>
      <guid>{BASE_URL}/outputs/podcast.mp3?ts={int(stat.st_mtime)}</guid>
    </item>"""

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>HN Daily</title>
    <description>Your personalised Hacker News podcast.</description>
    <link>{BASE_URL}</link>
    <language>en-us</language>
    <itunes:author>HN Daily</itunes:author>
    <itunes:category text="Technology"/>
    <itunes:explicit>no</itunes:explicit>{items_xml}
  </channel>
</rss>"""

    return Response(feed, mimetype="application/rss+xml")


@app.route("/history")
def get_history():
    """Return story list for feedback picker"""
    from persona_agent import load_history
    history = load_history()
    # Flatten into list of {run_id, date, story_title} for the UI picker
    items = []
    for run in reversed(history):
        for story in run.get("stories", []):
            items.append({
                "run_id": run["run_id"],
                "date": run["date"],
                "title": story["title"]
            })
    from flask import jsonify
    return jsonify(items)


@app.route("/feedback", methods=["POST"])
def submit_feedback():
    """Save feedback and trigger immediate persona update"""
    from persona_agent import add_feedback
    from flask import jsonify
    data = request.get_json()
    run_id = data.get("run_id", "")
    story_titles = data.get("story_titles", [])
    feedback_text = data.get("feedback", "").strip()
    if not feedback_text:
        return jsonify({"error": "No feedback provided"}), 400
    updated_persona = add_feedback(run_id, story_titles, feedback_text)
    return jsonify({"status": "ok", "persona_confidence": updated_persona.get("confidence")})


@app.route("/generate")
def generate():
    interests = request.args.get("interests", "technology, software engineering, open source")
    feedback  = request.args.get("feedback", "")

    q = queue.Queue()

    def pipeline():
        try:
            # ── 1. Fetch front page ──────────────────────────────────────────
            q.put({"type": "step_start", "step": "fetch"})
            stories = fetch_front_page(limit=30)
            q.put({"type": "step_done",  "step": "fetch"})

            # ── 2. Select stories ────────────────────────────────────────────
            q.put({"type": "step_start", "step": "select"})
            selected = select_stories(stories, interests)
            q.put({"type": "step_done",  "step": "select"})

            # ── 3. Briefings ─────────────────────────────────────────────────
            q.put({"type": "step_start", "step": "briefing"})
            story_lookup = {s["id"]: s for s in stories}
            briefings = []

            for sel in selected:
                story = story_lookup.get(sel["id"], sel)
                comments = fetch_comments(story["id"])
                article_text = fetch_article_text(story.get("url", ""))
                if not article_text:
                    article_text = websearch_fallback(story["title"], story.get("url", ""))
                briefing = generate_briefing_silent(story, article_text, comments)
                briefings.append(briefing)

            combined = (
                f"# HN PODCAST SOURCE — {date.today().strftime('%B %d, %Y')}\n"
                f"User interests: {interests}\n\n---\n\n"
                + "---".join(briefings)
            )

            briefing_path = os.path.join(OUTPUTS_DIR, "podcast_source.md")
            with open(briefing_path, "w") as f:
                f.write(combined)
            q.put({"type": "step_done", "step": "briefing"})

            # ── 4. Script ────────────────────────────────────────────────────
            q.put({"type": "step_start", "step": "script"})
            script = generate_script(combined)
            script_path = os.path.join(OUTPUTS_DIR, "podcast_script.txt")
            with open(script_path, "w") as f:
                for speaker, text in script:
                    f.write(f"{speaker}: {text}\n\n")
            q.put({"type": "step_done", "step": "script"})

            # ── 5. TTS ───────────────────────────────────────────────────────
            q.put({"type": "step_start", "step": "tts"})
            audio_path = script_to_audio(
                script,
                output_path=os.path.join(OUTPUTS_DIR, "podcast.mp3")
            )
            q.put({"type": "step_done", "step": "tts"})

            # ── 6. Done ──────────────────────────────────────────────────────
            q.put({
                "type": "done",
                "files": [
                    f"/outputs/podcast.mp3",
                    f"/outputs/podcast_source.md",
                ]
            })

        except Exception as e:
            q.put({"type": "error", "message": str(e)})

    thread = threading.Thread(target=pipeline, daemon=True)
    thread.start()

    def event_stream():
        while True:
            try:
                msg = q.get(timeout=300)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg["type"] in ("done", "error"):
                    break
            except queue.Empty:
                yield "data: {\"type\": \"error\", \"message\": \"Timed out\"}\n\n"
                break

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("🎙️  HN Daily server starting...")
    print(f"   Local :  http://localhost:{PORT}")
    print(f"   Network: http://{HOST}:{PORT}")
    print(f"   RSS feed: http://{HOST}:{PORT}/feed.xml")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)