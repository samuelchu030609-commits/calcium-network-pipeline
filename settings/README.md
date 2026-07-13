# Suite2p settings backup

Drop the canonical Suite2p settings file here as `pipeline_settings.npy`.

Users load it in the Suite2p GUI to get all the detection settings at once,
instead of entering them by hand (see [`../docs/SUITE2P_SETTINGS.md`](../docs/SUITE2P_SETTINGS.md)).

To create it: copy a clean `settings.npy` from a known-good plane0 run, e.g.

    cp "<a good recording>/suite2p/plane0/settings.npy" settings/pipeline_settings.npy

Note: `fs` and `tau` inside the file are per-recording — the guide tells users to
override those two for their own data. Everything else (Cellpose/meanImg/diameter)
is the shared, copy-exactly part.

This is the ONE .npy file that is committed to git (see the exception in
`.gitignore`).
