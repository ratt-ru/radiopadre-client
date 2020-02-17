import sys, subprocess, os

from . import config
from .utils import find_which, chdir, message, warning, error


def start_helpers(shadow_rootdir):

    JS9_DIR = os.environ.get('RADIOPADRE_JS9_DIR') or f"{sys.prefix}/js9-www"

    if not os.path.exists(JS9_DIR):
        error(f"{JS9_DIR} does not exist")
    else:
        js9helper = f"{JS9_DIR}/js9Helper.js"

        nodejs = find_which("nodejs") or find_which("node")

        if not nodejs:
            error("Unable to find nodejs or node -- can't run js9helper.")
        with chdir(shadow_rootdir):
            subprocess.Popen([nodejs.strip(), js9helper,
                  f'{{"helperPort": {helper_port}, "debug": {config.VERBOSE}, ' +
                  f'"fileTranslate": ["^(http://localhost:[0-9]+/[0-9a-f]+{absrootdir}|/static/)", ""] }}'],
                    stdout=stdout, stderr=stderr)

def start_helpers():


