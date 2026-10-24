# 0032 A persona's voicemail and call screener can answer outbound tests

Date: 2026-10-23
Status: accepted

## Context

- An outbound agent often reaches a voicemail or a call screener, not the person. Yaksh's caller always answered as the person, so these paths had no tests.
- A good result differs by agent: one agent must leave a message, another must hang up, a third must give its name to the screener.
- The persona's model cannot play a voicemail or a screener well. Their lines are fixed, and a tone is not speech.

## Decision

- A persona has `answering`: its voicemail type, an optional greeting, its call screener type, and what it does after screening (picks up, sends the call to voicemail, sends a reply, declines). The defaults are iPhone voicemail, iPhone call screening and picks up.
- Each scenario of a run has `answered_by`: `caller`, `voicemail`, `screener`, or more than one. Each answer is its own conversation. `voicemail` and `screener` apply only to phone runs of an outbound agent.
- The standard greetings, the screener lines and the tone are recorded files in the repo, made once with `scripts/make_answering_clips.py`. A persona's own greeting is spoken in its voice when the call starts. A gate keeps the persona's model silent while a machine line plays.
- When the persona picks up after screening, it says the scenario's first words, or "Hello", as at a normal pickup. Its context has the agent's answers to the screener and one note that it picked up.
- A call where the persona never talks has no criteria and no caller check, so its scenario verdict is not scored. Agent rules have `answered_by` (`caller`, `voicemail`, `screener` or `any`), and only the rules for what the call reached judge it. Existing rules check the caller.
- The run numbers use only the calls where the persona talked. The calls where it did not are listed apart, with their verdict from the agent rules, and `yaksh run start --wait` needs them to pass.
- Two end reasons: `voicemail_ended` and `screener_ended`. The caller reason says why.

## Why

- No built-in pass or fail: agents differ, so the user's rules decide. The run dialog warns when no deciding rule checks an answer, and the conversation page shows two plain voicemail facts: if the agent talked over the greeting, and the length of its message.
- Recorded lines sound the same on every call, cost nothing per call, and do not depend on a model.
- Answers on the scenario of a run, not on the scenario itself, so one scenario tests the caller, the voicemail and the screener without copies.

## Cost

- Migration 0002: the `answered_by` enum and column on `conversations` (default `caller`), the unique key with `answered_by`, `personas.answering`, and the two end reasons.
- The hold, wait and silence times are estimates from public descriptions, not measured on real phones.
- The recorded lines are English only.

## Other options

- The persona's model plays the voicemail or screener. Rejected: the lines change on each call, and the model cannot make the tone.
- A built-in voicemail check, such as "leaves a call-back number". Rejected: what is correct depends on the agent.
- `answered_by` on the scenario. Rejected: the same scenario would need one copy for each answer.
