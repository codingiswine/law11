import html, re
from typing import List, Dict


def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def unique_preserve_order(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen, result = set(), []
    for it in items:
        title = it.get("title")
        if title and title not in seen:
            seen.add(title)
            result.append(it)
    return result
