# 0017 A CLI and a skill for coding agents

Date: 2026-10-04, judge verdicts added 2026-10-05
Status: accepted

## Decision

Yaksha ships `yaksha`, a command-line client for its HTTP API, in `cli/`, and a skill that tells a coding agent how to test a voice agent with it and improve it in a loop (`cli/skill/yaksha/SKILL.md`; `yaksha guide` prints it). There is no MCP server for now.

- The CLI is written in Go, in its own module. Its API client is generated from `cli/openapi.json` with oapi-codegen, and CI fails when the spec or the client is out of date.
- The CLI is a thin wrapper. A command for a resource makes one API call, its flags match the API's fields, and the API's default applies when a flag is not set. The only logic beyond single calls: waiting, the exit code from the run's result, reading every page of scenarios for `run start --all`, and the check of the server and token in `yaksha auth login`.
- Waiting: `run wait` and `run start --wait` wait for the run to end and then for the judges' verdicts (Ctrl-C or SIGTERM during `run start --wait` cancels a run that is still going); `run cancel` waits until the run ends (a run that had already ended keeps its status, `done` or `cancelled`). One `--timeout` covers both waits of a command; without it, the wait for the judges stops after 10 minutes. The CLI does not retry or reconnect. When waiting fails, the error gives the next command to run; other errors say what failed.
- Standard output holds JSON only. A command for a resource prints the server's JSON body, indented. `version` and `auth status` print JSON of their own, and `yaksha guide` prints the skill. Progress, hints and errors go to standard error. The exit code is 0 when the command worked, and 1 otherwise. A test that ran and did not pass prints `failed:` on standard error, and a command that went wrong prints `error:`. A run that the CLI waited for works only when every call completed and the judges passed every call, each by its scenario verdict after people's labels, as the run's pass rate counts it. A call that the judges did not score, or whose evaluation failed, proves nothing, so it does not pass. With the judges off, no call gets a verdict, and completed calls are enough.
- `yaksha auth login` saves the server and the token in `$XDG_CONFIG_HOME/yaksha/config.json`, or `~/.config/yaksha/config.json` when `XDG_CONFIG_HOME` is not set, readable by the user only. `YAKSHA_URL` and `YAKSHA_API_TOKEN` override the file.
- The server's command is `yaksha-server`, so that `yaksha` names the client.

## Why

- Coding agents are the main users, and CI must work without a coding agent. A command serves both. A skill is plain Markdown that many coding agents load.
- A Go build is one file with no runtime to install: 10.7 MB for the CLI (7.2 MB stripped). In a test on 2 October 2026, Bun builds of a small CLI were 58 to 77 MB.
- The server's own JSON needs no output format of our own, and a coding agent reads JSON well. Regenerating the client brings in an API change's types and calls; a new field still needs its flag in the command.
- Waiting is the one thing that single requests do badly: a run takes minutes, and a stop must not leave paid calls on the line or lose a run's ID.
- The evaluator judges a call after it ends (0022). A wait that ended with the calls would report a result before the verdicts exist, and a coding agent could not tell a pass from a fail.

## Cost

- The commands cover the test loop: agents to read and `agent update --config-file` (the judges read the agent's configuration), scenarios and personas to read, runs with `run metrics`, conversations with `conversation evaluation`, auth, the version and the guide. Other API calls, such as labels and review, have no command yet.
- When the evaluator service does not run, verdicts stay pending. When the judge model fails, Yaksha tries again for 14 minutes or more before the evaluation fails. In both cases, a wait ends at its `--timeout` or after 10 minutes.
- A call that the judges did not score fails the command, also when the agent did nothing wrong, for example when Yaksha's caller broke the test. The agent runs the scenario again.
- The CI check catches an out-of-date spec or client, not a command that misses a new API field.
- The generated method names come from FastAPI's default operation IDs, so they are long. Users do not see them.

## Other options

- An MCP server. Not now: the CLI also works in CI with no coding agent, and coding agents run commands well. An MCP server can come later on the same API.
- A Python CLI in the server's package. Rejected: users would need Python and a package index; see 0018 for the install.
- TypeScript with Bun, or Rust. Both were compared with Go. Bun's builds are several times larger, and Go's release tool (GoReleaser) covers the platforms and signing that we need.
- Waiting for the calls only, and leaving the verdicts to `run metrics`. Rejected: the exit code would say pass before the judges decide.
