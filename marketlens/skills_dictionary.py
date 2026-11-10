"""The skill dictionary: each skill and the words that mean it.

SKILLS maps a skill name to the spellings that count. Matching ignores case and needs whole words, so "java" does
not match inside "javascript".

CONTEXT_RULES is for words that are also ordinary English or ordinary names ("Go", "R", "Swift", "React", "Spark",
"Spring", "Excel"). Each rule is a pattern that only fires when the surrounding words show it is the technology.
"""
import re

SKILLS = {
    # languages
    "python": ["python", "python3"],
    "java": ["java"],
    "javascript": ["javascript", "js", "ecmascript"],
    "typescript": ["typescript"],
    "c++": ["c++", "cpp"],
    "c#": ["c#", "csharp"],
    "ruby": ["ruby"],
    "php": ["php"],
    "kotlin": ["kotlin"],
    "scala": ["scala"],
    "rust": ["rust"],
    "sql": ["sql", "t-sql", "pl/sql"],
    "bash": ["bash", "shell scripting", "shell scripts"],
    "matlab": ["matlab"],
    "perl": ["perl"],
    "objective-c": ["objective-c", "objc"],
    "elixir": ["elixir"],
    "dart": ["dart"],
    "golang": ["golang"],
    # data
    "postgresql": ["postgresql", "postgres"],
    "mysql": ["mysql"],
    "sqlite": ["sqlite"],
    "oracle": ["oracle database", "oracle db", "pl/sql"],
    "snowflake": ["snowflake"],
    "bigquery": ["bigquery"],
    "redshift": ["redshift"],
    "databricks": ["databricks"],
    "spark": ["apache spark", "pyspark", "spark sql", "spark streaming"],
    "hadoop": ["hadoop", "hdfs", "mapreduce"],
    "kafka": ["kafka"],
    "airflow": ["airflow"],
    "dbt": ["dbt"],
    "flink": ["flink"],
    "hive": ["apache hive"],
    "trino": ["trino", "presto"],
    "clickhouse": ["clickhouse"],
    "mongodb": ["mongodb", "mongo db"],
    "redis": ["redis"],
    "elasticsearch": ["elasticsearch", "opensearch"],
    "cassandra": ["cassandra"],
    "dynamodb": ["dynamodb"],
    "tableau": ["tableau"],
    "power bi": ["power bi", "powerbi"],
    "looker": ["looker"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "etl": ["etl", "elt", "data pipelines", "data pipeline"],
    "data modeling": ["data modeling", "data modelling"],
    "data warehouse": ["data warehouse", "data warehousing"],
    # machine learning
    "machine learning": ["machine learning", "ml models"],
    "deep learning": ["deep learning", "neural networks"],
    "pytorch": ["pytorch"],
    "tensorflow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "nlp": ["nlp", "natural language processing"],
    "llm": ["llm", "llms", "large language models", "large language model"],
    "generative ai": ["generative ai", "genai", "gen ai"],
    "computer vision": ["computer vision"],
    "reinforcement learning": ["reinforcement learning"],
    "mlops": ["mlops"],
    "hugging face": ["hugging face", "huggingface"],
    "langchain": ["langchain"],
    "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    "xgboost": ["xgboost"],
    "statistics": ["statistics", "statistical analysis", "statistical modeling"],
    "a/b testing": ["a/b testing", "a/b tests", "ab testing"],
    # cloud and devops
    "aws": ["aws", "amazon web services"],
    "azure": ["azure"],
    "gcp": ["gcp", "google cloud"],
    "kubernetes": ["kubernetes", "k8s"],
    "docker": ["docker", "containers", "containerization"],
    "terraform": ["terraform"],
    "ansible": ["ansible"],
    "jenkins": ["jenkins"],
    "ci/cd": ["ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment"],
    "github actions": ["github actions"],
    "linux": ["linux", "unix"],
    "git": ["git", "github", "gitlab"],
    "prometheus": ["prometheus"],
    "grafana": ["grafana"],
    "datadog": ["datadog"],
    "microservices": ["microservices", "microservice"],
    "rest apis": ["rest apis", "rest api", "restful", "restful apis"],
    "graphql": ["graphql"],
    "grpc": ["grpc"],
    "serverless": ["serverless"],
    "distributed systems": ["distributed systems", "distributed system"],
    # web and mobile
    "angular": ["angular", "angularjs"],
    "vue": ["vue", "vue.js", "vuejs"],
    "next.js": ["next.js", "nextjs"],
    "node.js": ["node.js", "nodejs"],
    "django": ["django"],
    "flask": ["flask"],
    "fastapi": ["fastapi"],
    "ruby on rails": ["ruby on rails"],
    ".net": [".net", "asp.net", "dotnet"],
    "html": ["html", "html5"],
    "css": ["css", "css3", "sass"],
    "tailwind": ["tailwind", "tailwindcss"],
    "redux": ["redux"],
    "ios": ["ios"],
    "android": ["android"],
    "react native": ["react native"],
    "flutter": ["flutter"],
    "swiftui": ["swiftui"],
    # security
    "penetration testing": ["penetration testing", "pentesting", "pen testing"],
    "siem": ["siem", "splunk"],
    "owasp": ["owasp"],
    "soc 2": ["soc 2", "soc2"],
    "iam": ["iam", "identity and access management"],
    # business tools
    "salesforce": ["salesforce"],
    "hubspot": ["hubspot"],
    "excel": ["microsoft excel", "ms excel", "advanced excel"],
    "jira": ["jira"],
    "figma": ["figma"],
    "agile": ["agile", "scrum", "kanban"],
    "sap": ["sap"],
    "netsuite": ["netsuite"],
    "workday": ["workday"],
    "zendesk": ["zendesk"],
}

# Rules that need case or the words around them. Each is (pattern, skills it means). Patterns are case sensitive.
_LANGS = r"(?:Python|Java|JavaScript|TypeScript|Rust|C\+\+|C#|Kotlin|Scala|Ruby|SQL|Go|R|Swift)"
CONTEXT_RULES = [
    # "Python, Go" or "Go, Rust": Go is the language only when it sits in a list of languages.
    (re.compile(rf"(?:{_LANGS}\s*[,/]\s*Go\b|\bGo\s*[,/]\s*{_LANGS})"), ("go",)),
    (re.compile(r"\b(?:Golang)\b"), ("go",)),
    # R the language: in a list of languages, or "R programming", or "R and Python".
    (re.compile(rf"(?:{_LANGS}\s*(?:,|/|and|or)\s*R\b(?!\s*&)|\bR\s*(?:,|/|and|or)\s*{_LANGS}|\bR\s+programming)"), ("r",)),
    (re.compile(r"\bC/C\+\+"), ("c", "c++")),
    (re.compile(r"\bC\s+programming\b|\bC,\s*C\+\+"), ("c",)),
    # Swift the language is written "Swift". SWIFT (the bank network) is all capitals and stays out.
    (re.compile(r"\bSwift\b(?!-)"), ("swift",)),
    # React, but not "react quickly" or "react to".
    (re.compile(r"\bReact(?:\.js|JS)?\b(?!\s+(?:to|quickly|appropriately|well|calmly|swiftly|and\s+(?:adapt|respond|resolve|escalate|act)))"), ("react",)),
    # Spring only as the Java framework.
    (re.compile(r"\bSpring\s*(?:Boot|Framework|MVC)\b"), ("spring",)),
    # Excel the spreadsheet: "Excel" next to other office tools or spreadsheet words.
    (re.compile(r"\bExcel\b(?=\s*(?:,|/|and|&)\s*(?:Word|PowerPoint|Google Sheets|Sheets|SQL|VBA)|\s+(?:spreadsheets?|VBA|macros|models?|formulas|pivot))"), ("excel",)),
]


def build_alias_map():
    """alias (lower case) -> skills it means."""
    out = {}
    for skill, aliases in SKILLS.items():
        for a in aliases:
            out.setdefault(a.lower(), set()).add(skill)
    return out
