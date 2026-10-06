# Another agent version or target for one run

## Problem

A user wants to test a change before it replaces what the agent record points to: a staging deployment on another number, a new start request, or the agent's previous setup to compare with. Other voice-agent testing tools let a single run use another agent version or another target without changing the saved agent.

## Today

- A run tests the agent as it is saved: the current agent version, with its number or start request, direction and context.
- The agent version holds the target. What a conversation called is exactly what its pinned version says.
- `POST /agents/{id}/duplicate` copies an agent. The way to test another target is to duplicate the agent, change the copy, and run the copy.
- Yaksha cannot change the version inside the user's own voice platform. It can only call what the agent record points to.

## Idea

1. **Earlier version:** a run can pin an earlier agent version instead of the current one. Its number, start request and context come from that version.
2. **Target for one run:** a run can take another number, or another start request URL, for that run only. The call path reads the target from the pinned version, so showing the override is not enough: the override must be part of what each conversation freezes. Either the run creates an agent version that holds the override (a run variant, not the agent's current version), or each conversation stores the override and the call reads the pinned version plus the override.
3. Run comparison shows the version and any override on both sides.

## Open questions

- Is duplicating the agent enough, so only (1) is needed?
- For (2): a run variant version, or a stored override on each conversation?
- Which parts may change for one run: the number, the start request URL, headers, body?
- May an override change the direction (Yaksha calls, or the agent calls)? Proposal: no.
