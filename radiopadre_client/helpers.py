import subprocess

from . import config
from .utils import find_which, chdir


def start_helpers():



    nodejs = find_which("nodejs") or find_which("node")

    if not nodejs:
        raise RuntimeError("Unable to find nodejs or node -- can't run js9helper.")
    with chdir(directory):
        subprocess.Popen([nodejs.strip(), js9helper,
              f'{{"helperPort": {helper_port}, "debug": {config.VERBOSE}, ' +
              f'"fileTranslate": ["^(http://localhost:[0-9]+/[0-9a-f]+{absrootdir}|/static/)", ""] }}'],
                stdout=stdout, stderr=stderr)

def start_helpers():


