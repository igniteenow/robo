"""The `robo` launcher that `scripts/install.sh` writes runs
``venv/bin/python <entrypoint>``, so the entrypoint must be a Python file.

It pointed at the checkout's ``robo`` file, which is a POSIX shell script: every
`robo` command from that installer died with a SyntaxError before doing anything.
"""

import py_compile
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO / "scripts" / "install.sh"


def test_the_installer_runs_a_python_entrypoint():
    match = re.search(r'ROBO_ENTRYPOINT="\$INSTALL_DIR/([^"]+)"', INSTALL_SH.read_text(encoding="utf-8"))
    assert match, "could not find ROBO_ENTRYPOINT in scripts/install.sh; update this test with it"

    entrypoint = REPO / match.group(1)

    assert entrypoint.is_file(), f"{entrypoint.name} does not exist in the checkout"
    py_compile.compile(str(entrypoint), doraise=True)  # raises if it is not Python
