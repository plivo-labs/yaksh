"""What the evaluator reads from one saved conversation: its code metrics, its judged items and
its verdicts."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial

from yaksha.db.models import Conversation
from yaksha.domain.agents import AgentConfig, Direction
from yaksha.domain.conversations import (
    CallerSettings,
    CallerUsage,
    ConversationStatus,
    EndReason,
    LineFacts,
    Transcript,
    Turn,
)
from yaksha.domain.evaluations import DecidedBy, ItemRole, Metric, MetricKey, Outcome, UnsureKind
from yaksha.domain.files import FileStore
from yaksha.domain.language_models import JsonModel
from yaksha.domain.latency import Latency, Span, waits
from yaksha.domain.rules import LlmRule, PhraseRule
from yaksha.domain.scenarios import PlayedScenario
from yaksha.evaluation import metrics, speech
from yaksha.evaluation.caller_check import CALLER_CHECK, applied, check_caller
from yaksha.evaluation.criteria import AGENT_RULE, CRITERION, judge_criterion, judge_rule, rule_text
from yaksha.evaluation.evaluations import Evaluated
from yaksha.evaluation.evidence import CallView, render
from yaksha.evaluation.jev import JEV, Jev
from yaksha.evaluation.judging import ItemResult
from yaksha.evaluation.rules import gate_open, gated, phrase_item
from yaksha.evaluation.sources import (
    HALLUCINATION,
    INSTRUCTIONS,
    Document,
    judge_hallucination,
    judge_instructions,
)
from yaksha.evaluation.verdicts import RULE, counted, verdict


@dataclass(frozen=True)
class Judging:
    """What judging needs that lives as long as the evaluator: the judge model, the stored
    judge versions by judge name, and the slots that bound the model calls in flight."""

    model: JsonModel
    sources_model: JsonModel
    """The same judge model with a longer timeout, for the judges that read the agent's whole
    instructions or documents."""
    versions: Mapping[str, uuid.UUID]
    slots: asyncio.Semaphore
    max_input_chars: int
    """The most text one judge request holds; a judge whose sources do not fit is an error."""
    jev: Jev | None = None
    """Jev's first pass, with a TypeSafe key."""


SOURCE_JUDGES = (INSTRUCTIONS, HALLUCINATION)
"""The judges that read the agent's whole instructions or documents, with the sources model."""
JUDGES = (CRITERION, AGENT_RULE, CALLER_CHECK, *SOURCE_JUDGES)
"""Every judge an evaluation can name; the evaluator stores a version of each at start."""


