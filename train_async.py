import os
import runpy
import sys

ROOT = os.path.dirname(__file__)
SLIME_ROOT = os.path.join(ROOT, 'slime')
if SLIME_ROOT not in sys.path:
    sys.path.insert(0, SLIME_ROOT)

runpy.run_path(os.path.join(SLIME_ROOT, 'train_async.py'), run_name='__main__')
