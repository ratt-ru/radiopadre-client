import os, sys, subprocess, atexit, traceback, psutil

import iglesia
from iglesia import PadreError
from .utils import find_which, chdir, find_unused_ports, ff, DEVZERO, DEVNULL, \
    message, warning, error, debug
from . import logger

_child_processes = []

def init_helpers(radiopadre_base, verbose=False, run_http=True, run_js9=True, run_carta=True):
    """Starts up helper processes, if they are not already running"""
    # set ports, else allocate ports
    selected_ports = os.environ.get('RADIOPADRE_SELECTED_PORTS')
    if selected_ports:
        selected_ports = list(map(int, selected_ports.strip().split(":")))
        debug(ff("  ports configured as {selected_ports}"))
    else:
        selected_ports = find_unused_ports(5)
        debug(ff("  ports selected: {selected_ports}"))

    userside_ports = os.environ.get('RADIOPADRE_USERSIDE_PORTS')
    if userside_ports:
        userside_ports = list(map(int, userside_ports.strip().split(":")))
        debug(ff("  userside ports configured as {userside_ports}"))
    else:
        userside_ports = selected_ports
        debug(ff("  userside ports are the same"))

    nbconvert = bool(os.environ.get('RADIOPADRE_NBCONVERT'))
    iglesia.set_userside_ports(selected_ports if nbconvert else userside_ports)

    jupyter_port, helper_port, http_port, carta_port, carta_ws_port = selected_ports

    # JS9 init
    iglesia.JS9_DIR = os.environ.setdefault('RADIOPADRE_JS9_DIR', ff("{sys.prefix}/js9-www"))

    # accumulates rewrite rules for HTTP server
    # add radiopadre/html/ to rewrite as /radiopadre-www/
    http_rewrites = [ff("/radiopadre-www/={radiopadre_base}/radiopadre/html/"),
                     ff("/js9-www/={iglesia.JS9_DIR}/")]

    # are we running inside a container?
    in_container = bool(os.environ.get('RADIOPADRE_CONTAINER_NAME'))

    if verbose:
        stdout, stderr = sys.stdout, sys.stderr
    else:
        stdout, stderr = DEVNULL, logger.logfile

    ## is this even needed?
    # import notebook
    # http_rewrites.append("/js9-www/={}/".format(JS9_DIR))
    # http_rewrites.append(
    #     "/js9colormaps.js={}/static/js9colormaps.js".format(os.path.dirname(notebook.__file__)))
    #
    global _child_processes

    # run JS9 helper
    if run_js9:
        if 'RADIOPADRE_JS9HELPER_PID' not in os.environ:
            try:
                js9helper = iglesia.JS9_DIR + "/js9Helper.js"

                if not os.path.exists(iglesia.JS9_DIR):
                    raise PadreError(ff("{iglesia.JS9_DIR} does not exist"))
                if not os.path.exists(js9helper):
                    raise PadreError(ff("{js9helper} does not exist"))

                js9prefs = iglesia.SESSION_DIR + "/js9prefs.js"
                if not in_container:
                    # create JS9 settings file (in container mode, this is created and mounted inside container already)
                    open(js9prefs, "w").write(ff("JS9Prefs.globalOpts.helperPort = {iglesia.JS9HELPER_PORT};\n"))
                    debug(ff("  writing {js9prefs} with helperPort={iglesia.JS9HELPER_PORT}"))

                message(ff("Starting {js9helper} on port {helper_port} in {iglesia.SHADOW_ROOTDIR}"))
                nodejs = find_which("nodejs") or find_which("node")
                if not nodejs:
                    raise PadreError("unable to find nodejs or node -- can't run js9helper.")
                try:
                    with chdir(iglesia.SHADOW_ROOTDIR):
                        _child_processes.append(
                            subprocess.Popen([nodejs.strip(), js9helper,
                                ff('{{"helperPort": {helper_port}, "debug": {iglesia.VERBOSE}, ') +
                                ff('"fileTranslate": ["^(http://localhost:[0-9]+/[0-9a-f]+{iglesia.ABSROOTDIR}|/static/)", ""] }}')],
                                             stdin=DEVZERO, stdout=stdout, stderr=stderr))
                        os.environ['RADIOPADRE_JS9HELPER_PID'] = str(_child_processes[-1].pid)
                        message("  started as PID {}".format(_child_processes[-1].pid))
                except Exception as exc:
                    error(ff("error running {nodejs} {js9helper}: {exc}"))
            except PadreError:
                pass
        else:
            debug("JS9 helper should be running (pid {})".format(os.environ["RADIOPADRE_JS9HELPER_PID"]))

    if run_http:
        if 'RADIOPADRE_HTTPSERVER_PID' not in os.environ:
            message(ff("Starting HTTP server process in {iglesia.SHADOW_HOME} on port {http_port}"))
            server = find_which("radiopadre-http-server.py")
            if server:
                with chdir(iglesia.SHADOW_HOME):
                    _child_processes.append(
                        subprocess.Popen([server, str(http_port)] + http_rewrites,
                                         stdin=DEVZERO,  stdout=stdout, stderr=stderr))
                    os.environ['RADIOPADRE_HTTPSERVER_PID'] = str(_child_processes[-1].pid)
                    message("  started as PID {}".format(_child_processes[-1].pid))
            else:
                error("HTTP server script radiopadre-http-server.py not found, functionality will be restricted")
        else:
            debug("HTTP server should be running (pid {})".format(os.environ["RADIOPADRE_HTTPSERVER_PID"]))

    if run_carta:
        if 'RADIOPADRE_CARTA_PID' not in os.environ:
            # start CARTA backend
            for carta_exec in os.environ.get('RADIOPADRE_CARTA_EXEC'), ff("{sys.prefix}/carta/carta"), \
                              find_which('carta'):
                # if carta_exec:
                #     subprocess.call(ff("ls -l /.radiopadre/venv"), shell=True)
                #     message("{}: {} {}".format(carta_exec, os.path.exists(carta_exec), os.access(carta_exec, os.X_OK)))
                if carta_exec and os.access(carta_exec, os.X_OK):
                    break
            else:
                carta_exec = None

            if not carta_exec or not os.path.exists(carta_exec):
                warning(ff("CARTA backend not found, omitting ({sys.prefix}/carta/carta)"))
            else:
                carta_dir = os.environ.get('RADIOPADRE_CARTA_DIR') or os.path.dirname(os.path.dirname(carta_exec))
                message(ff("Running CARTA backend {carta_exec} (in dir {carta_dir})"))
                with chdir(carta_dir):
                    _child_processes.append(
                        subprocess.Popen([carta_exec, "--remote",
                                            ff("--root={iglesia.ABSROOTDIR}"), ff("--folder={iglesia.ABSROOTDIR}"),
                                            ff("--port={carta_ws_port}"), ff("--fport={carta_port}")],
                                         stdin=subprocess.PIPE,  stdout=stdout, stderr=stderr))
                    os.environ['RADIOPADRE_CARTA_PID'] = str(_child_processes[-1].pid)
                    ## doesn't exit cleanly, let it be eaten rather
                    # atexit.register(_exit_carta, _child_processes[-1])
                    message("  started as PID {}".format(_child_processes[-1].pid))
        else:
            debug("CARTA backend should be running (pid {})".format(os.environ["RADIOPADRE_CARTA_PID"]))


