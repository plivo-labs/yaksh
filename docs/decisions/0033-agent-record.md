# 0033 Read the agent's own record of each phone test

Date: 2026-10-24
Status: accepted

## Context

- The judges see only what Yaksh observed. A criterion about a saved value or a tool call ends "unsure, hidden action", and what the agent's speech-to-text heard is not seen at all.
- The agent's provider keeps its own record of each call. Plivo CX's agent API returns a run's lines, the values its AI nodes saved, and its tool calls. Vapi, Retell and ElevenLabs return a call record too.
- Plivo CX gives no join on Yaksh's call UUID: a run's call UUID is another leg's. Runs of calls placed together start in the same second.

## Decision

- An agent has an optional `record_source`: a provider, the agent's URL in the provider's API, and headers with `{{secrets.NAME}}`. A provider table names each provider's label, default URL, URL check and whether its record holds the live transcript. Only that table and the provider's reader know a provider.
- The evaluator reads the record before it judges a judged phone test that connected, and stores it in `agent_records`, found or missing, once. A record not final yet puts the evaluation off, without using an attempt, for up to 5 minutes after the call; then what there is is kept with a reason.
- An outbound call's record is named by the trigger's response, which `conversations.trigger_response` keeps. An inbound call's record is the agent's run that started during the call from the number Yaksh called from.
- The evidence view gets an AGENT RECORD section of saved values and tool calls, numbered R1 and up. Criteria and agent rules can quote it in `record_evidence`.
- Two items: `saved_data` (deciding: counts in the conversation verdict, not the scenario verdict) and `heard` (reporting, only when the provider's transcript is live).
- The saved values are names and values only. A step or node is left out: only Plivo CX has one.

## Why

- The record shows what the transcript cannot, from the agent's own side, with no change to the agent.
- The saved data check counts with the agent rules so that the scenario verdict and the pass rate mean the same with and without a record source.
- A wait that used attempts would fail evaluations of agents whose provider is slow.

## Cost

- One migration (0003). Evaluations of agents with a record source wait for the record: about 100 seconds after the call for Plivo CX.
- The record source holds a credential in its headers, as the text endpoint does.
- Plivo CX's run log is not a public contract; a change can stop the reader. Then the record is missing, with the reason, and no call fails for it.

## Other options

- Take the record source from the trigger URL or the text endpoint. Rejected: the run URL and the API are on different hosts, and a change to the text endpoint would break the record without notice.
- Match inbound runs by start time alone. Rejected: runs of calls placed together start in the same second.
- Show what the agent heard as a list beside the transcript. Rejected: the agent's whole transcript in the tab, with its own words, gives the heard lines their context.
