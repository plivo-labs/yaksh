# 0006 Persona separate from scenario

Date: 2026-09-29
Status: accepted

## Decision

A persona is how the caller behaves: style, language and voice. A scenario is what the caller wants: goal, facts and criteria. A conversation picks one of each.

## Why

- One scenario runs with many callers, and one caller runs across many scenarios.
- Scenarios belong to an agent; personas are shared by all agents.

## Other options

- Persona inside the scenario. Rejected: the same caller is copied into every scenario, and one scenario cannot be tested with different callers.
