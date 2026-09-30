# 0011 A scenario points to the persona it runs with

Date: 2026-09-30
Status: accepted

## Decision

Each scenario points to one persona. A run starts every scenario with its own persona; a single test call can still pick another. The link is not versioned: each conversation pins the persona and its version. Personas stay separate records shared by all agents, as in 0006. Scenario generation gives the chosen personas to the new scenarios in turn. A persona cannot be deleted while a live scenario points to it.

## Why

- A run of many scenarios must know which caller each one uses, without pairing them again for every run.
- Other voice-agent testing tools tie a persona to each scenario the same way.

## Cost

- 0006 rejected a persona inside the scenario because one scenario could not be tested with different callers. In a run this is true again: a scenario runs with its one persona. Testing it with another caller means changing its persona, or a single call with another persona.
- A persona that scenarios use cannot be deleted until they point to another one.

## Other options

- The run stores the scenario and persona pairs. Rejected: every run must pair them again, and generation cannot choose personas.
- Every scenario runs with every persona the run lists. Left as an idea to try later: the count grows fast, and a pass rate over mixed callers is hard to read.
