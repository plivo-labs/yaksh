"""Imported only by the forkserver, as the last module of its preload (see `children.PRELOAD`):
the forkserver dies with the worker, and what the preload imported is frozen, so that the call
processes it forks keep sharing those pages after their own collections. Imported anywhere
else, it would do the same to that process."""

import gc

from yaksh.caller.child import die_with_parent

die_with_parent()
gc.collect()
gc.freeze()
