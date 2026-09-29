# 0008 Generic trigger template

Date: 2026-09-29
Status: accepted

## Decision

An outbound agent has one HTTP request template: an HTTPS URL, headers and a JSON body, sent with POST. Placeholders for the Truman number, the conversation ID, agent data and secrets are allowed only in header values and inside JSON string values. Truman parses the body, replaces placeholders inside each string, and serializes the result. Truman has no code for specific providers.

## Why

- One mechanism works for any provider API, flow or webhook.
- No provider code to maintain when a provider changes its API.
- Users send the request their system already expects, so no glue service is needed.
- Replacing inside parsed JSON strings means a value can never break the JSON, and there is no escaping rule to get wrong.
- Cost: users write the request themselves. Form bodies, other methods and URL placeholders wait for an integration that needs them.

## Other options

- Built-in integrations for each provider. Rejected: code per provider, and it breaks when their APIs change.
- A fixed request body sent to a user webhook. Rejected: every user must build a service that translates it.
- Plain text templates with escaping by `Content-Type`. Rejected: quoting and value types are ambiguous.
