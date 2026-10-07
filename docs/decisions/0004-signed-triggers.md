# 0004 Triggers are signed

Date: 2026-09-29
Status: accepted, changed by 0026 (GET triggers) and 0027 (the key is on the Settings page)

## Decision

Every trigger carries `X-Yaksha-Delivery: <conversation id>`, so the receiver can drop duplicates. When `YAKSHA_WEBHOOK_SIGNING_KEY` is set, every trigger also carries:

```
X-Yaksha-Timestamp: <unix seconds>
X-Yaksha-Signature: v1=<hex HMAC-SHA256(key, delivery_id + "." + timestamp + "." + raw body)>
```

The receiving endpoint rejects a timestamp more than 5 minutes in the past or the future, recomputes the HMAC and compares in constant time, and only then records the delivery ID atomically, rejecting one it has seen. Without the key, only `X-Yaksha-Delivery` is sent.

## Why

- A user's own trigger endpoint can check that the request came from Yaksha and is recent.
- The key never travels in the request. The timestamp limits the replay window, and the delivery ID stops duplicates inside it. Yaksha never resends a trigger, so a repeated delivery ID is always a replay.
- The delivery ID is signed, so a replayed request cannot change it to get past the duplicate check.
- The key is outside the `YAKSHA_TRIGGER_` prefix, so a trigger template cannot send it.
- The same scheme as the common webhook signing convention (signed ID, timestamp and body), so users know how to verify it.

## Other options

- A shared secret sent as a header. Rejected: the secret travels with every request, and a copied request can be replayed.
- No signing. Rejected: an endpoint that starts real calls cannot tell who sent the request. Hosted voice-agent APIs check their own API key, so signing matters for users' own webhooks.
- Signing only the timestamp and body. Rejected: the delivery ID could be changed on a replay.
