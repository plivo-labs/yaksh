"""What the evaluator reads from one saved conversation: its code metrics, its judged items and
its verdicts."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial

from yaksh.db.models import Conversation
from yaksh.domain.agent_records import StoredRecord
from yaksh.domain.agents import AgentConfig, Direction, Transport
from yaksh.domain.answering import AnsweredBy, Answering, reaches
from yaksh.domain.conversations import (
    CallerSettings,
    CallerUsage,
    LineFacts,
    Transcript,
    Turn,
    judges_score,
    picked_up,
    voicemail_answered,
)
from yaksh.domain.evaluations import DecidedBy, ItemRole, Metric, MetricKey, Outcome, UnsureKind
from yaksh.domain.files import FileStore
from yaksh.domain.language_models import JsonModel
from yaksh.domain.latency import Latency, Span, waits
from yaksh.domain.record_sources import RECORD_PROVIDERS
from yaksh.domain.rules import LlmRule, PhraseRule, in_scope
from yaksh.domain.scenarios import PlayedScenario
from yaksh.evaluation import metrics, speech
from yaksh.evaluation.caller_check import CALLER_CHECK, applied, check_caller
from yaksh.evaluation.criteria import AGENT_RULE, CRITERION, judge_criterion, judge_rule, rule_text
from yaksh.evaluation.evaluations import Evaluated
from yaksh.evaluation.evidence import CallView, record_lines, render
from yaksh.evaluation.jev import JEV, Jev
from yaksh.evaluation.judging import ItemResult
from yaksh.evaluation.limit import Slots
from yaksh.evaluation.record_checks import HEARD, SAVED_DATA, judge_heard, judge_saved_data
from yaksh.evaluation.rules import gate_open, gated, phrase_item
from yaksh.evaluation.sources import (
    HALLUCINATION,
    INSTRUCTIONS,
    Document,
    judge_hallucination,
    judge_instructions,
)
from yaksh.evaluation.verdicts import RULE, counted, verdict


@dataclass(frozen=True)
class Judging:
    """What judging needs that lives as long as the evaluator: the judge model, the stored
    judge versions by judge name, and the slots that bound the model calls in flight."""

    model: JsonModel
    sources_model: JsonModel
    """The same judge model with a longer timeout, for the judges that read the agent's whole
    instructions or documents."""
    versions: Mapping[str, uuid.UUID]
    slots: Slots
    max_input_chars: int
    """The most text one judge request holds; a judge whose sources do not fit is an error."""
    jev: Jev | None = None
    """Jev's first pass, with a TypeSafe key."""


SOURCE_JUDGES = (INSTRUCTIONS, HALLUCINATION)
"""The judges that read the agent's whole instructions or documents, with the sources model."""
JUDGES = (CRITERION, AGENT_RULE, CALLER_CHECK, *SOURCE_JUDGES, SAVED_DATA, HEARD)
"""Every judge an evaluation can name; the evaluator stores a version of each at start."""


