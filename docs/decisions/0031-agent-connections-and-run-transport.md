# 0031 An agent has connections, and a run has a transport

Date: 2026-10-19
Status: accepted

## Context

- An agent had one `transport`, phone or text, and one `direction`, inbound or outbound. A text agent could not have a number, and a phone agent could not have an endpoint.
- A Plivo CX flow has a number or a start request, and a text-test URL, at the same time. To test it over both, a user made two agents and copied the brief, the languages and the rules into both. The results were then on two agents.
- The direction tells who starts the conversation. The transport tells how one run reaches the agent. The console showed them as one choice of three.

## Decision

- An agent keeps `direction`, and has connections: a phone connection (`agent_number` for an inbound agent, `outbound` for an outbound agent), a text `endpoint`, or both. It needs at least one. The API shows them as `transports`.
- A run has a `transport` column. `RunCreate.transport` sets it. With one connection, no value takes that connection. With two connections, a request without a value is refused. A transport that the agent does not have is refused.
- The console's run dialog shows the choice when the agent has both connections, with phone selected first, because a call is the final check. The request always names the transport.
- A conversation copies the run's transport, as before. The worker, the callers and the judges read the transport from the conversation, never from the agent.
- The trigger's agent data check applies only to phone runs, because a text run sends no trigger.
- The Plivo CX import gives every flow its text endpoint: the trigger URL with `/text-test`, with the account's Basic credentials, as the start request has them.

## Why

- One agent keeps one history. Its phone and text results are in one list, and the list filters by transport.
- A wrong default in the API could start phone calls, which cost money, or test the wrong path with no warning. So a request for an agent with both connections names its transport. The console shows the choice, so the person sees it before the run starts.

## Cost

- The schema changes `agents` and `runs`. Each existing install needs the change by hand (0010): drop `agents.transport`, add `runs.transport` from the pinned version, and remove the `transport` key from `agent_versions.config`, which `AgentConfig` no longer accepts.

## Other options

- A transport on each scenario or each conversation of a run. Rejected: a run then mixes phone and text results, and its numbers mix audio and text metrics.
- Phone as the API default for an agent with both connections. Rejected for the reason above.
