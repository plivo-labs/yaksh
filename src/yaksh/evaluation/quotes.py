"""Code checks on a judge's answer: every quote is in the turn it names, and a claim that
something never happened covers the turns it must."""

from collections.abc import Sequence
from typing import Any

from yaksh.domain.conversations import Turn
from yaksh.evaluation.canonical import canonical, contains
from yaksh.evaluation.evidence import speaker, turn_evidence


def quote_problems(
    evidence: Sequence[dict[str, Any]], turns: Sequence[Turn], *, tools: bool = False
) -> list[str]:
    """With tools, a quote can come from a turn's tool calls too: for what the agent did, not
    for what it said."""
    problems = []
    for quote in evidence:
        turn, words = quote["turn"], quote["quote"]
        if 1 <= turn <= len(turns):
            # A judge can copy the line's number and speaker label along with its words.
            label = f"{speaker(turns[turn - 1])}: "
            words = words.removeprefix(f"[{turn}] ").removeprefix(label)
        keys = (
            1 <= turn <= len(turns)
            and turns[turn - 1].dtmf
            and bool(words.strip())
            and words.strip() in turns[turn - 1].text
        )
        if not canonical(words) and not keys:
            problems.append(f"The quote for turn {turn} is empty. Quote the words that show it.")
        elif not 1 <= turn <= len(turns):
            problems.append(
                f'The quote "{words}" names turn {turn}; the call has turns 1 to {len(turns)}.'
            )
        elif not contains(turn_evidence(turns[turn - 1]) if tools else turns[turn - 1].text, words):
            problems.append(
                f'The quote "{words}" is not in turn {turn}. '
                f"Quote the words as turn {turn} has them."
            )
    return problems


def record_quote_problems(evidence: Sequence[dict[str, Any]], lines: Sequence[str]) -> list[str]:
    problems = []
    for quote in evidence:
        line, words = quote["line"], quote["quote"]
        if not canonical(words):
            problems.append(f"The quote for record line R{line} is empty. Quote the words.")
        elif not 1 <= line <= len(lines):
            have = f"lines R1 to R{len(lines)}" if lines else "no lines"
            problems.append(
                f'The quote "{words}" names record line R{line}; the record has {have}.'
            )
        elif not contains(lines[line - 1], words):
            problems.append(
                f'The quote "{words}" is not in record line R{line}. '
                f"Quote the words as R{line} has them."
            )
    return problems


def absence_problems(answer: dict[str, Any], turn_count: int) -> tuple[list[str], list[str]]:
    """Problems with a claim that something never happened: hard ones always need a new answer;
    a soft one, a claim whose turns stop before the end of the call, gets one question, because
    the item can name a window that ends earlier. A pass can rest on an absence too, such as
    "never says the date of birth"."""
    if not answer["absence"] or turn_count == 0:
        return [], []
    span = answer["absence_turns"]
    if span is None:
        return ["The answer says something never happened but gives no absence_turns."], []
    first, last = span["first"], span["last"]
    if not 1 <= first <= last <= turn_count:
        return [
            f"absence_turns {first} to {last} are not turns of this call (1 to {turn_count})."
        ], []
    if last < turn_count:
        return [], [
            f"Your claim covers turns {first} to {last}, but the call has {turn_count} turns. "
            f"Check turns {last + 1} to {turn_count} too, unless the item names a window that "
            "ends earlier."
        ]
    return [], []
