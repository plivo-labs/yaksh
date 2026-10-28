# 0038 Phone calls in processes of their own

Date: 2026-10-28
Status: accepted

## Decision

With `YAKSH_CALL_PROCESSES=true`, the worker runs the audio pipeline of each phone call in a child process of its own. The default is off: then all calls run in the worker process, as before.

- The worker keeps the claim, the call's lease, the Plivo routes, the stream's WebSocket and the hang-up. The child holds the conversation: the Pipecat pipeline, the transcript, the recording and the live-listening connection to Postgres. Both modes run the same conversation code (`caller/conversation.py`) behind one interface: `Conversations.reserve()` gives a `Seat`, `Seat.start()` gives a `Conversation`.
- The worker relays the stream's ASGI messages to the child over a socket pair (`caller/link.py`: a length and a kind, then a pickled payload). The child builds a Starlette `WebSocket` from them. The child sends back the stream's outgoing messages, the observer's calls, `ENDED` when the conversation ends, and `HEARD` with the result. Then it leaves with `os._exit`.
- A pool (`caller/children.py`) keeps 2 ready processes. A call takes one when it is claimed, so the process is ready when the stream opens, and the pool starts a new one when the call starts. A process holds one call and leaves; the pool reaps it in the background. A call that never starts (the dial failed, Plivo refused the call) gives its process back to the pool, if the pool has fewer than 2 spare processes, so a run of failed dials does not start a process for each call.
- On Linux the processes come from a forkserver that preloads `yaksh.__main__`, the child module and `yaksh.caller.forkserver`. The last one sets `PR_SET_PDEATHSIG` and calls `gc.freeze()`. Each child also sets `PR_SET_PDEATHSIG` and raises its own `oom_score_adj`. One daemon thread starts every process and lives as long as the worker, because the forkserver dies with the thread that started it. On macOS each process starts a new interpreter (spawn): a forked process that uses macOS system frameworks crashes.
- A cancelled call has `CANCEL_KILL_S` (2 s) to send its result; then the worker kills the process. In this mode, a stuck pipeline does not make the worker exit.
- One ordered writer task per call sends the child's stream messages to Plivo. When a message is not sent within `STREAM_SEND_LIMIT_S` (2 s) of its arrival in the worker, the call fails and the worker kills the process.
- One ticker on each event loop measures how late the loop runs, for each call while it is live (`caller/lag.py`). In process mode, the worker's ticker measures the loop that relays the audio. A call's loop lag has the larger stall and the larger 99th percentile of the two loops.
- The worker's container runs an init process (`init: true`), which reaps a process that loses its parent.
- `OPENBLAS_NUM_THREADS=1` in each process: the smart-turn model used ten times more CPU with OpenBLAS's extra threads.

## Why

- One worker process runs all calls on one event loop and one interpreter lock, so it uses one CPU. On a 4 vCPU host it held about 14 calls; with more, every call's caller replied later, and a stall hit all calls at once.
- With processes, the calls use all CPUs of the host, and a slow or stuck call cannot delay the others.
- The worker still owns the stream, so the rule "one worker for each public address" stays, and Plivo's webhooks need no change.

## Cost

- Memory: each process holds its own models and pipeline. At rest the worker uses about 660 MB in this mode and 320 MB in one process. Each call adds about 100 MB, and 25 MB in one process. Without the forkserver preload and `gc.freeze()`, a ready process took about 200 MB.
- A burst of calls starts processes at the same time: about 2 to 3 s of all CPUs for 20 processes.
- Each call opens its own Postgres connection for live listening, as before, but from its process.
- The live listening of a call starts when its stream opens, in both modes. So that a listener who asked before then hears the opening, each call sends its first 5 s of audio to Postgres also when nobody listens.
- On macOS a process starts in about 2 s, not in milliseconds.
- `yaksh.__main__` and the child module load in the forkserver. When you change the preload list, make sure that each module imports in the forkserver. CPython ignores an `ImportError` there and logs nothing. The child logs a warning when it must import the child module itself.

## Other options

- Several workers behind one address, with each call forwarded to the worker that owns it. Rejected: Plivo's webhooks and the stream of a call must reach the worker that made the call, so this needs a router and shared state.
- A separate router process in front of several workers. Rejected for the same reason, with one more process to operate.
- Threads. Rejected: the interpreter lock keeps the pipelines on one CPU.
- uvloop in the worker. Not needed: relaying 20 calls costs the worker 0.1 CPU.