async def evaluate(
    conversation: Conversation,
    store: FileStore,
    agent: AgentConfig,
    scenario: PlayedScenario,
    persona: str | None,
    answering: Answering,
    documents: Sequence[Document],
    judging: Judging | None,
    *,
    retry_later: bool,
    record: StoredRecord | None = None,
) -> Evaluated:
    """Code metrics for every call. A call that completed and that no one stopped also gets its
    agent's phrase rules and, with a judge model, its judges and verdicts; any other call none.
    retry_later lets a temporary judge failure put the evaluation off; on its last attempt,
    the failure is the item's error instead. Items come in order: criteria by number, rules as
    the agent lists them, instruction adherence when the agent has its instructions,
    hallucination when it has knowledge-base documents, the checks of the agent's own record
    when there is one, and last the caller check, whose findings can block criteria. A call that
    the persona's voicemail or call screener answered gets only the rules that check what it
    reached; one where the persona never talked gets no criteria, no record checks and no
    caller check, so its scenario verdict is not scored."""
    transcript = Transcript.model_validate(conversation.transcript or {})
    found = await measure_call(conversation, store, agent.agent_speaks_first)
    if not judged(conversation):
        return Evaluated(metrics=found)
    turns = transcript.turns
    reached = reaches(
        conversation.answered_by,
        picked_up=picked_up(transcript.wire_events),
        voicemail_answered=voicemail_answered(turns),
    )
    agent_rules = [rule for rule in agent.rules if in_scope(rule, reached)]
    if judging is None:
        phrases = [phrase_item(rule, turns) for rule in agent_rules if isinstance(rule, PhraseRule)]
        return Evaluated(metrics=found, items=phrases)
    view = render(call_view(conversation, agent, scenario, transcript, answering, record))
    played = AnsweredBy.CALLER in reached
    criteria_text = scenario.criteria if played else []
    kept = record.record if record is not None else None
    lines = record_lines(kept) if kept is not None else []
    open_rules = [
        rule for rule in agent_rules if isinstance(rule, LlmRule) and gate_open(rule, transcript)
    ]
    first = (
        await judging.jev.ask(
            view,
            {f"criterion-{n}": text for n, text in enumerate(criteria_text, 1)}
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
                        record_lines=lines,
                        slots=judging.slots,
                        retry_later=retry_later,
                    ),
                )
            )
            for number, criterion in enumerate(criteria_text, 1)
        ]
        caller = (
            group.create_task(
                check_caller(
                    judging.model,
                    view,
                    transcript,
                    persona,
                    criteria_text,
                    conversation.end_reason,
                    conversation.language,
                    slots=judging.slots,
                    retry_later=retry_later,
                )
            )
            if criteria_text
            else None
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
                        record_lines=lines,
                        slots=judging.slots,
                        retry_later=retry_later,
                    ),
                )
            )
            if rule in open_rules
            else rule
            for rule in agent_rules
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
                        record_lines=lines,
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
                        record_lines=lines,
                        slots=judging.slots,
                    )
                )
            )
        record_items = []
        if kept is not None and played and kept.saved:
            record_items.append(
                group.create_task(
                    judge_saved_data(
                        judging.model,
                        view,
                        turns,
                        kept,
                        slots=judging.slots,
                        retry_later=retry_later,
                    )
                )
            )
        heard = RECORD_PROVIDERS[kept.provider].live_transcript if kept is not None else False
        if kept is not None and played and heard:
            record_items.append(
                group.create_task(
                    judge_heard(
                        judging.model,
                        view,
                        turns,
                        kept,
                        slots=judging.slots,
                        retry_later=retry_later,
                    )
                )
            )
    checked = caller.result() if caller is not None else None
    items = (
        (
            applied([task.result() for task in criteria], checked, conversation.end_reason)
            if checked is not None
            else []
        )
        + [rule_item(rule, turns) for rule in rules]
        + [task.result() for task in sources]
        + [task.result() for task in record_items]
        + ([checked] if checked is not None else [])
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
    return judges_score(conversation.status, conversation.end_reason)


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
    conversation: Conversation,
    agent: AgentConfig,
    scenario: PlayedScenario,
    transcript: Transcript,
    answering: Answering,
    record: StoredRecord | None = None,
) -> CallView:
    line = parsed(LineFacts, conversation.line_facts)
    return CallView(
        brief=agent.brief,
        agent_data=list(scenario.agent_data)
        if agent.direction is Direction.OUTBOUND or conversation.transport is Transport.TEXT
        else [],
        instructions=scenario.instructions,
        known_facts=list(scenario.known_facts),
        unknown_facts=list(scenario.unknown_facts),
        today=conversation.today,
        time_zone=conversation.time_zone,
        direction=agent.direction,
        transport=conversation.transport,
        agent_number=agent.agent_number,
        yaksh_number=conversation.caller_number,
        agent_caller_id=conversation.agent_caller_id,
        hangup_source=line.hangup_source if line else None,
        end_reason=conversation.end_reason,
        talk_ms=conversation.talk_ms,
        turns=list(transcript.turns),
        answered_by=conversation.answered_by,
        answering=None if conversation.answered_by is AnsweredBy.CALLER else answering,
        events=list(transcript.wire_events),
        record=record,
    )


async def measure_call(
    conversation: Conversation, store: FileStore, agent_speaks_first: bool
) -> dict[MetricKey, Metric]:
    """The metrics of a saved call. A call that never connected has only its usage. One that
    failed before it was saved in full, or has no recording or caller replies, has no speech
    metrics: a missing value, never a zero. agent_speaks_first is the pinned agent's setting:
    without it, Yaksh's caller opens the call. The persona's voicemail or call screener is not
    a reply that waits for the agent, so its lines, and the call's start when it answers, have
    no response time."""
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
    if conversation.transport is Transport.TEXT:
        return found
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
        agent_opens=agent_speaks_first and conversation.answered_by is AnsweredBy.CALLER,
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
    replies = [reply for reply in transcript.caller_replies if reply.machine is None]
    return await speech.measure(agent, voice, rate, transcript.recording_start_ms, replies)
