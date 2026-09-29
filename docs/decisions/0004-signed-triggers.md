# 0004 Triggers are signed

Date: 2026-09-29
Status: accepted

## Decision

When `TRUMAN_WEBHOOK_SIGNING_KEY` is set, every trigger request carries:

```
X-Truman-Delivery: <conversation id>
X-Truman-Timestamp: <unix seconds>
X-Truman-Signature: v1=<hex HMAC-SHA256(key, delivery_id + "." + timestamp + "." + raw body)>
```

The receiving endpoint rejects a timestamp more than 5 minutes in the past or the future, recomputes the HMAC and compares in constant time, and only then records the delivery ID atomically, rejecting one it has seen. Without the key, no signature headers are sent.

## Why

- A user's own trigger endpoint can check that the request came from Truman and is recent.
- The key never travels in the request. The timestamp limits the replay window, and the delivery ID stops duplicates inside it. Truman never resends a trigger, so a repeated delivery ID is always a replay.
- The delivery ID is signed, so a replayed request cannot change it to get past the duplicate check.
- The key is outside the `TRUMAN_TRIGGER_` prefix, so a trigger template cannot send it.
- The same scheme as the common webhook signing convention (signed ID, timestamp and body), so users know how to verify it.

## Other options

- A shared secret sent as a header. Rejected: the secret travels with every request, and a copied request can be replayed.
- No signing. Rejected: an endpoint that starts real calls cannot tell who sent the request. Hosted voice-agent APIs check their own API key, so signing matters for users' own webhooks.
- Signing only the timestamp and body. Rejected: the delivery ID could be changed on a replay.
