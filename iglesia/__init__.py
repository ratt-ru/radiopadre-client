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

SELECTED_PORTS = None       # js9helper, http_server, carta, carta_ws
USERSIDE_PORTS = None       # same on user side (after port forwarding)

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

def init():
    """Initialize padre runtime environment, and setup globals describing it"""
    global ABSROOTDIR, ROOTDIR, DISPLAY_ROOTDIR, SHADOW_HOME, SERVER_BASEDIR, SHADOW_ROOTDIR, \
        LOCAL_SESSION_DIR, SHADOW_SESSION_DIR, SESSION_DIR, LOCAL_SESSION_URL, \
        FILE_URL_ROOT, NOTEBOOK_URL_ROOT, SESSION_ID, CACHE_URL_ROOT, \
        CACHE_URL_BASE, VERBOSE, SESSION_ID, HOSTNAME, \
        SELECTED_PORTS, USERSIDE_PORTS, ALIEN_MODE, JS9_DIR, \
        JS9HELPER_PORT, HTTPSERVER_PORT, CARTA_PORT, CARTA_WS_PORT

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

    # set ports, else allocate ports
    selected_ports = os.environ.get('RADIOPADRE_SELECTED_PORTS')
    if selected_ports:
        SELECTED_PORTS = map(int, selected_ports.strip().split(":"))
    else:
        SELECTED_PORTS = find_unused_ports(4)

    userside_ports = os.environ.get('RADIOPADRE_USERSIDE_PORTS')
    if userside_ports:
        USERSIDE_PORTS = map(int, userside_ports.strip().split(":"))
    else:
        USERSIDE_PORTS = SELECTED_PORTS
    JS9HELPER_PORT, HTTPSERVER_PORT, CARTA_PORT, CARTA_WS_PORT = USERSIDE_PORTS

    # set hostname
    HOSTNAME = os.environ.get('HOSTNAME')
    if not HOSTNAME:
        os.environ["HOSTNAME"] = HOSTNAME = subprocess.check_output("/bin/hostname").decode().strip()

def init_helpers(radiopadre_base):
    """Starts up helper processes, if they are not already running"""
    helper_port, http_port, carta_port, carta_ws_port = SELECTED_PORTS

    # JS9 init
    global JS9_DIR
    JS9_DIR = os.environ.setdefault('RADIOPADRE_JS9_DIR', ff("{sys.prefix}/js9-www"))

    # accumulates rewrite rules for HTTP server
    # add radiopadre/html/ to rewrite as /radiopadre-www/
    http_rewrites = [ff("/radiopadre-www/={radiopadre_base}/html/"),
                     ff("/js9-www/={JS9_DIR}/")]

    # are we running inside a container?
    in_container = bool(os.environ.get('RADIOPADRE_CONTAINER_NAME'))

    ## is this even needed?
    # import notebook
    # http_rewrites.append("/js9-www/={}/".format(JS9_DIR))
    # http_rewrites.append(
    #     "/js9colormaps.js={}/static/js9colormaps.js".format(os.path.dirname(notebook.__file__)))
    #
    child_processes = []

    # run JS9 helper
    if 'RADIOPADRE_JS9HELPER_PID' not in os.environ:
        try:
            js9helper = JS9_DIR + "/js9Helper.js"

            if not os.path.exists(JS9_DIR):
                raise PadreError(ff("{JS9_DIR} does not exist"))
            if not os.path.exists(js9helper):
                raise PadreError(ff("{js9helper} does not exist"))

            message(ff("Starting {js9helper} on port {helper_port} in {SHADOW_ROOTDIR}"))

            js9prefs = SESSION_DIR + "/js9prefs.js"
            if not in_container:
                # create JS9 settings file (in container mode, this is created and mounted inside container already)
                open(js9prefs, "w").write(ff("JS9Prefs.globalOpts.helperPort = {JS9HELPER_PORT};\n"))
                debug(ff("  writing {js9prefs} with helperPort={JS9HELPER_PORT}"))

            message(ff("Starting {js9helper} on port {helper_port} in {SHADOW_ROOTDIR}"))
            nodejs = find_which("nodejs") or find_which("node")
            if not nodejs:
                raise PadreError("unable to find nodejs or node -- can't run js9helper.")
            try:
                with chdir(SHADOW_ROOTDIR):
                    child_processes.append(
                        subprocess.Popen([nodejs.strip(), js9helper,
                            ff('{{"helperPort": {helper_port}, "debug": {VERBOSE}, ') +
                            ff('"fileTranslate": ["^(http://localhost:[0-9]+/[0-9a-f]+{ABSROOTDIR}|/static/)", ""] }}')],
                                         stdin=DEVZERO, stdout=DEVNULL, stderr=logger.logfile))
                    os.environ['RADIOPADRE_JS9HELPER_PID'] = str(child_processes[-1].pid)
            except Exception as exc:
                error(ff("error running {nodejs} {js9helper}: {exc}"))
        except PadreError:
            pass
    else:
        debug("JS9 helper should be running (pid {})".format(os.environ["RADIOPADRE_JS9HELPER_PID"]))

    if 'RADIOPADRE_HTTPSERVER_PID' not in os.environ:
        message(ff("Starting HTTP server process in {SHADOW_HOME} on port {http_port}"))
        server = find_which("radiopadre-http-server.py")
        if server:
            with chdir(SHADOW_HOME):
                child_processes.append(
                    subprocess.Popen([server, str(http_port)] + http_rewrites,
                                     stdin=DEVZERO, stdout=DEVNULL, stderr=logger.logfile))
                os.environ['RADIOPADRE_HTTPSERVER_PID'] = str(child_processes[-1].pid)
        else:
            error("HTTP server script radiopadre-http-server.py not found, functionality will be restricted")
    else:
        debug("HTTP server should be running (pid {})".format(os.environ["RADIOPADRE_HTTPSERVER_PID"]))

    if 'RADIOPADRE_CARTA_PID' not in os.environ:
        # start CARTA backend
        for carta_exec in os.environ.get('RADIOPADRE_CARTA_EXEC'), ff("{radiopadre_base}/carta/carta"), \
                          find_which('carta'):
            if carta_exec and os.access(carta_exec, os.X_OK):
                break
        else:
            carta_exec = None

        if not carta_exec or not os.path.exists(carta_exec):
            warning("CARTA backend not found, omitting")
        else:
            carta_dir = os.environ.get('RADIOPADRE_CARTA_DIR') or os.path.dirname(os.path.dirname(carta_exec))
            message(ff("Running CARTA backend {carta_exec} (in dir {carta_dir})"))
            with chdir(carta_dir):
                child_processes.append(
                    subprocess.Popen([carta_exec, "--remote",
                                        ff("--root={ABSROOTDIR}"), ff("--folder={ABSROOTDIR}"),
                                        ff("--port={carta_ws_port}"), ff("--fport={carta_port}")],
                                     stdin=subprocess.PIPE, stdout=DEVNULL, stderr=logger.logfile))
                os.environ['RADIOPADRE_CARTA_PID'] = str(child_processes[-1].pid)
    else:
        debug("CARTA backend should be running (pid {})".format(os.environ["RADIOPADRE_CARTA_PID"]))

    return child_processes