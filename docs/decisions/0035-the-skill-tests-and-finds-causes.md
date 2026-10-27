# 0035 The skill tests the agent and finds the cause of each failure, and the user decides what to change

Date: 2026-10-27
Status: proposed
Changes: 0017

## Context

- Decision 0017 ships a skill that tells a coding agent how to test a voice agent and improve it in a loop.
- A change to the agent is only as good as the evidence for it. A failed item can come from the agent, but also from the test: Yaksh's caller can end a call early, a fixed date can go stale, and a judge can be wrong. A coding agent that does not find these causes changes the agent for faults of the test.
- The CLI could not add or change scenarios or agent rules, so a coding agent could not write the tests that it runs.

## Decision

- The skill covers four tasks: write scenarios and agent rules, run them, read the judges' verdicts, and find whether the agent or the test caused each failure. The coding agent reports the evidence, and the user decides what to change in the agent. A later decision can add changes to the agent.
- The CLI gets `yaksh scenario create` and `yaksh scenario update`, which read a YAML or JSON file, `yaksh scenario generate`, and `yaksh agent update --rules-file`. A YAML file keeps each value as its text, so that a date or a number with a leading zero does not change on the way to the server.
- The skill is one SKILL.md of about 5,000 tokens. The rules that protect the user come first, and the details that only some tasks need come last.

## Why

- A report that names the cause of each failure, with its evidence, lets the user act on the agent and fix the test when the test is wrong.
- One file that the agent reads at once works better than topic files that the agent must decide to load: an agent does not always load a topic when it needs it.
- Agent tools load a skill's body and keep only its start after a summary of the conversation, and their shell tools show only the start of a long output. A body near 5,000 tokens fits these limits, and `yaksh guide` can print it whole.
