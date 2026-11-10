from types import SimpleNamespace

from marketlens import llm_fallback as lf
from marketlens import trends
from tests.test_trends import P, make_db


class FakeClient:
    """Stands in for the API. Returns whatever answer it is given for each call and counts the calls."""
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0
        self.messages = self

    def create(self, **kwargs):
        text = self.answers[self.calls % len(self.answers)]
        self.calls += 1
        return SimpleNamespace(content=[SimpleNamespace(text=text)], usage=SimpleNamespace(input_tokens=1000, output_tokens=20))


def db_with_empty_tech_job():
    con = make_db([
        P(1, "Software Engineer", "We build backend services with Haskell and Idris in a small team.", "2026-11-01", company="A"),
        P(2, "Account Executive", "Sell to enterprise customers.", "2026-11-01", company="B"),
        P(3, "Data Engineer", "Python and SQL pipelines.", "2026-11-01", company="C"),
    ])
    trends.build(con)
    return con


def test_only_technical_jobs_with_no_skill_are_candidates():
    con = db_with_empty_tech_job()
    keys = [k for k, _, _ in lf.candidates(con)]
    assert keys == ["greenhouse:1"]                             # job 2 is sales, job 3 already has skills
    assert "greenhouse:3" not in keys and "greenhouse:2" not in keys


def test_skills_not_in_the_posting_are_rejected():
    con = db_with_empty_tech_job()
    client = FakeClient(['["haskell", "idris", "kubernetes"]'])   # kubernetes is not in the text
    s = lf.run(con, client)
    assert s["kept"] == 2 and s["rejected"] == 1
    saved = {r[0] for r in con.execute("SELECT skill FROM job_skills_llm").fetchall()}
    assert saved == {"haskell", "idris"}
    assert "haskell" in s["new_to_dictionary"]


def test_a_job_already_asked_about_is_not_asked_again():
    con = db_with_empty_tech_job()
    client = FakeClient(['["haskell"]'])
    lf.run(con, client)
    lf.run(con, client)
    assert client.calls == 1


def test_bad_model_answers_give_no_skills_and_a_cap_stops_the_run():
    assert lf.parse_skills("I could not find any") == []
    assert lf.parse_skills("Here you go: [\"Python\", 3, \"\"] thanks") == ["python"]
    con = db_with_empty_tech_job()
    s = lf.run(con, FakeClient(["not json"]))
    assert s["asked"] == 1 and s["with_skill"] == 0
    con2 = db_with_empty_tech_job()
    assert lf.run(con2, FakeClient(['["haskell"]']), max_usd=0.0)["stopped_for_cost"] is True


def test_whole_word_match():
    assert lf.appears_in("r", "We use R and Python") and not lf.appears_in("r", "there is more")
