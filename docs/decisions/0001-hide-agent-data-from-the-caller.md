# 0001 Hide agent data from the caller

Date: 2026-09-29
Status: accepted

## Decision

In an outbound scenario, agent data goes only to the agent (through the trigger). The simulated caller never sees it. The caller has its own known facts.

## Why

- The test checks what the agent does with its data. If the agent says "you owe 50,000" and the agent data says 5,000, a caller that knows 5,000 may correct it, and the bug stays hidden.
- A real person does not know what is in the agent's system.
- The judge sees both lists and can compare them.

## Other options

- The caller sees the agent data. Rejected: the caller becomes too smart and hides agent mistakes. It would save typing values that both sides know, such as the caller's name.
