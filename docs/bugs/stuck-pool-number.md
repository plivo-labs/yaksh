# A phone number can stay leased to an ended conversation

Status: open.

## Problem

A pool number can stay in use after its conversation has ended, and nothing frees it. The pool then has one number less until someone clears it in the database.

## Cause

1. A worker claims a conversation. Its lease on the conversation lasts `TRUMAN_WORKER_LEASE_S`, 30 seconds by default.
2. The worker checks that it owns the conversation, then prepares the call. When the conversation has no number yet, `prepare_call` leases one with `lease_number` (`simulation/numbers.py`).
3. `lease_number` takes a free number and writes it to the conversation. It does not check that the conversation is still live and still claimed by this worker.
4. When the worker stops for longer than its lease between steps 2 and 3, the reaper fails the conversation with `lease_lost` and frees its numbers. It has none yet. The lease that follows gives a number to an ended conversation.
5. Nothing frees that number later. `free_numbers` takes only numbers without a conversation, `release_numbers` runs only when a live conversation ends (in `finalize` and in the reaper), and the number sync keeps the conversation of each number.

## Effect

The stop must be longer than the lease, for example on a host under heavy load or behind a slow database, so the bug is rare. Each time it happens, Truman can place one call less at a time. With 6 numbers, that is about a sixth of the capacity.

## Fix

- In `prepare_call`, lock the conversation and check that this worker still owns it before the lease: one `UPDATE ... WHERE owned_by(...) RETURNING`, which also renews the conversation's lease. A worker that no longer owns the conversation stops without a number. The lock order is then a conversation before phone numbers, as AGENTS.md states; `lease_number` breaks that order today.
- At worker start, free every number whose conversation is not live, so a number lost before the fix comes back.
- Test: let the reaper end a claimed conversation before `prepare_call` runs, then check that no number stays leased to it.