def _exit_carta(proc):
    try:
        if proc.poll() is None:
            message("Asking CARTA backend (pid {}) to exit".format(proc.pid))
            try:
                proc.communicate("q\n")
            except TypeError: # because fuck you Python
                proc.communicate(b"q\n")
        else:
            message("CARTA backend already exited with code {}".format(proc.returncode))
    except Exception:
        err = traceback.format_exc()
        error(ff("Exception in _exit_carta: {err}"))


def register_helpers(*procs):
    """Registers another helper process started externally, mainly to make sure it is killed properly"""
    global _child_processes
    _child_processes += list(procs)

def kill_helpers():
    global _child_processes
    try:
        if _child_processes:
            message("Terminating remaining child processes ({})".format(
                    " ".join([str(proc.pid) for proc in _child_processes])))
            for proc in _child_processes:
                if proc.poll() is None:
                    proc.terminate()
                else:
                    message("  child {} already exited with code {}".format(proc.pid, proc.returncode))
            while _child_processes:
                proc = _child_processes.pop()
                proc.wait()
        else:
            debug("No child processes remaining")
    except Exception:
        err = traceback.format_exc()
        error(ff("Exception in kill_helpers: {err}"))

## This was not brutal enough
# atexit.register(kill_helpers)

def eat_children():
    # ask children to terminate
    procs = psutil.Process().children(recursive=True)
    if not procs:
        return

    message("Terminating {} remaining child processes".format(len(procs)))
    debug(" ".join(map(str, procs)))
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass

    def on_terminate(proc):
        debug("  Child process {} terminated with exit code {}".format(proc, proc.returncode))

    gone, alive = psutil.wait_procs(procs, timeout=1, callback=on_terminate)

    # if any are still alive, kill them
    if alive:
        message("Killing {} lingering child processes".format(len(alive)))
        debug(" ".join(map(str, alive)))
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass

atexit.register(eat_children)