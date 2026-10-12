# 0026 A trigger can be a GET

Date: 2026-10-07
Status: accepted

## Decision

A trigger has a method, `POST` or `GET`. `POST` is the default, so triggers saved before this change stay as they were.

- A `POST` sends a JSON body and has no query parameters. Fixed query values can be part of the URL.
- A `GET` has no body. It sends its values as query parameters: a list of names and values, like headers. Placeholders are allowed in the values, not in the names. Yaksh fills the values, percent-encodes them and adds them after the URL's own query.
- The URL still takes no placeholders, no user name or password, and no host that ends with a dot. The HTTP client takes these out of the URL it sends, so the signed URL would not match. Send credentials in a header.
- A signed `GET` is signed over the full URL as it is sent, with the query: `HMAC-SHA256(key, delivery_id + "." + timestamp + "." + url)`. A signed `POST` is signed over its body, as before.

This changes 0008, which allowed only `POST`, and 0004, which signed only the body.

## Why

- Some agent APIs start a call with a `GET`.
- Query parameters keep the rule of 0008 that no value can change the request's shape: a value is encoded inside a parameter, as it is placed inside a JSON string for a `POST`.
- The URL stays free of placeholders, so the address checks of 0003 still see the final host.
- A `GET` has no body, so a signature over the body alone would not cover the values. The URL holds them.

## Other options

- Placeholders anywhere in the URL. Rejected: a value could change the path or the host, and the address checks run on the template.
- A body for a `GET`. Rejected: many servers and proxies drop it.
- More methods, such as `PUT`. Not now: no agent API needs one yet.
