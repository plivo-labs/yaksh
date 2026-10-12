# Sign in with ChatGPT for the models

Not decided.

## Problem

Yaksh needs an OpenAI API key for the persona model and for scenario generation. Many users already pay for ChatGPT Plus or Pro, but they must still open an API account, add billing and manage a key before their first test.

## Today

- The persona model (`caller/pipeline.py`, through Pipecat's Responses service) and scenario generation (`integrations/openai_models.py`) call the Responses API at `OPENAI_BASE_URL` with `OPENAI_API_KEY`.
- Scenario generation asks for `json_schema` output, sends `store=False` and, when the model takes it, a reasoning effort. It does not stream, and it sends `input` as one string.
- Deepgram, ElevenLabs and Plivo need their own keys. A ChatGPT plan cannot pay for speech or calls.

## What OpenAI offers

With [Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source), an app can send Responses API requests that the user's ChatGPT plan pays for. The feature is in preview.

- Who: ChatGPT Plus and Pro users. Plan usage is for "open-source projects, personal projects that run locally, and selected private apps" ([cookbook](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt)). Paid or remotely hosted apps must fill in an interest form.
- Sign-in: OAuth authorization code with PKCE in the system browser, with a loopback redirect to `http://127.0.0.1:{port}/auth/callback`. Each installation registers itself and gets its own `client_id`; there is no client secret. Access tokens last one hour, and refresh tokens rotate ([sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)).
- Requests: the usual `POST https://api.openai.com/v1/responses`, with the access token as the bearer token. `GET /v1/models` with the same token lists the models of the plan ([models](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)).
- Preview rules: each request must set `stream: true` and `store: false` and send `input` as an array. The API refuses some parameters, such as `temperature`, `max_output_tokens`, `metadata` and `background` ([limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)).
- Limits: a request over the plan's limit fails with `subscription_sharing_usage_limit_exceeded`.
- Servers: the user signs in on their own computer with the same tool, then copies the credential file to the server over a secure channel, such as SSH. The server then refreshes the tokens itself. Usage by host and revocation of copied sessions are "not yet available" ([self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)).

## Idea

1. Sign in with ChatGPT is an option next to `OPENAI_API_KEY`. With it, the persona model and scenario generation run on the user's ChatGPT plan.
2. Sign-in:
   - When Yaksh runs on the user's computer, the console starts the sign-in and the API receives the loopback redirect.
   - When Yaksh runs on a server, the CLI signs in on the user's computer and sends the credential record to the server through the API.
3. The database holds one credential record for each server: the client id, the tokens and the host id. Only one process refreshes the tokens at a time, because each refresh token works once.
4. The model lists in the console come from `GET /v1/models` with the token.
5. All model requests follow the preview rules. Scenario generation must stream and send `input` as an array.
6. A request that hits the plan limit ends the conversation as an error on Yaksh's side, with the reason. The run does not try it again at once, because the next try fails the same way.

## Risks

- Speed: the persona must answer within a phone turn. OpenAI gives no latency numbers for plan usage.
- Limits: a run can make hundreds of persona turns, so a plan limit can stop a run in the middle.
- Shared servers: a team server uses one person's plan for the runs of everyone. OpenAI does not say if this is allowed.
- Preview: the rules can change. The docs do not say if `json_schema` output and reasoning effort work, and scenario generation needs `json_schema`.
- Models: the plan may not offer the default persona model, `gpt-6-luna`.

## Open questions

- Is a self-hosted Yaksh on a remote server an "open-source project" for OpenAI, or must the project fill in the interest form?
- One plan for each server, or one for each user? Yaksh has no user accounts today.
- When the plan limit is reached, does Yaksh fall back to an API key, if one is set?
- Do Anthropic or Google offer plan usage to open-source apps?
- Is the latency good enough for the persona? Measure it before building.
