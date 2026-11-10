"""Ask a small language model for the skills in jobs where the dictionary found none.

Why: the dictionary finds a skill in 68.8% of jobs. For the rest, either the job really names no skill (most sales
and legal jobs) or the dictionary is missing a word. This step looks only at technical jobs with no skill found, asks
the model what skills the posting names, and checks every answer.

Rules that keep it honest:
  * A skill the model returns only counts if the words appear in the posting. Anything else is rejected, so the model
    cannot invent a skill.
  * Results go in their own tables (job_skills_llm, llm_done). They are NOT mixed into job_skills. The numbers on the
    results page still come from the dictionary alone until you decide otherwise.
  * Every job asked about is remembered, so running it again never pays for the same job twice.
  * A spending cap stops the run.

Run: python -m marketlens.llm_fallback --limit 25      (put ANTHROPIC_API_KEY in .env first)
"""
import argparse
import json
import os
import re

from . import store
from .skills_dictionary import SKILLS
from .trends import TECH_FAMILIES

MODEL = "claude-haiku-5-5"
# Price per million tokens for this model under 100K tokens per request. Check anthropic.com/pricing before trusting
# the dollar figures; the token counts printed alongside are exact.
INPUT_USD_PER_M = 0.10
OUTPUT_USD_PER_M = 0.50
MAX_DESCRIPTION_CHARS = 6000

SYSTEM = (
    "You read one job posting and list the technical skills it names: programming languages, tools, frameworks, "
    "platforms, databases, and named methods. Only list a skill if its name appears in the text of the posting. "
    "Do not infer skills the posting does not name. Do not list soft skills. Answer with a JSON array of up to 10 "
    "short lowercase strings and nothing else. If the posting names no technical skill, answer []."
)

CREATE_SKILLS = "CREATE TABLE IF NOT EXISTS job_skills_llm (job_key VARCHAR, skill VARCHAR, model VARCHAR)"
CREATE_DONE = ("CREATE TABLE IF NOT EXISTS llm_done (job_key VARCHAR, model VARCHAR, kept INTEGER, rejected INTEGER, "
               "input_tokens INTEGER, output_tokens INTEGER, asked_at VARCHAR)")


def cost_usd(input_tokens, output_tokens):
    return input_tokens * INPUT_USD_PER_M / 1e6 + output_tokens * OUTPUT_USD_PER_M / 1e6


def candidates(con, families=TECH_FAMILIES, limit=25):
    """Technical jobs the dictionary found nothing in, that this model has not been asked about yet."""
    con.execute(CREATE_SKILLS)
    con.execute(CREATE_DONE)
    return con.execute(
        """SELECT j.source || ':' || j.source_id, j.title, j.description
           FROM jobs j JOIN job_facts f ON f.job_key = j.source || ':' || j.source_id
           WHERE list_contains(?, f.role_family)
             AND NOT EXISTS (SELECT 1 FROM job_skills s WHERE s.job_key = f.job_key)
             AND NOT EXISTS (SELECT 1 FROM llm_done d WHERE d.job_key = f.job_key AND d.model = ?)
           ORDER BY f.job_key LIMIT ?""", [list(families), MODEL, limit]).fetchall()


def parse_skills(text):
    """The model should answer with a JSON array. Tolerate text around it. Anything else gives no skills."""
    match = re.search(r"\[.*\]", text or "", re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except ValueError:
        return []
    return [s.strip().lower() for s in items if isinstance(s, str) and s.strip()]


def appears_in(skill, description):
    """Whole word match, so 'r' is not found inside 'there'."""
    return re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", (description or "").lower()) is not None


def ask(client, model, title, description):
    resp = client.messages.create(
        model=model, max_tokens=300, system=SYSTEM,
        messages=[{"role": "user", "content": f"Title: {title}\n\nPosting:\n{(description or '')[:MAX_DESCRIPTION_CHARS]}"}])
    text = "".join(getattr(b, "text", "") for b in resp.content)
    return parse_skills(text), resp.usage.input_tokens, resp.usage.output_tokens


def run(con, client, limit=25, max_usd=0.50, model=MODEL, families=TECH_FAMILIES):
    """Ask about up to `limit` jobs. Stops early if the estimated spend reaches `max_usd`. Returns a summary dict."""
    jobs = candidates(con, families, limit)
    summary = {"asked": 0, "with_skill": 0, "kept": 0, "rejected": 0, "new_to_dictionary": set(),
               "input_tokens": 0, "output_tokens": 0, "stopped_for_cost": False, "examples": []}
    for key, title, description in jobs:
        if cost_usd(summary["input_tokens"], summary["output_tokens"]) >= max_usd:
            summary["stopped_for_cost"] = True
            break
        found, tin, tout = ask(client, model, title, description)
        good = sorted({s for s in found if appears_in(s, description) or appears_in(s, title)})
        bad = [s for s in found if s not in good]
        if good:
            con.executemany("INSERT INTO job_skills_llm VALUES (?, ?, ?)", [[key, s, model] for s in good])
        con.execute("INSERT INTO llm_done VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [key, model, len(good), len(bad), tin, tout, store.now_iso()])
        summary["asked"] += 1
        summary["with_skill"] += 1 if good else 0
        summary["kept"] += len(good)
        summary["rejected"] += len(bad)
        summary["input_tokens"] += tin
        summary["output_tokens"] += tout
        summary["new_to_dictionary"].update(s for s in good if s not in SKILLS)
        if len(summary["examples"]) < 10:
            summary["examples"].append((title, good, bad))
    summary["cost_usd"] = cost_usd(summary["input_tokens"], summary["output_tokens"])
    return summary


def print_summary(s):
    print(f"asked about {s['asked']} jobs; {s['with_skill']} got at least one verified skill, "
          f"{s['asked'] - s['with_skill']} got none")
    print(f"skills kept: {s['kept']}   rejected because the words are not in the posting: {s['rejected']}")
    print(f"tokens: {s['input_tokens']} in, {s['output_tokens']} out   estimated cost: ${s['cost_usd']:.4f} "
          f"(at ${INPUT_USD_PER_M}/M in, ${OUTPUT_USD_PER_M}/M out; check the current price)")
    if s["stopped_for_cost"]:
        print("stopped early: the spending cap was reached")
    if s["new_to_dictionary"]:
        print("verified skills the dictionary does not have (candidates to add): "
              + ", ".join(sorted(s["new_to_dictionary"])))
    print("\nFirst examples (check these by hand):")
    for title, good, bad in s["examples"]:
        print(f"  {title[:60]:<60} kept: {good}  rejected: {bad}")


def main():
    ap = argparse.ArgumentParser(description="LLM fallback for jobs with no skill found.")
    ap.add_argument("--db", default="data/marketlens.duckdb")
    ap.add_argument("--limit", type=int, default=25, help="how many jobs to ask about (default 25)")
    ap.add_argument("--max-usd", type=float, default=0.50, help="stop when the estimated spend reaches this")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY in the .env file first.")
    import anthropic
    con = store.connect(args.db)
    print_summary(run(con, anthropic.Anthropic(), limit=args.limit, max_usd=args.max_usd))


if __name__ == "__main__":
    main()
