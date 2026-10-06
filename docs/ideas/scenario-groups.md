# Scenario groups

## Problem

An agent can have hundreds of scenarios, and a run starts from a hand-made selection. A user cannot keep named sets such as "smoke", "billing" or "Spanish callers", so each run means ticking the same scenarios again.

## Today

- Scenarios belong to one agent. Their name, category (happy path, messy input, edge case) and description are not versioned.
- The only groups are the fixed category and the generation batch (`generation_id`). The scenario list filters by batch.
- A selection lives in the page only. It feeds delete, and the run plan adds Run to it.

## Idea

1. Tags on scenarios: a scenario has zero or more tags, not versioned, like its name. A folder is the special case of one tag per scenario, so tags cover both.
2. The scenario list shows tag chips, filters by one or more tags, and adds or removes a tag on the selection.
3. A run can take tags instead of ids: the tagged scenarios at the moment the run starts. The run records which tags it used, and its conversations pin the scenarios as usual.
4. `GET /agents/{id}/scenarios?tag=` and a tag list with counts for the agent.

## Open questions

- Tags, or folders with one place for each scenario?
- Tags for each agent, or shared by all agents?
- "Run again" of a tag run: the same scenario ids, or the tag's scenarios at that time?
- Limits: tags for each scenario, tag length.
