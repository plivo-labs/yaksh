# 0009 Optional list of calling numbers

Date: 2026-09-29
Status: accepted

## Decision

An outbound agent has an optional list of numbers it calls from. Empty: Truman accepts a call from any number on the reserved Truman number. Filled: calls from other numbers are rejected and logged. The actual caller ID is always stored on the conversation.

## Why

- The reserved Truman number identifies the test. The caller ID is only an extra check.
- Agents often call from several numbers: local numbers per area, rotation, or one number per region.
- The stored caller ID lets a scenario check which number the agent used.

## Other options

- One required calling number. Rejected: agents with several numbers cannot be tested, and a wrong number looks like an unanswered call.