async def evaluate(
    conversation: Conversation,
    store: FileStore,
    agent: AgentConfig,
    scenario: PlayedScenario,
    persona: str | None,
    documents: Sequence[Document],
    judging: Judging | None,
    *,
    retry_later: bool,
) -> Evaluated:
    """Code metrics for every call. A call that completed and that no one stopped also gets its
    agent's phrase rules and, with a judge model, its judges and verdicts; any other call none.
    retry_later lets a temporary judge failure put the evaluation off; on its last attempt,
    the failure is the item's error instead. Items come in order: criteria by number, rules as
    the agent lists them, instruction adherence when the agent has its instructions,
    hallucination when it has knowledge-base documents, and last the caller check, whose
    findings can block criteria."""
    transcript = Transcript.model_validate(conversation.transcript or {})
    found = await measure_call(conversation, store, agent.agent_speaks_first)
    if not judged(conversation):
        return Evaluated(metrics=found)
    turns = transcript.turns
    if judging is None:
        phrases = [phrase_item(rule, turns) for rule in agent.rules if isinstance(rule, PhraseRule)]
        return Evaluated(metrics=found, items=phrases)
    view = render(call_view(conversation, agent, scenario, transcript))
    open_rules = [
        rule for rule in agent.rules if isinstance(rule, LlmRule) and gate_open(rule, transcript)
    ]
    first = (
        await judging.jev.ask(
            view,
            {f"criterion-{n}": text for n, text in enumerate(scenario.criteria, 1)}
            | {f"{RULE}{rule.key}": rule_text(rule) for rule in open_rules},
        )
        if judging.jev is not None
        else None
    )
    bar = judging.jev.pass_bar if judging.jev is not None else 1.0
    answers = first.answers if first is not None else {}

    async def decided(
        key: str, subject: str, role: ItemRole, judge: Callable[[], Awaitable[ItemResult]]
    ) -> ItemResult:
        """Jev's confident pass, or the judge model's answer with Jev's beside it."""
        answer = answers.get(key)
        if answer is not None and answer.passes(bar):
            return ItemResult(
                key=key,
                subject=subject,
                judge=JEV.name,
                decided_by=DecidedBy.JEV,
                role=role,
                outcome=Outcome.PASS,
                jev_choice=answer.choice,
                jev_probabilities=answer.probabilities,
            )
        item = await judge()
        if answer is None:
            return item
        return replace(item, jev_choice=answer.choice, jev_probabilities=answer.probabilities)

    async with asyncio.TaskGroup() as group:
        criteria = [
            group.create_task(
                decided(
                    f"criterion-{number}",
                    criterion,
                    ItemRole.DECIDING,
                    partial(
                        judge_criterion,
                        judging.model,
                        view,
                        turns,
                        number,
                        criterion,
                        slots=judging.slots,
                        retry_later=retry_later,
                    ),
                )
            )
            for number, criterion in enumerate(scenario.criteria, 1)
        ]
        caller = group.create_task(
            check_caller(
                judging.model,
                view,
                transcript,
                persona,
                scenario.criteria,
                conversation.end_reason,
                conversation.language,
                slots=judging.slots,
                retry_later=retry_later,
            )
        )
        rules = [
            group.create_task(
                decided(
                    f"{RULE}{rule.key}",
                    rule.name,
                    rule.role,
                    partial(
                        judge_rule,
                        judging.model,
                        view,
                        turns,
                        rule,
                        slots=judging.slots,
                        retry_later=retry_later,
                    ),
                )
            )
            if rule in open_rules
            else rule
            for rule in agent.rules
        ]
        sources = []
        if agent.config:
            sources.append(
                group.create_task(
                    judge_instructions(
                        judging.sources_model,
                        view,
                        turns,
                        agent.config,
                        judging.max_input_chars,
                        slots=judging.slots,
                    )
                )
            )
        if documents:
            sources.append(
                group.create_task(
                    judge_hallucination(
                        judging.sources_model,
                        view,
                        turns,
                        documents,
                        agent.config,
                        judging.max_input_chars,
                        slots=judging.slots,
                    )
                )
            )
    checked = caller.result()
    items = (
        applied([task.result() for task in criteria], checked, conversation.end_reason)
        + [rule_item(rule, turns) for rule in rules]
        + [task.result() for task in sources]
        + [checked]
    )
    return Evaluated(
        metrics=found,
        items=items,
        scenario_verdict=verdict(outcomes(items, criteria_only=True)),
        conversation_verdict=verdict(outcomes(items, criteria_only=False)),
        judge_versions=judging.versions,
        jev_usage=first.usage if first is not None else None,
    )


def rule_item(
    rule: asyncio.Task[ItemResult] | LlmRule | PhraseRule, turns: list[Turn]
) -> ItemResult:
    """An agent rule's item: its judge's answer, its phrase check, or its shut gate."""
    if isinstance(rule, asyncio.Task):
        return rule.result()
    if isinstance(rule, PhraseRule):
        return phrase_item(rule, turns)
    return gated(rule)


def judged(conversation: Conversation) -> bool:
    return (
        conversation.status is ConversationStatus.COMPLETED
        and conversation.end_reason is not EndReason.USER_REQUEST
    )


def outcomes(
    items: list[ItemResult], *, criteria_only: bool
) -> list[tuple[Outcome, UnsureKind | None]]:
    """The outcomes a verdict counts: the criteria, and for the conversation verdict also the
    agent rules that decide."""
    return [
        (item.outcome, item.unsure_kind)
        for item in items
        if counted(item.key, item.role, criteria_only=criteria_only)
    ]


