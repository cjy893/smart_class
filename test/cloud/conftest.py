import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLOUD_SRC = ROOT / "cloud" / "src"

if str(CLOUD_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUD_SRC))
