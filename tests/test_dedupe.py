from marketlens import dedupe, store
from marketlens.ingest.schema import Posting


def P(i, title, company="Acme", location="Phoenix, AZ", source="greenhouse", posted="2026-11-01", desc="d"):
    return Posting(source, str(i), title, company, location, desc, posted, "u", "", None, None, "t")


def rows(postings):
    return [p.as_dict() for p in postings]


def test_exact_duplicates_after_cleaning_are_found():
    r = rows([P(1, "Data Engineer"), P(2, "data  engineer (Remote OK)"), P(3, "Data Engineer!")])
    d = dedupe.find_duplicates(r)
    assert len(d) == 2 and {m for _, _, m in d} == {"exact"}


def test_company_suffix_and_case_do_not_matter():
    r = rows([P(1, "Data Engineer", company="Acme Inc."), P(2, "Data Engineer", company="ACME")])
    assert len(dedupe.find_duplicates(r)) == 1


def test_same_job_on_two_sources_is_found():
    r = rows([P(1, "Data Engineer", source="greenhouse"), P(2, "Data Engineer", source="remotive")])
    d = dedupe.find_duplicates(r)
    assert len(d) == 1 and d[0][1]["source"] in ("greenhouse", "remotive")


def test_different_place_is_a_different_job():
    r = rows([P(1, "Data Engineer", location="Phoenix, AZ"), P(2, "Data Engineer", location="Austin, TX")])
    assert dedupe.find_duplicates(r) == []


def test_remote_variants_count_as_the_same_place():
    r = rows([P(1, "Data Engineer", location="Remote, US"), P(2, "Data Engineer", location="Remote - Americas")])
    assert len(dedupe.find_duplicates(r)) == 1


def test_different_level_or_team_is_kept():
    r = rows([
        P(1, "Data Engineer"), P(2, "Senior Data Engineer"), P(3, "Data Engineer II"),
        P(4, "Software Engineer, Backend"), P(5, "Software Engineer, Frontend"),
    ])
    assert dedupe.find_duplicates(r) == []


def test_small_typo_is_a_fuzzy_duplicate():
    r = rows([P(1, "Machine Learning Engineer"), P(2, "Machine Learnin Engineer")])
    d = dedupe.find_duplicates(r)
    assert len(d) == 1 and d[0][2] == "fuzzy"


def test_oldest_posting_is_kept():
    r = rows([P(1, "Data Engineer", posted="2026-11-05"), P(2, "Data Engineer", posted="2026-10-20")])
    d = dedupe.find_duplicates(r)
    assert d[0][1]["source_id"] == "2" and d[0][0]["source_id"] == "1"


def test_run_builds_map_and_jobs_view_and_can_repeat():
    con = store.connect(":memory:")
    store.upsert(con, [P(1, "Data Engineer"), P(2, "Data Engineer"), P(3, "Designer")])
    rep = dedupe.run(con)
    assert (rep["total"], rep["duplicates"], rep["unique"]) == (3, 1, 2)
    assert con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    rep2 = dedupe.run(con)                       # running again gives the same answer, not more rows
    assert rep2["duplicates"] == 1 and con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM postings").fetchone()[0] == 3   # raw table is never changed


def test_team_or_customer_type_in_title_keeps_jobs_apart():
    # real examples that the first version wrongly merged
    r = rows([
        P(1, "Account Executive, Product Sales (Terminal)"), P(2, "Account Executive, Product Sales - Tax"),
        P(3, "Staff Software Engineer- CXI"), P(4, "Staff Software Engineer - IAM"),
        P(5, "Fraud Operations Associate SDC"), P(6, "Fraud Operations Associate (Mandarin Speaking)"),
        P(7, "Strategic Core Account Executive"), P(8, "Strategic Core Account Executive - CPG"),
        P(9, "Tech Operations Associate"), P(10, "Operations Associate"),
    ])
    assert dedupe.find_duplicates(r) == []


def test_noise_in_brackets_is_ignored_but_meaningful_brackets_are_kept():
    assert dedupe.norm_title("Data Engineer (Remote)") == "data engineer"
    assert dedupe.norm_title("Data Engineer (m/f/d)") == "data engineer"
    assert dedupe.norm_title("Fraud Associate (Mandarin Speaking)") == "fraud associate mandarin speaking"


def test_sr_and_senior_are_the_same_word():
    assert len(dedupe.find_duplicates(rows([P(1, "Sr. Data Engineer"), P(2, "Senior Data Engineer")]))) == 1


def test_different_city_lists_and_different_remote_states_are_kept_apart():
    r = rows([
        P(1, "Data Engineer", location="San Francisco, CA; New York, NY"), P(2, "Data Engineer", location="San Francisco, CA"),
        P(3, "Account Executive", location="Remote - Texas"), P(4, "Account Executive", location="Remote - Virginia"),
    ])
    assert dedupe.find_duplicates(r) == []