def call_view(
    conversation: Conversation, agent: AgentConfig, scenario: PlayedScenario, transcript: Transcript
) -> CallView:
    line = parsed(LineFacts, conversation.line_facts)
    return CallView(
        brief=agent.brief,
        agent_data=list(scenario.agent_data) if agent.direction is Direction.OUTBOUND else [],
        instructions=scenario.instructions,
        known_facts=list(scenario.known_facts),
        unknown_facts=list(scenario.unknown_facts),
        today=conversation.today,
        time_zone=conversation.time_zone,
        direction=agent.direction,
        agent_number=agent.agent_number,
        yaksha_number=conversation.caller_number,
        agent_caller_id=conversation.agent_caller_id,
        hangup_source=line.hangup_source if line else None,
        end_reason=conversation.end_reason,
        talk_ms=conversation.talk_ms,
        turns=list(transcript.turns),
    )


async def measure_call(
    conversation: Conversation, store: FileStore, agent_speaks_first: bool
) -> dict[MetricKey, Metric]:
    """The metrics of a saved call. A call that never connected has only its usage. One that
    failed before it was saved in full, or has no recording or caller replies, has no speech
    metrics: a missing value, never a zero. agent_speaks_first is the pinned agent's setting:
    without it, Yaksha's caller opens the call."""
    transcript = Transcript.model_validate(conversation.transcript or {})
    found = {
        MetricKey.USAGE: metrics.usage(
            transcript,
            parsed(CallerSettings, conversation.caller_settings),
            parsed(CallerUsage, conversation.caller_usage),
            parsed(LineFacts, conversation.line_facts),
        )
    }
    if not transcript.connected:
        return found
    found[MetricKey.AGENT_REPETITION] = metrics.agent_repetition(transcript.turns)
    opened = transcript.stream_opened_ms
    if opened is None:
        found[MetricKey.CAPTURE_FAULTS] = metrics.incomplete_record()
        return found
    gaps = media_gaps(transcript, opened)
    found[MetricKey.CAPTURE_FAULTS] = metrics.capture_faults(
        transcript, conversation.recording_key is not None, gaps
    )
    heard = await hear(conversation, transcript, store)
    if heard is None:
        return found
    goodbye = metrics.goodbye_from(transcript)
    paired = waits(
        opened,
        heard.replies,
        heard.speech.agent,
        heard.end_ms,
        goodbye_from_ms=goodbye,
        gaps=gaps,
        agent_opens=agent_speaks_first,
    )
    found[MetricKey.SPEECH] = Metric(value=heard.speech.model_dump(mode="json"))
    found[MetricKey.RESPONSE_TIME] = Metric(value=Latency.answered(paired).model_dump(mode="json"))
    found[MetricKey.TURN_TAKING] = metrics.turn_taking(paired)
    found[MetricKey.SPEAKING] = metrics.speaking(heard.speech, goodbye)
    return found


def media_gaps(transcript: Transcript, stream_opened_ms: int | None) -> list[Span]:
    """Where no media came from the agent's side, from the stream's opening on."""
    media = transcript.agent_media
    if media is None:
        return []
    if stream_opened_ms is None or media.first_ms <= stream_opened_ms:
        return media.gaps
    return [Span(start_ms=stream_opened_ms, end_ms=media.first_ms), *media.gaps]


def parsed[T: (CallerSettings, CallerUsage, LineFacts)](
    model: type[T], stored: dict[str, object] | None
) -> T | None:
    return None if stored is None else model.model_validate(stored)


async def hear(
    conversation: Conversation, transcript: Transcript, store: FileStore
) -> speech.Heard | None:
    """Both sides' speech; None for a call without a recording or its caller replies."""
    if (
        conversation.recording_key is None
        or transcript.recording_start_ms is None
        or transcript.caller_replies is None
    ):
        return None
    recording = await store.get(conversation.recording_key)
    agent, rate = await asyncio.to_thread(speech.read_mono, recording)
    voice = b""
    if conversation.caller_voice_key is not None:
        caller_voice = await store.get(conversation.caller_voice_key)
        voice, voice_rate = await asyncio.to_thread(speech.read_mono, caller_voice)
        if voice_rate != rate:
            raise ValueError(f"the caller voice is at {voice_rate} Hz, the recording at {rate} Hz")
    return await speech.measure(
        agent, voice, rate, transcript.recording_start_ms, transcript.caller_replies
    )
