"""
Iglesia is radiopadre's runtime environment

This package provides variables and settings and utilities common to the client and server.
"""

import os, subprocess, uuid, sys

from .utils import find_which, chdir, make_dir, make_link, find_unused_ports, ff, DEVZERO, DEVNULL, \
    message, warning, error, debug
from . import logger

ABSROOTDIR = None       # absolute path to "root" directory, e.g. /home/user/path/to
ROOTDIR = None          # relative path to "root" directory (normally .)
DISPLAY_ROOTDIR = None  # what the root directory should be rewritten as, for display purposes
SHADOW_HOME = None      # base dir for the shadow directory tree

SERVER_BASEDIR = None   # dir where the Jupyter server is running, e.g. /home/user/path (or ~/.radiopadre/home/user/path)
SHADOW_ROOTDIR = None   # "root" directory in shadow tree, e.g. ~/.radiopadre/home/user/path/to
# The distinction above is important. The Jupyter session can be started in some *base* directory, while
# notebooks may be launched in a subdirectory of the latter. We need to know about this, because the
# subdirectory needs to be included in URLs given to Jupyter/JS9 helper/etc. to access the files within
# the subdirectory correctly.


LOCAL_SESSION_DIR = None    # local session dir -- usually {ABSROOTDIR}/.radiopadre-session
SHADOW_SESSION_DIR = None   # shadow session dir -- usually {SHADOW_ROOTDIR}/.radiopadre-session

SESSION_DIR = None          # session dir -- same as SHADOW_SESSION_DIR
SESSION_URL = None          # usually {SHADOW_URL_PREFIX}/{ABSROOTDIR}/.radiopadre-session
SESSION_ID = None           # session ID. Used below in paths
VERBOSE = 0                 # message verbosity level, >0 for debugging

JS9_DIR         = None             # JS9 install directory
HTTPSERVER_PORT = None             # (userside) HTTP port
JS9HELPER_PORT  = None             # (userside) helper port, if set up
CARTA_PORT = CARTA_WS_PORT = None  # (userside) carta ports, if set up

HOSTNAME = "localhost"

ALIEN_MODE = False         # true if browsing someone else's files

def _strip_slash(path):
    return path if path == "/" or path is None else path.rstrip("/")

def _is_subdir(subdir, parent):
    return subdir == parent or subdir.startswith(parent+"/")

class PadreError(RuntimeError):
    def __init__(self, message):
        super(PadreError, self).__init__(message)
        error(message)

from .helpers import init_helpers, register_helpers, kill_helpers

def init():
    """Initialize padre runtime environment, and setup globals describing it"""
    global ABSROOTDIR, ROOTDIR, DISPLAY_ROOTDIR, SHADOW_HOME, SERVER_BASEDIR, SHADOW_ROOTDIR, \
        LOCAL_SESSION_DIR, SHADOW_SESSION_DIR, SESSION_DIR, LOCAL_SESSION_URL, \
        FILE_URL_ROOT, NOTEBOOK_URL_ROOT, SESSION_ID, CACHE_URL_ROOT, \
        CACHE_URL_BASE, VERBOSE, SESSION_ID, HOSTNAME, \
        ALIEN_MODE, JS9_DIR

    def setdefault_path(envvar, default):
        if envvar in os.environ:
            return _strip_slash(os.environ[envvar])
        value = os.environ[envvar] = _strip_slash(default() if callable(default) else default)
        return value

    ABSROOTDIR = os.path.abspath(os.getcwd())
    ROOTDIR = setdefault_path('RADIOPADRE_ROOTDIR', '.')
    debug(ff("Setting up radiopadre environment:"))
    debug(ff("  ABSROOTDIR is {ABSROOTDIR}"))

    # setup shadow directory under ~/.radiopadre
    SHADOW_HOME = setdefault_path('RADIOPADRE_SHADOW_HOME', os.path.expanduser("~/.radiopadre"))
    make_dir(SHADOW_HOME)

    SHADOW_ROOTDIR = SHADOW_HOME + ABSROOTDIR
    if not os.path.exists(SHADOW_ROOTDIR):
        os.system("mkdir -p {}".format(SHADOW_ROOTDIR))
    DISPLAY_ROOTDIR = setdefault_path('RADIOPADRE_DISPLAY_ROOTDIR', '.')

    LOCAL_SESSION_DIR = ABSROOTDIR + "/.radiopadre-session"
    SESSION_DIR = SHADOW_SESSION_DIR = SHADOW_ROOTDIR + "/.radiopadre-session"

    # is base directory for the server already set up (e.g. by radiopadre-client)?
    # just read it off then
    if 'RADIOPADRE_SERVER_BASEDIR' in os.environ:
        SERVER_BASEDIR = _strip_slash(os.path.abspath(os.environ['RADIOPADRE_SERVER_BASEDIR']))
        ALIEN_MODE = _is_subdir(SERVER_BASEDIR, SHADOW_HOME)
        debug("  SERVER_BASEDIR configured in environment as {}, {} mode".format(SERVER_BASEDIR,
                                                                                 "alien" if ALIEN_MODE else "native"))
    else:
        ALIEN_MODE = not os.access(ABSROOTDIR, os.W_OK)
        # now figure out if we're browsing our own files, or someone else's
        # make .radiopadre and .radiopadre-session in target dir, or in shadow dir
        cachedir = ABSROOTDIR + "/.radiopadre"
        cachelink = SHADOW_ROOTDIR + "/.radiopadre"
        if not ALIEN_MODE:
            SERVER_BASEDIR = ABSROOTDIR
            debug(ff("  setting SERVER_BASEDIR to {SERVER_BASEDIR}: native mode"))
            make_dir(cachedir)
            make_link(cachedir, cachelink, rm_fr=True)
            make_dir(LOCAL_SESSION_DIR)
            make_link(LOCAL_SESSION_DIR, SHADOW_SESSION_DIR, rm_fr=True)
        else:
            SERVER_BASEDIR = SHADOW_ROOTDIR
            debug(ff("  setting SERVER_BASEDIR to {SERVER_BASEDIR}: alien mode"))
            if os.path.islink(cachelink):
                os.unlink(cachelink)
            make_dir(cachelink)
            if os.path.islink(SHADOW_SESSION_DIR):
                os.unlink(SHADOW_SESSION_DIR)
            make_dir(SHADOW_SESSION_DIR)
        os.environ['RADIOPADRE_SERVER_BASEDIR'] = SERVER_BASEDIR

    # just in case, make sure the session directory exists
    if not os.path.exists(SESSION_DIR):
        make_dir(SESSION_DIR)

    # get session ID, or setup a new one
    SESSION_ID = os.environ.get('RADIOPADRE_SESSION_ID')
    if not SESSION_ID:
        os.environ['RADIOPADRE_SESSION_ID'] = SESSION_ID = uuid.uuid4().hex

    # set verbosity
    VERBOSE = int(os.environ.get('RADIOPADRE_VERBOSE') or 0)

    # set hostname
    HOSTNAME = os.environ.get('HOSTNAME')
    if not HOSTNAME:
        os.environ["HOSTNAME"] = HOSTNAME = subprocess.check_output("/bin/hostname").decode().strip()


def set_userside_ports(userside_ports):
    """Sets the relevant userside port variables"""
    global JS9HELPER_PORT, HTTPSERVER_PORT, CARTA_PORT, CARTA_WS_PORT
    JS9HELPER_PORT, HTTPSERVER_PORT, CARTA_PORT, CARTA_WS_PORT = userside_ports
