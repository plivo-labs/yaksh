# 0028 Call audio in file storage

Date: 2026-10-09
Status: accepted

## Decision

- The worker builds the audio files of a call in memory: the stereo recording and the caller's voice. It writes no local files.
- After the call ends, and before it saves the result, the worker uploads both files side by side to the file storage under `recordings/<conversation id>/`. The lease stays held during the upload. The upload gets one attempt and at most 10 s.
- The conversation row keeps the keys of the files, not paths. The API and the evaluator read the files from the storage by these keys.
- If the upload of a file fails, the worker logs the error and saves the call without that file. If the upload runs out of time, the call is saved without both. The evaluation reports a missing recording, as for any call without one.
- File storage is required. Yaksha does not start without `YAKSHA_S3_ENDPOINT`, `YAKSHA_S3_ACCESS_KEY` and `YAKSHA_S3_SECRET_KEY`.

## Why

- With local files, the API, the worker and the evaluator had to share one disk. Then they could not run on separate hosts, and only one worker could run.
- The calls already keep all of their audio in memory, so no local file is necessary.
- A call result is worth more than its audio. A failed upload must not lose the result.
- Without storage, calls would have no playback and no metrics, and nothing would say why. A start that fails is clearer.

## Cost

- Each worker stop can take 15 s more: 10 s for the upload and 5 s to cancel it. The grace period of the worker container covers it.
- An upload that succeeds for a call whose result is not saved leaves files that nothing uses.
- The API holds a whole recording in memory while it sends it: about 1.9 MB for each minute of the call.

## Other options

- A shared volume. Rejected: it ties the services to one host.
- Presigned URLs for playback. Rejected: the console already loads the whole file with the API token, and the bucket can stay private.
- Local files with an upload later. Rejected: the files would still have to outlive the worker.
