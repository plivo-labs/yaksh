"""One written form for numbers, dates and times, so that a judge's quote and a phrase rule
match the transcript however the speech-to-text wrote them: "five five five, oh one four two"
and "555 0142" are both "555 0142", "two thirty p.m." and "2:30 PM" are both "2:30 pm"."""

import re
import unicodedata

UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "first": 1, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
}  # fmt: skip
""""second" is left out: it is far more often the unit of time than an ordinal."""
TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
}  # fmt: skip
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "twentieth": 20, "thirtieth": 30,
}  # fmt: skip
NUMBER_WORDS = {*UNITS, *TEENS, *TENS, "hundred", "thousand"}
YEAR_CENTURIES = {"18", "19", "20"}


def canonical(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"(?<![a-z])([ap])\.?\s?m\b\.?", r"\1m", text)
    text = re.sub(r"\b(\d{1,2})\.(\d{2})(?=\s?[ap]m\b)", r"\1:\2", text)
    text = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", text)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    found = tokens(text.replace("-", " "))
    words: list[str] = []
    run: list[str] = []
    for index, (kind, token) in enumerate(found):
        following = found[index + 1][1] if index + 1 < len(found) else ""
        if token in NUMBER_WORDS and (token != "oh" or run or following in UNITS):
            run.append(token)
            continue
        if token == "and" and run and run[-1] in {"hundred", "thousand"}:
            continue
        words += spoken(run)
        run = []
        if kind != "mark":
            words.append(token)
    words += spoken(run)
    return " ".join(words)


def tokens(text: str) -> list[tuple[str, str]]:
    """Words (letters with their combining marks, in any script), numbers (with a time's colon,
    in any script's digits, as ASCII digits) and punctuation marks, which end a run of number
    words. Spaces separate tokens."""
    found: list[tuple[str, str]] = []
    current: list[str] = []
    current_kind: str | None = None
    for char in text:
        category = unicodedata.category(char)
        if category == "Nd" or (char == ":" and current_kind == "number"):
            kind: str | None = "number"
            char = str(unicodedata.digit(char)) if category == "Nd" else char
        elif category[0] in "LM":
            kind = "word"
        elif category[0] in "PS":
            kind = "mark"
        else:
            kind = None
        if current and (kind != current_kind or kind == "mark"):
            found.append(flushed(current_kind, current))
            current = []
        if kind is not None:
            current.append(char)
        current_kind = kind
    if current:
        found.append(flushed(current_kind, current))
    return found


def flushed(kind: str | None, chars: list[str]) -> tuple[str, str]:
    text = "".join(chars)
    return (kind or "mark", text.rstrip(":") if kind == "number" else text)


def spoken(run: list[str]) -> list[str]:
    """A run of number words as digits: single digits one after another as one number, a time
    such as "two thirty" or "nine oh five" as 2:30 or 9:05, a year such as "nineteen ninety"
    as 1990."""
    if not run:
        return []
    values = numbers(run)
    if len(values) == 3 and values[1] == "0" and len(values[2]) == 1:
        if values[0] in YEAR_CENTURIES:
            return ["".join(values)]
        if 1 <= int(values[0]) <= 12:
            return [f"{values[0]}:0{values[2]}"]
    if all(len(value) == 1 for value in values):
        return ["".join(values)]
    if (
        len(values) == 2
        and all(len(value) == 2 for value in values)
        and values[0] in YEAR_CENTURIES
    ):
        return ["".join(values)]
    if len(values) == 2 and 1 <= int(values[0]) <= 12 and len(values[1]) == 2:
        return [f"{values[0]}:{values[1]}"]
    return values


def numbers(run: list[str]) -> list[str]:
    """The numbers a run of number words says, in order: "five five" is two numbers, "twenty
    one" is one, "one thousand two hundred fifty" is one."""
    found: list[int] = []
    total: int | None = None
    group: int | None = None
    after: str | None = None
    """What the last word lets the next one join: "tens" a unit, "hundred" or "thousand" any."""

    def end() -> None:
        nonlocal total, group
        if total is not None or group is not None:
            found.append((total or 0) + (group or 0))
        total = group = None

    for word in run:
        if word == "hundred":
            group, after = (group or 1) * 100, "hundred"
            continue
        if word == "thousand":
            total, group, after = (total or 0) + (group or 1) * 1000, None, "thousand"
            continue
        joins = after in {"hundred", "thousand"} or (after == "tens" and word in UNITS)
        if not joins:
            end()
        value = UNITS.get(word, TEENS.get(word, TENS.get(word, 0)))
        group = (group or 0) + value
        after = "tens" if word in TENS else None
    end()
    return [str(value) for value in found]


def compact(text: str) -> str:
    """Canonical form without the spaces between digits, so "555 0142" is "5550142" however the
    digits were grouped."""
    return re.sub(r"(?<=\d) (?=\d)", "", canonical(text))


def count(text: str, part: str) -> int:
    """How many times part is in text as whole words, not overlapping: as written, or with
    numbers, dates and times in one form, whichever finds more. Digits are not joined across
    punctuation, so "fifty. Five" holds no 505, but words are: "Okay, so your total" holds
    "okay so your total". `contains` also finds part inside a longer word, as phrase rules do."""
    written = len(re.findall(whole(part.casefold()), text.casefold()))
    one_form = compact(part)
    if not one_form:
        return written
    pieces = re.split(r"[.,;!?](?=\s|$)", text)
    joined = " ".join(piece for piece in map(compact, pieces) if piece)
    return max(written, len(re.findall(whole(one_form), joined)))


def settled(text: str) -> str:
    """The text without the number at its end: the speech to text can still add to it, as
    "fifty" becomes "fifty five"."""
    words = text.split()
    while words and (words[-1][-1].isdigit() or words[-1].casefold() in NUMBER_WORDS):
        words.pop()
    return " ".join(words)


def whole(part: str) -> str:
    """A pattern for part with no letter or digit just before or after it."""
    return rf"(?<![^\W_]){re.escape(part)}(?![^\W_])"


def contains(text: str, part: str) -> bool:
    """Whether part is in text: as written, or with numbers, dates and times in one form. The
    written compare comes first, so a quote that stops inside a spoken number, such as "twenty"
    out of "twenty five", still counts."""
    if part.casefold() in text.casefold():
        return True
    return compact(part) in compact(text)
