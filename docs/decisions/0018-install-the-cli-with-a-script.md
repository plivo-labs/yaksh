# 0018 Install the CLI with a script and keep it at the server's version

Date: 2026-10-04
Status: accepted; not built yet

## Decision

- Users install the CLI with `curl -fsSL https://raw.githubusercontent.com/plivo-labs/yaksh/main/install.sh | bash`. The script is at the root of the repo on `main`; later it moves to our own domain. The CLI has no package on PyPI or npm.
- Each version tag builds the CLI for macOS and Linux with GoReleaser, and publishes the server's container image. Windows comes later.
- Versions stay on 0.x (commitizen `major_version_zero`).
- macOS builds get an ad-hoc signature. There is no notarization for now.
- During the beta, the CLI always changes itself to the newest release of the server's 0.x: it updates when the server's 0.x differs, checks once a day for a newer patch, and goes down to an older server's 0.x. There is no pinning. A CLI built from source never changes itself.
- Coding agents install the skill with `npx skills add plivo-labs/yaksh`. `yaksh guide` prints the skill that matches the binary.
- The README gives a prompt that a user pastes into a coding agent: install the CLI with the script, install the skill, and follow it.

## Why

- A script needs no package manager, and it works the same on a laptop and in CI.
- Yaksh is self-hosted, so each user runs a server at its own version. A CLI that follows the server's 0.x always speaks that server's API.
- `npx skills` installs one skill into many coding agents, so Yaksh needs no installer of its own for the skill.

## Cost

- A user must trust a script that runs in their shell.
- A user who wants to keep a CLI version cannot until pinning exists. We add pinning when the API is stable, or when a user reports a problem that it would solve.
- `npx skills` needs Node.

## Other options

- PyPI. Rejected: users would need Python.
- Pin the CLI to one version during the beta. Rejected for now: a CLI that does not match a self-hosted server is the bigger risk.
- Notarize macOS builds. Not now; GoReleaser can do it later.
