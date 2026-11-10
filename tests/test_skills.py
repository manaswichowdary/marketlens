from marketlens import extract, skills, store, dedupe
from marketlens.ingest.schema import Posting


def found(text, title=""):
    return skills.extract(title, text)


def test_basic_skills_are_found_case_insensitively():
    assert {"python", "sql", "aws"} <= found("You know PYTHON, sql and Amazon Web Services (S3).")


def test_whole_words_only():
    f = found("We use JavaScript every day.")
    assert "javascript" in f and "java" not in f


def test_symbols_in_names():
    f = found("Strong C++ and C# skills, plus node.js and .NET.")
    assert {"c++", "c#", "node.js", ".net"} <= f
    assert "javascript" not in f                      # node.js does not mean JavaScript here


def test_go_is_a_language_only_in_a_list_of_languages():
    assert "go" in found("Experience with Python, Go and Rust.")
    assert "go" in found("Golang services")
    assert "go" not in found("Own the go-to-market plan and let's go build things.")


def test_r_is_a_language_only_in_context():
    assert "r" in found("Proficiency in Python, R and SQL.")
    assert "r" not in found("The R&D team and our Q&R process.")


def test_swift_language_vs_swift_bank_network():
    assert "swift" in found("Build iOS apps in Swift and Objective-C.")
    assert "swift" not in found("Experience with SWIFT payment messages.")


def test_react_framework_vs_react_verb():
    assert "react" in found("Front end work in React and TypeScript.")
    assert "react" not in found("You will react quickly to incidents.")
    assert "react" not in found("Be able to react and adapt to change.")
    assert "react native" in found("We ship React Native apps.")


def test_spark_and_spring_and_excel_need_context():
    assert "spark" in found("Jobs on Apache Spark and PySpark.")
    assert "spark" not in found("Spark curiosity in our customers.")
    assert "spring" in found("Java with Spring Boot.") and "spring" not in found("Starts in the spring of 2027.")
    assert "excel" in found("Excel spreadsheets and PowerPoint.") and "excel" not in found("You will excel in this role.")


def test_c_and_cpp_in_one_phrase():
    assert {"c", "c++"} <= found("Systems work in C/C++.")


def test_title_counts_too_and_empty_text_is_fine():
    assert "kubernetes" in found("", title="Kubernetes Platform Engineer")
    assert found("") == set()


def test_run_writes_job_skills_and_report_counts_empty_jobs():
    con = store.connect(":memory:")
    store.upsert(con, [
        Posting("greenhouse", "1", "Data Engineer", "A", "X", "Python, SQL and Airflow", "2026", "u", "Data", None, None, "t"),
        Posting("greenhouse", "2", "Account Executive", "A", "X", "Build relationships with customers.", "2026", "u", "Sales", None, None, "t"),
    ])
    dedupe.run(con)
    per_job = extract.run(con)
    rep = extract.report(per_job)
    assert (rep["total"], rep["with_skill"], rep["empty"]) == (2, 1, 1)
    assert rep["empty_by_category"] == [("Sales", 1)]
    rows = con.execute("SELECT skill FROM job_skills ORDER BY skill").fetchall()
    assert [r[0] for r in rows] == ["airflow", "python", "sql"]
    extract.run(con)                                         # running again does not double the rows
    assert con.execute("SELECT count(*) FROM job_skills").fetchone()[0] == 3


def test_company_boilerplate_is_ignored_but_job_specific_skills_are_kept():
    con = store.connect(":memory:")
    about = "Databricks is the data and AI company built on Spark and Databricks."
    postings = []
    for i in range(12):
        postings.append(Posting(
            "greenhouse", str(i), f"Role {i}", "Databricks", "X",
            f"{about} You will write Rust services number {i}.", "2026", "u", "Eng", None, None, "t"))
    postings.append(Posting("greenhouse", "x", "Writer", "Other Co", "X", about, "2026", "u", "Eng", None, None, "t"))
    store.upsert(con, postings)
    dedupe.run(con)
    per_job = extract.run(con)
    assert per_job["greenhouse:3"][2] == {"rust"}             # the About sentence did not add "databricks"
    assert "databricks" in per_job["greenhouse:x"][2]          # a different company, no repetition, so it counts
    removed, total = extract.run.boilerplate_stats
    assert removed == 12 and total == 25


def test_skill_in_title_still_counts_even_if_description_is_boilerplate():
    assert "databricks" in skills.extract("Databricks Platform Engineer", "")


def test_a_companys_own_product_is_not_a_skill_for_its_own_jobs_unless_in_the_title():
    con = store.connect(":memory:")
    store.upsert(con, [
        Posting("greenhouse", "1", "Account Executive", "Databricks", "X", "Sell Databricks to customers. Know Python.", "2026", "u", "Sales", None, None, "t"),
        Posting("greenhouse", "2", "Principal Engineer, Elasticsearch", "Elastic", "X", "Build Elasticsearch features in Java.", "2026", "u", "Eng", None, None, "t"),
        Posting("greenhouse", "3", "Finance Analyst", "MongoDB Inc.", "X", "Work with MongoDB and SQL data.", "2026", "u", "Fin", None, None, "t"),
        Posting("greenhouse", "4", "Data Engineer", "Acme", "X", "We run on Databricks and Python.", "2026", "u", "Eng", None, None, "t"),
    ])
    dedupe.run(con)
    per_job = extract.run(con)
    assert per_job["greenhouse:1"][2] == {"python"}                     # own product dropped
    assert per_job["greenhouse:2"][2] == {"elasticsearch", "java"}      # kept: it is in the title
    assert per_job["greenhouse:3"][2] == {"sql"}                        # company name has a suffix, still matched
    assert per_job["greenhouse:4"][2] == {"databricks", "python"}       # another company: it is a real skill
