"""Recents row copy. Same rules as the iOS list: skip actions that repeat the title."""

INTENT_PREFIXES = [
    ["i", "need", "to"],
    ["i", "have", "to"],
    ["i", "must"],
    ["i", "will"],
    ["ill"],
    ["i", "am", "going", "to"],
    ["im", "going", "to"],
    ["going", "to"],
    ["need", "to"],
    ["have", "to"],
    ["dont", "forget", "to"],
    ["remember", "to"],
]


def comparable_words(text):
    words = []
    current = []
    for character in text.lower():
        if character.isalnum() or character in "'’":
            current.append(character)
            continue
        if current:
            token = "".join(current).strip("'’")
            if token:
                words.append(token)
            current = []
    if current:
        token = "".join(current).strip("'’")
        if token:
            words.append(token)
    return words


def strip_intent(words):
    for prefix in INTENT_PREFIXES:
        if len(words) > len(prefix) and words[: len(prefix)] == prefix:
            return words[len(prefix) :]
    return words


def contiguous_start(needle, haystack):
    if not needle or len(haystack) < len(needle):
        return None
    last = len(haystack) - len(needle)
    width = len(needle)
    for start in range(last + 1):
        if haystack[start : start + width] == needle:
            return start
    return None


def echoes_title(action, title):
    """True when the action is the same phrase Recents already shows as the title."""
    action_words = strip_intent(comparable_words(action))
    opening = strip_intent(comparable_words(title))[:32]
    if len(action_words) < 2 or not opening:
        return False
    if opening == action_words:
        return True

    shared = 0
    for left, right in zip(opening, action_words):
        if left != right:
            break
        shared += 1
    if shared == len(action_words) or shared == len(opening):
        shorter = min(len(action_words), len(opening))
        longer = max(len(action_words), len(opening))
        if shorter >= 3 or (longer and shorter / longer >= 0.75):
            return True

    start = contiguous_start(action_words, opening)
    if start is not None and start <= 3:
        coverage = len(action_words) / len(opening)
        if len(action_words) >= 5 or coverage >= 0.6:
            return True
    return False


def todo_preview_line(items, title):
    """A distinct next action, or a count when every item repeats the preview."""
    if not items:
        return None
    for item in items:
        if not echoes_title(item, title):
            return f"To do · {item}"
    if len(items) == 1:
        return "1 to-do"
    return f"{len(items)} to-dos"
