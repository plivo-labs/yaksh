import json

import pytest

from yaksha.domain.scenarios import Fact
from yaksha.domain.triggers import RenderError, Trigger, agent_data_names, render

TRIGGER = Trigger.model_validate(
    {
        "url": "https://agents.example.com/calls",
        "headers": [{"name": "Authorization", "value": "Bearer {{env.YAKSHA_TRIGGER_KEY}}"}],
        "body": {
            "to": "{{yaksha.number}}",
            "customer": {"name": "{{ agent_data.Customer name }}", "vip": True},
            "tags": ["run {{yaksha.conversation_id}}", 3],
        },
    }
)
FACTS = [Fact(name="customer  NAME", value='Priya "PR" Raman\nline two')]


def test_placeholders_are_filled_inside_json_strings_without_changing_the_json() -> None:
    rendered = render(
        TRIGGER,
        number="+15716535187",
        conversation_id="c-1",
        agent_data=FACTS,
        env={"YAKSHA_TRIGGER_KEY": "sk_live"},
    )

    assert json.loads(rendered.body) == {
        "to": "+15716535187",
        "customer": {"name": 'Priya "PR" Raman\nline two', "vip": True},
        "tags": ["run c-1", 3],
    }
    assert rendered.headers == {"Authorization": "Bearer sk_live"}
    assert rendered.secrets == ("sk_live",)


@pytest.mark.parametrize(
    ("facts", "env", "missing"),
    [([], {"YAKSHA_TRIGGER_KEY": "k"}, "Customer name"), (FACTS, {}, "YAKSHA_TRIGGER_KEY")],
)
def test_a_missing_value_is_named_instead_of_sent_empty(
    facts: list[Fact], env: dict[str, str], missing: str
) -> None:
    with pytest.raises(RenderError, match=missing):
        render(TRIGGER, number="+1", conversation_id="c", agent_data=facts, env=env)


def test_the_agent_data_a_trigger_needs_is_known_before_it_is_sent() -> None:
    assert agent_data_names(TRIGGER) == {"customer name"}


def test_a_value_that_would_break_a_header_is_refused() -> None:
    trigger = Trigger.model_validate(
        {
            "url": "https://agents.example.com/calls",
            "headers": [{"name": "X-Customer", "value": "{{agent_data.Name}}"}],
            "body": {},
        }
    )
    injected = [Fact(name="Name", value="Priya\r\nX-Admin: yes")]

    with pytest.raises(RenderError, match="X-Customer header"):
        render(trigger, number="+1", conversation_id="c", agent_data=injected, env={})
