"""Find skills in a posting with the dictionary. No model, no cost, same answer every time."""
import re

from .skills_dictionary import CONTEXT_RULES, build_alias_map

ALIASES = build_alias_map()
# One pattern for every alias, longest first so "react native" is tried before "react".
_alts = "|".join(re.escape(a) for a in sorted(ALIASES, key=len, reverse=True))
# Whole words only. A skill like "c++" or ".net" has symbols in it, so the edges are checked by hand.
PATTERN = re.compile(rf"(?<![A-Za-z0-9+#.])(?:{_alts})(?![A-Za-z0-9+#])", re.IGNORECASE)


def extract(title, description):
    """Return the set of skill names found in the title and description."""
    text = f"{title or ''}\n{description or ''}"
    found = set()
    for match in PATTERN.findall(text):
        found |= ALIASES[match.lower()]
    for rule, skills in CONTEXT_RULES:
        if rule.search(text):
            found.update(skills)
    return found
