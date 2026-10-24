import pytest

from yaksh.domain.answering import AfterScreening, AnsweredBy, Answering, plays_scenario, reaches
from yaksh.domain.rules import LlmRule, PhraseExpectation, PhraseRule, RuleScope, in_scope

CALLER, VOICEMAIL, SCREENER = AnsweredBy.CALLER, AnsweredBy.VOICEMAIL, AnsweredBy.SCREENER


@pytest.mark.parametrize(
    ("answered_by", "after", "reached"),
    [
        (CALLER, AfterScreening.REPLY, {CALLER}),
        (VOICEMAIL, AfterScreening.PICKS_UP, {VOICEMAIL}),
        (SCREENER, AfterScreening.PICKS_UP, {SCREENER, CALLER}),
        (SCREENER, AfterScreening.VOICEMAIL, {SCREENER, VOICEMAIL}),
        (SCREENER, AfterScreening.REPLY, {SCREENER}),
        (SCREENER, AfterScreening.DECLINES, {SCREENER}),
    ],
)
def test_a_screener_passes_the_call_on_only_to_who_answers_after_it(
    answered_by: AnsweredBy, after: AfterScreening, reached: set[AnsweredBy]
) -> None:
    answering = Answering(after_screening=after)

    assert reaches(answered_by, answering) == reached
    assert plays_scenario(answered_by, answering) is (CALLER in reached)


def test_a_persona_with_no_answering_settings_has_the_most_common_phone() -> None:
    answering = Answering.model_validate({})

    assert (answering.voicemail, answering.screener, answering.after_screening) == (
        "iphone",
        "iphone",
        "picks_up",
    )
    assert answering.greeting is None


def test_a_stored_rule_with_no_scope_checks_only_the_calls_where_the_caller_talked() -> None:
    rule = PhraseRule.model_validate(
        {"key": "name", "name": "Says the name", "expects": "required", "value": "Swift"}
    )

    assert rule.answered_by is RuleScope.CALLER
    assert in_scope(rule, frozenset({SCREENER, CALLER}))
    assert not in_scope(rule, frozenset({VOICEMAIL}))


@pytest.mark.parametrize(
    ("scope", "reached", "checked"),
    [
        (RuleScope.VOICEMAIL, {VOICEMAIL}, True),
        (RuleScope.VOICEMAIL, {SCREENER, VOICEMAIL}, True),
        (RuleScope.VOICEMAIL, {CALLER}, False),
        (RuleScope.SCREENER, {SCREENER}, True),
        (RuleScope.SCREENER, {VOICEMAIL}, False),
        (RuleScope.ANY, {VOICEMAIL}, True),
    ],
)
def test_a_rule_checks_a_call_when_its_scope_is_among_who_answered(
    scope: RuleScope, reached: set[AnsweredBy], checked: bool
) -> None:
    rule = LlmRule(
        key="callback",
        name="Leaves a call-back number",
        applies_when="The agent leaves a message.",
        pass_when="It gives a number.",
        fail_when="It gives no number.",
        answered_by=scope,
    )
    phrase = PhraseRule(
        key="brand",
        name="Brand",
        expects=PhraseExpectation.REQUIRED,
        value="Swift",
        answered_by=scope,
    )

    assert in_scope(rule, frozenset(reached)) is checked
    assert in_scope(phrase, frozenset(reached)) is checked
