# The caller's track in a recording starts late

Status: open.

## Problem

In a call recording, the caller's channel plays about 2 seconds after the caller spoke. The agent's channel is on time. So in a recording the agent seems to interrupt the caller when it did not, and a click on a caller turn in the transcript lands before the caller's voice.

## Evidence

Call `01a0f660-edb9-7c0c-bf99-ced9609e95c7`, a 94.3 s recording that starts at `connected`:

- Each caller reply has the same length in the recording as on the wire (`caller_audio_start` to `caller_audio_end`), but it starts later: 1.5 s later for the first reply, then 1.9 to 2.2 s later.
- The agent's first speech in the recording starts 50 ms after its turn start.
- Truman cleared the caller's queued audio at 74.7 s (recording time), where the wire events end that reply. The recording plays the same caller audio until 76.9 s.

## Cause

`Recorder` in `caller/phone.py` is Pipecat's `AudioBufferProcessor`, placed after the output transport. It takes the agent's audio as it arrives and the caller's audio as its frames pass the transport, and it lines the two up by padding silence by its own timing. That padding puts the caller's frames late. Not yet confirmed: which step of the padding adds the delay.

A second effect, confirmed in the installed Pipecat 1.11: `start_recording` sets the time of the last write of both tracks to None, so no silence goes before the first frame. The file starts at the first audio frame after `connected`, not at `connected`. Plivo sends audio from the start of the stream, so today the two are close, but nothing makes them equal.

## Fix

- Build the WAV from Truman's own clock: write each agent frame at the time it arrived and each caller frame at the time Truman sent it, both measured from `connected`, into one stereo buffer. The recording then matches the transcript and the wire events by construction.
- Test: a call whose two sides speak at known times gives a recording with each speech onset at its time, within one frame, also when the first audio comes seconds after `connected`.
