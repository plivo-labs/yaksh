import os
from importlib.metadata import version

# Before numpy is imported: after each matrix product, OpenBLAS's extra threads spin and cost
# more CPU than the work itself.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

__version__ = version("yaksh")
