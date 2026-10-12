# Practice calls for people

Not decided.

## Problem

People practice hard conversations with a friend, or not at all. A friend plays one kind of counterpart, gets tired after a few rounds, and gives vague feedback.

## Idea

Point Yaksh at a person instead of an agent. Yaksh already generates many scenarios, plays each one with any persona, places real phone calls, records them and keeps a timed transcript. The same parts can call a person who wants to practice:

1. The person adds their own phone number in place of an agent, and describes what they practice, for example "a product manager interview at a fintech company".
2. Yaksh generates scenarios for it. Each scenario sets what the caller wants and the criteria that the person should meet.
3. A run calls the person once for each scenario and persona, for example 10 interviewers, each with a different style.
4. After each call, the person gets the recording, the transcript, a verdict for each criterion with quotes from the call, and voice metrics: talk ratio, long pauses, interruptions, response time.

The person sees what to improve across many kinds of counterpart, not one.

## Examples

| Practice | Who practices | Caller personas | What the judge checks |
| --- | --- | --- | --- |
| Job interview | A candidate | Friendly, skeptical, rushed, silent with long pauses, interrupts often, goes deep on one topic, jumps between topics, stress interviewer | Answers the question that was asked; gives a concrete example with numbers; asks a clarifying question when the question is vague; keeps each answer under two minutes |
| Sales call | A sales rep | Busy executive, price objector, gatekeeper, happy with the current vendor, buyer who cannot decide | Finds the problem before the pitch; answers the price objection without offering a discount first; ends with a next step and a date |
| Support training | A new contact-center agent | Angry customer, confused older caller, caller with a strong accent, caller who wants a refund outside the policy | Verifies identity before account details; follows the refund policy; stays calm; summarizes the outcome before the call ends |
| Language practice | A learner | Slow and patient speaker, fast native speaker, regional accent, shopkeeper, clinic receptionist | Completes the task (orders food, books an appointment); understands numbers and dates; asks for a repeat instead of guessing |
| Hard conversations | Anyone | Manager in a salary talk, landlord in a deposit dispute, customer who gets bad news | States the request clearly; gives reasons; does not stop at the first "no" |
| Pitch and media questions | A founder or a spokesperson | Skeptical investor, tough journalist, off-topic questioner | Answers in the first sentence; stays on the message; makes no claim without a fact |
| Front desk and intake | Clinic or hotel staff | Patient who needs an urgent slot, caller who books for someone else, caller who gives facts in the wrong order | Collects every required field; reads back dates and names; follows the escalation rule |
| Compliance practice | Collections or insurance agents | Debtor who disputes the debt, caller who asks for a supervisor, caller who records the call | Says every required disclosure; uses no forbidden phrase; offers the dispute process |

## What it needs

- A caller that leads. The caller prompt says "The agent drives the call" (`src/yaksh/simulation/templates/caller.j2`). An interviewer or a trainer drives the call, so the caller needs a leading mode: its own questions, follow-up questions on weak answers, and its own end of the call.
- Criteria about the person, and feedback written for a person: what went well and what to change, with quotes, not only pass or fail.
- Consent. Yaksh may call and record only the person who signed up, at their own number.
- Possibly calls in the browser instead of the phone, so that practice needs no phone line.

## Open questions

- Is this a mode of Yaksh, or a separate product on the same parts?
- Who is the user: one person, or a company that trains its staff and wants results across a team?
- How do we know the feedback is right? The questions about judge quality are the same as for agents.
