"""
persona_agent.py
Updates persona.json based on feedback attached to history entries.

Called automatically:
  1. When user submits feedback via UI (immediate update)
  2. Before each generation run (picks up any pending feedback)

Usage:
  from persona_agent import update_persona, load_persona
  update_persona()
"""

import json
import os
from datetime import date
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()

OUTPUTS_DIR = "outputs"
HISTORY_PATH = os.path.join(OUTPUTS_DIR, "history.json")
PERSONA_PATH = os.path.join(OUTPUTS_DIR, "persona.json")

DEFAULT_PERSONA = {
    "version": 1,
    "last_updated": None,
    "confidence": "low",
    "runs_analyzed": 0,
    "topic_preferences": {
        "high_interest": [],
        "low_interest": [],
        "neutral": []
    },
    "style_preferences": {
        "technical_depth": "unknown",
        "preferred_angle": "unknown",
        "pace": "unknown"
    },
    "inferred_signals": [],
    "explicit_feedback_log": []
}

UPDATE_PROMPT = """You are maintaining a listener profile for a personalized podcast app.

Your job: given the listener's history of podcasts and any feedback they've given, update their persona profile.

CRITICAL RULES:
- Be conservative. One data point should NOT strongly shift the profile.
- Distinguish between explicit feedback ("I didn't like X") and inferred signals (they keep requesting AI topics).
- If feedback is vague, note the uncertainty rather than over-interpreting.
- Confidence should only rise to "medium" after 3+ consistent signals, "high" after 5+.
- Never remove a topic from high_interest based on a single negative comment — downgrade to neutral first.
- technical_depth options: "low" / "medium" / "high" / "unknown"
- preferred_angle options: "narrative" / "debate" / "explainer" / "mixed" / "unknown"
- pace options: "slow" / "medium" / "fast" / "unknown"

CURRENT PERSONA:
{current_persona}

PODCAST HISTORY (most recent first):
{history}

TODAY'S DATE: {today}

Return ONLY valid JSON matching exactly this schema — no preamble, no markdown:
{{
  "version": <increment by 1>,
  "last_updated": "<YYYY-MM-DD>",
  "confidence": "<low|medium|high>",
  "runs_analyzed": <total runs with feedback>,
  "topic_preferences": {{
    "high_interest": ["topic1", "topic2"],
    "low_interest": ["topic3"],
    "neutral": ["topic4"]
  }},
  "style_preferences": {{
    "technical_depth": "<low|medium|high|unknown>",
    "preferred_angle": "<narrative|debate|explainer|mixed|unknown>",
    "pace": "<slow|medium|fast|unknown>"
  }},
  "inferred_signals": [
    {{"date": "YYYY-MM-DD", "signal": "description", "confidence": "<low|medium|high>", "source": "<explicit|inferred>"}}
  ],
  "explicit_feedback_log": [
    {{"date": "YYYY-MM-DD", "story_title": "...", "feedback": "...", "interpreted_as": "..."}}
  ]
}}"""


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH) as f:
        return json.load(f)


def load_persona():
    if not os.path.exists(PERSONA_PATH):
        return DEFAULT_PERSONA.copy()
    with open(PERSONA_PATH) as f:
        return json.load(f)


def save_persona(persona: dict):
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    with open(PERSONA_PATH, "w") as f:
        json.dump(persona, f, indent=2)


def has_pending_feedback(history: list) -> bool:
    """Check if any history entries have unprocessed feedback."""
    for run in history:
        if run.get("feedback"):
            return True
    return False


def format_history_for_prompt(history: list) -> str:
    """Format history into readable text for the prompt."""
    lines = []
    for run in reversed(history):  # most recent first
        lines.append(f"--- Run: {run['date']} (interests: {run.get('interests', 'not specified')}) ---")
        for story in run.get("stories", []):
            lines.append(f"  Story: {story['title']}")
            lines.append(f"  Topics: {', '.join(story.get('topics', []))}")
            lines.append(f"  Summary: {story.get('summary', '')}")
        feedback = run.get("feedback", [])
        if feedback:
            lines.append(f"  Feedback given:")
            for fb in feedback:
                story_ref = fb.get("story_title", "general")
                lines.append(f"    - Re '{story_ref}': {fb['text']}")
        else:
            lines.append("  Feedback: none")
        lines.append("")
    return "\n".join(lines)


def update_persona():
    """
    Main entry point. Reads history, updates persona if there's anything new.
    Returns updated persona dict.
    """
    history = load_history()
    current_persona = load_persona()

    if not history:
        print("   No history found — skipping persona update")
        return current_persona

    # Check if there's anything worth updating
    total_feedback = sum(len(r.get("feedback", [])) for r in history)
    if total_feedback == 0 and current_persona.get("runs_analyzed", 0) >= len(history):
        print("   Persona up to date — no new feedback to process")
        return current_persona

    print("   🧠 Updating listener persona...")

    history_text = format_history_for_prompt(history)
    prompt = UPDATE_PROMPT.format(
        current_persona=json.dumps(current_persona, indent=2),
        history=history_text,
        today=date.today().isoformat()
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    updated = json.loads(raw)
    save_persona(updated)
    print(f"   ✅ Persona updated (confidence: {updated.get('confidence')}, signals: {len(updated.get('inferred_signals', []))})")
    return updated


def add_feedback(run_id: str, story_titles: list, feedback_text: str):
    """
    Attach feedback to specific stories in history.json.
    Called from server.py when user submits feedback via UI.
    """
    history = load_history()

    feedback_entry = {
        "story_title": ", ".join(story_titles) if story_titles else "general",
        "text": feedback_text,
        "date": date.today().isoformat()
    }

    # Find the run and attach feedback
    matched = False
    for run in history:
        if run["run_id"] == run_id:
            if "feedback" not in run:
                run["feedback"] = []
            run["feedback"].append(feedback_entry)
            matched = True
            break

    if not matched:
        # If run_id not found, attach to most recent run
        if history:
            if "feedback" not in history[-1]:
                history[-1]["feedback"] = []
            history[-1]["feedback"].append(feedback_entry)

    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)

    print(f"   💬 Feedback saved for: {feedback_entry['story_title']}")

    # Immediately trigger persona update
    return update_persona()


def append_run_to_history(interests: str, stories: list):
    """
    Called at end of generation pipeline to log the new run.
    stories: list of dicts with title, url, topics, summary
    """
    history = load_history()

    run_id = f"run_{str(len(history) + 1).zfill(3)}"
    entry = {
        "run_id": run_id,
        "date": date.today().isoformat(),
        "interests": interests,
        "stories": stories,
        "feedback": []
    }

    history.append(entry)

    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)

    print(f"   📝 Run logged to history: {run_id}")
    return run_id


if __name__ == "__main__":
    # Test: run persona update against existing history
    persona = update_persona()
    print("\n" + "=" * 50)
    print("CURRENT PERSONA:")
    print("=" * 50)
    print(json.dumps(persona, indent=2))