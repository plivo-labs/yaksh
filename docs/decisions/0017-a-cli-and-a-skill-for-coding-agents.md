# 0017 A CLI and a skill for coding agents

Date: 2026-10-04
Status: accepted

## Decision

Truman ships `truman`, a command-line client for its HTTP API, in `cli/`, and a skill that tells a coding agent how to test a voice agent with it (`cli/skill/SKILL.md`; `truman guide` prints it). There is no MCP server for now.

- The CLI is written in Go, in its own module. Its API client is generated from `cli/openapi.json` with oapi-codegen, and CI fails when the spec or the client is out of date.
- The CLI is a thin wrapper. A command for a resource makes one API call, its flags match the API's fields, and the API's default applies when a flag is not set. The only logic beyond single calls: waiting, reading every page of scenarios for `run start --all`, and the check of the server and token in `truman auth login`.
- Waiting: `run wait`, `run start --wait` (Ctrl-C or SIGTERM cancels the run), `run cancel` (waits until the run is cancelled) and `conversation start --wait` (streams the call's events). The CLI does not retry or reconnect. When waiting or following fails, the error gives the next command to run; other errors say what failed.
- Standard output holds JSON only. A command for a resource prints the server's JSON body, indented. `conversation start --wait` writes one line for each event, as `{"event", "data"}`, and the conversation itself last. `version` and `auth status` print JSON of their own, and `truman guide` prints the skill. Progress, hints and errors go to standard error. The exit code is 0 when the command worked, and 1 otherwise.
- `truman auth login` saves the server and the token in `$XDG_CONFIG_HOME/truman/config.json`, or `~/.config/truman/config.json` when `XDG_CONFIG_HOME` is not set, readable by the user only. `TRUMAN_URL` and `TRUMAN_API_TOKEN` override the file.
- The server's command is `truman-server`, so that `truman` names the client.

## Why

- Coding agents are the main users, and CI must work without a coding agent. A command serves both. A skill is plain Markdown that many coding agents load.
- A Go build is one file with no runtime to install: 10.7 MB for the CLI (7.2 MB stripped). In a test on 2 October 2026, Bun builds of a small CLI were 58 to 77 MB.
- The server's own JSON needs no output format of our own, and a coding agent reads JSON well. Regenerating the client brings in an API change's types and calls; a new field still needs its flag in the command.
- Waiting is the one thing that single requests do badly: a run takes minutes, and a stop must not leave paid calls on the line or lose a run's ID.

## Cost

- The commands cover the test loop: agents, scenarios and personas to read, runs, conversations, auth, the version and the guide. Other API calls have no command yet.
- The CI check catches an out-of-date spec or client, not a command that misses a new API field.
- The generated method names come from FastAPI's default operation IDs, so they are long. Users do not see them.

## Other options

- An MCP server. Not now: the CLI also works in CI with no coding agent, and coding agents run commands well. An MCP server can come later on the same API.
- A Python CLI in the server's package. Rejected: users would need Python and a package index; see 0018 for the install.
- TypeScript with Bun, or Rust. Both were compared with Go. Bun's builds are several times larger, and Go's release tool (GoReleaser) covers the platforms and signing that we need.
- Verdicts from a judge in the CLI's output. Later, when the judge exists.
