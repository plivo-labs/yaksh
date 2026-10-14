# 0029 Phone numbers are chosen in Yaksh

Date: 2026-10-14
Status: accepted. Changes 0027.

## Context

- `YAKSH_PLIVO_NUMBERS` listed the numbers of an install. Without it, the worker used every voice number of the Plivo account.
- `YAKSH_PLIVO_APP_ID` named the Plivo application for outbound tests. Only outbound tests used it.
- The worker read the numbers only when it started. After a change in the Plivo console, the user restarted the worker.
- Two installs on one Plivo account used the same numbers unless each one had a correct list. Nothing showed the collision.
- The default took every voice number, also the numbers of the agents under test. Yaksh then called an agent from the agent's own number, or from the number of a different agent.

## Decision

- A number is a test number when it is linked, in Plivo, to the receiving application. Plivo keeps this link, so every install on the account sees the same owner for each number.
- The receiving application is the setting `phone.application_id` on the **Phone** tab of Settings. `YAKSH_PLIVO_APP_ID` and `YAKSH_PLIVO_NUMBERS` are removed.
- Yaksh can make the receiving application: its name is `Yaksh`, its answer URL is `<YAKSH_PUBLIC_URL>/incoming` and its hangup URL is `<YAKSH_PUBLIC_URL>/incoming/hangup`, both `POST`. The user can also choose an application of the account, but not one of a Plivo CX agent. When the URLs of the application go to a different address, Yaksh shows the problem and can change them.
- The user chooses the test numbers on the **Numbers** page or with `yaksh numbers`. **Use for tests** links a free number to the receiving application. **Stop using** removes the link.
- Yaksh never takes a number that a different application receives. It never buys a number.
- **Stop using** is refused while a test holds the number, or while the number rests after a test. Thus no test loses a call that it waits for.
- A worker reads the numbers of the account again every `phone.check_interval_s` (default 300 s), and the API reads them at once on **Check now** and after each change. A database row holds the check: one process takes it for at most 60 s, so only one process checks at a time.
- When a check fails, or the account lists no numbers, Yaksh keeps the numbers of the last check and shows the error.
- Inbound tests and outbound tests use only test numbers.

## Why

- Plivo already holds one application for each number. With that link as the owner, all installs and the Plivo console agree, and no install needs to know about the others.
- A change in the Plivo console shows within one check interval, or at once with **Check now**. No restart is necessary.
- A new install takes no number until the user chooses it. The numbers of the agents under test stay out of the pool.

## Cost

- Each check sends one request to list the numbers, and one request for the name of each linked application.
- A change in the Plivo console shows only after the next check. A number that leaves the receiving application keeps its test until the test ends.
- Two installs that choose the same receiving application share its numbers. Yaksh shows that the URLs of the application go to a different address, but it does not stop the choice.
- A user who links a number to a different application in the Plivo console takes it from Yaksh at the next check.

## Other options

- Keep the list in the environment. Rejected: a change needs a restart, and other installs cannot see the list.
- A flag in the Yaksh database that marks a number as enabled. Rejected: other installs on the account cannot see it, so two installs can still use the same number.
- Let Yaksh link a number that a different application receives. Rejected: it would take the number of a Plivo CX agent or of another install, and break that agent or that install without a warning.
