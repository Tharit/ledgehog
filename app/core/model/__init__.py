"""The model (pass 3) asked in the background (architecture §5.4): the in-memory list settling fills
(`queue`) and the one worker that works through it (`worker`). Importing the package imports neither, so
settling can reach the queue without reaching the worker, which settles."""
