# A plugin for coding agents

Not decided.

## Problem

Truman works through its console and its HTTP API. A developer who builds a voice agent with a coding agent, such as Claude Code, must leave the coding agent to generate scenarios, start a run and read the results. Then the developer must come back and explain the failures to the coding agent.

## Idea

Ship Truman as a plugin for coding agents, in two parts:

1. **A CLI** over the HTTP API. It creates and changes agents, generates scenarios, starts a run, waits for it, and prints results, transcripts and wire events as text or JSON. The CLI is also useful alone, in scripts and in CI. Today the `truman` command only starts the API and the worker and runs migrations (`src/truman/__main__.py`), so these commands are new work.
2. **Skills** that tell a coding agent when and how to use the CLI: test a change to a voice agent, read a failed conversation (transcript, wire events, recording), find the cause, and run the failed scenarios again after a fix.

The plugin is not only for Claude Code. Skills are plain Markdown instructions and the CLI is a normal command, so any coding agent that loads plugins or skills can use the same parts.

## Risks

- Each coding agent has its own plugin format, so each one costs packaging work.
- The CLI repeats the console's flows, and both must follow every change to the API.
- Test calls cost money and take minutes. A coding agent that runs tests in a loop can place many calls, so the skills must say when a run is worth it, and the CLI must show the number of calls before a run starts.

## Open questions

- Which coding agents come first?
- Does the CLI talk to a hosted Truman, a local one, or both, and how does it get its API token?
- Does a run that a coding agent starts wait for its results, or return at once and get checked later?
