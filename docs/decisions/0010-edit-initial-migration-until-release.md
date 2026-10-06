# 0010 Edit the initial migration until the first release

Date: 2026-09-29
Status: accepted

## Decision

Until the first release, schema changes go into `0001_initial_schema.py` in place. There are no further migrations and no upgrade path. Every existing database is recreated after a schema change.

## Why

- Nobody runs Yaksha yet, so no database needs to be kept.
- One migration file shows the whole schema in one place.
- Cost: every schema change means resetting local databases.

## Other options

- A new migration for each change, with upgrade tests. Rejected until the first release: a long chain of migrations for a schema nobody has deployed.

After the first release, every schema change is a new migration, and this ADR is replaced.
