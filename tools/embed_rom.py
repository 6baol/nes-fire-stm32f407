"""Compatibility wrapper. Single-file embedding is now "embed_roms.py add"."""
import subprocess, sys
from pathlib import Path

if __name__ == '__main__':
    tool = Path(__file__).with_name('embed_roms.py')
    sys.exit(subprocess.call([sys.executable, str(tool), 'add'] + sys.argv[1:]))
