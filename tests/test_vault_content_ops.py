from pathlib import Path
import sys

# Insert scripts/ into sys.path only when the module file exists. This ensures
# initial test run fails with ModuleNotFoundError (when the script doesn't
# exist) and later fails with NotImplementedError if the script is created
# as a placeholder that raises on import.
ROOT = Path(__file__).resolve().parents[1]
module_file = ROOT / "scripts" / "vault_content_ops.py"
if module_file.exists():
    sys.path.insert(0, str(ROOT / "scripts"))

# Import at module-import time so pytest collection fails in the two-step way
# described in the task.
import vault_content_ops
