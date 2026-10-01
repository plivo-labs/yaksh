# Several personas for each scenario in a run

Not decided. An experiment to find out whether users need it.

## Problem

In a run, each scenario runs with its own persona. A user who wants to know how the agent handles the same request from different callers must change the scenario's persona and start another run.

## Idea

Two forms to try:

1. **Every combination:** the run takes a list of personas, and each scenario runs with each of them instead of its own persona. 10 scenarios and 10 personas give 100 conversations, times the repeats.
2. **Partial override:** a run-level persona changes only the settings it sets, for example the speaking pace, the language or the voice, and the rest stays the scenario persona's own. Each scenario then runs as itself and once for each override.

Other voice-agent testing tools offer one or the other.

## Risks

- The count grows fast: the run limit (200 conversations) is reached with 20 scenarios and 10 personas.
- Results are harder to read: a pass rate across personas mixes two causes.

## Open questions

- Which form, if any, do users ask for?
- Does a persona override count as a separate result in run comparison?
