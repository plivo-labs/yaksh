# 0024 The caller check judges the test, not the caller prompt

Date: 2026-10-06
Status: accepted

## Decision

The caller check gets the scenario goal and facts (from the view) and the persona. It does not get the caller's general prompt rules. It blames the caller only for a wrong fact, an act against the goal, an invented value, a scripted line not said although the caller had a turn, or a hang-up that the goal did not allow.

## Why

- The general rules, such as "end the call only when your goal is achieved" and "one thing at a time", steer the caller model. When the check used them, it blamed an early answer, a scripted "Bye" and hang-ups that the agent made. Each wrong blame hid an agent failure.
- On 48 stored TeleCRM calls: false blames went from 4 to 8 to 0; the check still found 13 to 14 of 15 real breaks.
- Benchmark: https://glance.plivo.com/kishan-kumar/yaksha-caller-check-benchmark
