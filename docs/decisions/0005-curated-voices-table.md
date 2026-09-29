# 0005 Curated voices table

Date: 2026-09-29
Status: accepted

## Decision

Personas pick voices from Truman's own `voices` table, not from a live list of the provider's voices. Built-in voices are seeded; users add a voice by its provider ID, and Truman fills the details from the provider. Each voice has its own `languages` list, which the user can edit. A persona keeps its own copy of the voice settings.

## Why

- The provider's full list is large and paged; loading it made the voice picker slow.
- The provider's language labels are incomplete. Truman needs its own list of the languages a voice can speak.
- Editing or deleting a voice never changes a persona version or a past call.

## Other options

- Live provider list in the picker. Rejected: slow, too many voices, no control over languages.
