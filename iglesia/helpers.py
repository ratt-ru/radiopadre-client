import os, sys, subprocess, atexit, traceback, getpass, tempfile, psutil, stat, uuid
from radiopadre_client.config import RADIOPADRE_VENV, NUM_PORTS

import iglesia
from iglesia import PadreError
from .utils import find_which, chdir, find_unused_ports, DEVZERO, DEVNULL, \
    message, warning, error, debug
from . import logger

_child_processes = []

_child_resources = []


def init_helpers(radiopadre_base, verbose=False, run_http=True, interactive=True, certificate=None):
    """Starts up helper processes, if they are not already running"""
    # set ports, else allocate ports
    selected_ports = os.environ.get('RADIOPADRE_SELECTED_PORTS')
    if selected_ports:
        selected_ports = list(map(int, selected_ports.strip().split(":")))
        debug(f"  ports configured as {selected_ports}")
    else:
        selected_ports = find_unused_ports(NUM_PORTS)
        debug(f"  ports selected: {selected_ports}")

    userside_ports = os.environ.get('RADIOPADRE_USERSIDE_PORTS')
    if userside_ports:
        userside_ports = list(map(int, userside_ports.strip().split(":")))
        debug(f"  userside ports configured as {userside_ports}")
    else:
        userside_ports = selected_ports
        debug(f"  userside ports are the same")

    nbconvert = bool(os.environ.get('RADIOPADRE_NBCONVERT'))
    iglesia.set_userside_ports(selected_ports if nbconvert else userside_ports)

    jupyter_port, helper_port, http_port, carta_port, carta_ws_port, wetty_port = selected_ports

    # JS9 init
    iglesia.JS9_DIR = os.environ.setdefault('RADIOPADRE_JS9_DIR', f"{sys.prefix}/js9-www")

    # accumulates rewrite rules for HTTP server
    # add radiopadre/html/ to rewrite as /radiopadre-www/
    http_rewrites = [f"/radiopadre-www/={radiopadre_base}/radiopadre/html/",
                     f"/js9-www/={iglesia.JS9_DIR}/"]

    # are we running inside a container?
    in_container = bool(os.environ.get('RADIOPADRE_CONTAINER_NAME'))
    in_docker = in_container and os.environ.get('RADIOPADRE_DOCKER') == 'True'

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

    # run wetty
    if interactive:
        if 'RADIOPADRE_WETTY_PID' not in os.environ:
            wetty = find_which("wetty")
            if not wetty:
                raise PadreError("unable to find wetty")
            session_id = os.environ.get('RADIOPADRE_SESSION_ID')
            wettycfg = tempfile.NamedTemporaryFile("wt")
            os.chmod(wettycfg.name, stat.S_IRUSR)
            wettycfg.write(f"""{{
                    'server': {{ 'base': '/{session_id}/wetty' }},
                }}
            """)
            wettycfg.flush()
            _child_resources.append(wettycfg)
            # message(f"Starting {wetty} on port {wetty_port} with config file {wettycfg.name} and base {session_id}")
            wetty_opts = [wetty,
                    "--conf", wettycfg.name, 
                    "--ssh-host", "localhost",
                    "--ssh-port", "22",
                    "--ssh-user", getpass.getuser(),
                    "--ssh-auth", "publickey,password",
                    "--port", str(wetty_port),
                    "--allow-iframe",
                ]
            if certificate:
                wetty_opts += ["--ssl-key", certificate, "--ssl-cert", certificate]
            message(f"Starting: {' '.join(wetty_opts)}")
            _child_processes.append(subprocess.Popen(wetty_opts))
            os.environ['RADIOPADRE_WETTY_PID'] = str(_child_processes[-1].pid)
            message("  started as PID {}".format(_child_processes[-1].pid))
        else:
            debug("wetty should be running (pid {})".format(os.environ["RADIOPADRE_WETTY_PID"]))

    # run JS9 helper
    if interactive:
        if 'RADIOPADRE_JS9HELPER_PID' not in os.environ:
            try:
                js9helper = iglesia.JS9_DIR + "/js9Helper.js"

                if not os.path.exists(iglesia.JS9_DIR):
                    raise PadreError(f"{iglesia.JS9_DIR} does not exist")
                if not os.path.exists(js9helper):
                    raise PadreError(f"{js9helper} does not exist")

                js9prefs = iglesia.SESSION_DIR + "/js9prefs.js"
                if not in_container:
                    # create JS9 settings file (in container mode, this is created and mounted inside container already)
                    open(js9prefs, "w").write(f"JS9Prefs.globalOpts.helperPort = {iglesia.JS9HELPER_PORT};\n")
                    debug(f"  writing {js9prefs} with helperPort={iglesia.JS9HELPER_PORT}")

                # message(f"Starting {js9helper} on port {helper_port} in {iglesia.SHADOW_ROOTDIR}")
                nodejs = find_which("nodejs") or find_which("node")
                if not nodejs:
                    raise PadreError("unable to find nodejs or node -- can't run js9helper.")
                try:
                    js9_opts = [nodejs.strip(), js9helper,
                                f'{{"helperPort": {helper_port}, "debug": {iglesia.VERBOSE}, ' +
                                f'"fileTranslate": ["^(http://localhost:[0-9]+/[0-9a-f]+{iglesia.ABSROOTDIR}|/static/)", ""] }}']
                    message(f"Starting in {iglesia.SHADOW_ROOTDIR}: {' '.join(js9_opts)}")
                    with chdir(iglesia.SHADOW_ROOTDIR):
                        _child_processes.append(subprocess.Popen(js9_opts, 
                                                stdin=DEVZERO, stdout=stdout, stderr=stderr))
                        os.environ['RADIOPADRE_JS9HELPER_PID'] = str(_child_processes[-1].pid)
                        message("  started as PID {}".format(_child_processes[-1].pid))
                except Exception as exc:
                    error(f"error running {nodejs} {js9helper}: {exc}")
            except PadreError:
                pass
        else:
            debug("JS9 helper should be running (pid {})".format(os.environ["RADIOPADRE_JS9HELPER_PID"]))

    if run_http:
        if 'RADIOPADRE_HTTPSERVER_PID' not in os.environ:
            message(f"Starting HTTP server process in {iglesia.SHADOW_HOME} on port {http_port}")
            server = find_which("radiopadre-http-server.py")
            if server:
                server_opts = [server, str(http_port)] + http_rewrites
                if certificate:
                    server_opts.append(certificate)
                if in_docker:
                    server_opts.append("0.0.0.0")
                message(f"Starting in {iglesia.SHADOW_HOME}: {' '.join(server_opts)}")
                with chdir(iglesia.SHADOW_HOME):
                    _child_processes.append(subprocess.Popen(server_opts, stdin=DEVZERO)) #,  stdout=stdout, stderr=stderr))
                    os.environ['RADIOPADRE_HTTPSERVER_PID'] = str(_child_processes[-1].pid)
                    message("  started as PID {}".format(_child_processes[-1].pid))
            else:
                error("HTTP server script radiopadre-http-server.py not found, functionality will be restricted")
        else:
            debug("HTTP server should be running (pid {})".format(os.environ["RADIOPADRE_HTTPSERVER_PID"]))

    if interactive:
        if 'RADIOPADRE_CARTA_PID' not in os.environ:
            # find CARTA backend or CARTA app
            for carta_exec in os.environ.get('RADIOPADRE_CARTA_EXEC'), f"{sys.prefix}/carta/carta", \
                              f"{sys.prefix}/carta-appimage", \
                              find_which('carta_backend'), find_which('carta'):
                # if carta_exec:
                #     subprocess.call(f"ls -l /.radiopadre/venv", shell=True)
                #     message("{}: {} {}".format(carta_exec, os.path.exists(carta_exec), os.access(carta_exec, os.X_OK)))
                if carta_exec and os.access(carta_exec, os.X_OK):
                    break
            else:
                carta_exec = None

            if not carta_exec or not os.path.exists(carta_exec):
                warning(f"CARTA backend not found, omitting")
            else:
                # check version, assume 1.x if not found
                carta_version = f"{sys.prefix}/carta_version"
                if os.path.exists(carta_version):
                    iglesia.CARTA_VERSION = open(carta_version, "rt").read()
                    message(f"Detected CARTA version {iglesia.CARTA_VERSION}")
                else:
                    iglesia.CARTA_VERSION = "2.x" if carta_exec.endswith("backend") else "1.x"
                    message(f"Assuming CARTA version {iglesia.CARTA_VERSION}, as none was detected")

                carta_dir = os.environ.get('RADIOPADRE_CARTA_DIR') or os.path.dirname(os.path.dirname(carta_exec))
                message(f"Running CARTA {iglesia.CARTA_VERSION} backend {carta_exec} (in dir {carta_dir})")
                carta_env = None

                if iglesia.CARTA_VERSION >= "2":
                    carta_dir = iglesia.ABSROOTDIR
                    cmdline = [carta_exec, f"--port={carta_port}", "--no_browser", # "--debug_no_auth",
                                f"--top_level_folder={iglesia.ABSROOTDIR}" ]
                    # explicit frontend for packaged versions
                    if not carta_exec.endswith("appimage"): 
                        cmdline.append(f"--frontend_folder=/usr/share/carta/frontend")
                    carta_stdout, carta_stderr = sys.stdout, sys.stderr
                    # use our session ID as the auth token for CARTA
                    carta_env = os.environ.copy()
                    carta_env['CARTA_AUTH_TOKEN'] = str(uuid.UUID(session_id))
                else:
                    cmdline = [carta_exec, "--remote",
                                f"--root={iglesia.ABSROOTDIR}", f"--folder={iglesia.ABSROOTDIR}",
                                f"--port={carta_ws_port}", f"--fport={carta_port}"]
                    carta_stdout, carta_stderr = stdout, stderr

                message(f"Starting: {' '.join(cmdline)}")
                with chdir(carta_dir):
                    _child_processes.append(subprocess.Popen(cmdline, stdin=subprocess.PIPE,  stdout=carta_stdout, stderr=carta_stderr, shell=False, env=carta_env))
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
        error(f"Exception in _exit_carta: {err}")


def register_helpers(*procs):
    """Registers another helper process started externally, mainly to make sure it is killed properly"""
    global _child_processes
    _child_processes += list(procs)

def kill_helpers():
    global _child_processes, _child_resources
    _child_resources = []
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
        error(f"Exception in kill_helpers: {err}")

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