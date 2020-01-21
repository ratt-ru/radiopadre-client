import sys, os, os.path, subprocess, time
from radiopadre_client.utils import message, shell, bye, find_which, DEVNULL, DEVZERO

from radiopadre_client import config


def init():
    pass

def read_session_info(container_name):
    raise NotImplementedError("not available in virtualenv mode")

def save_session_info(container_name, session_id, selected_ports, userside_ports):
    pass

def list_sessions():
    raise NotImplementedError("not available in virtualenv mode")

def identify_session(session_dict, arg):
    raise NotImplementedError("not available in virtualenv mode")

def kill_sessions(session_dict, session_ids):
    raise NotImplementedError("not available in virtualenv mode")


def update_installation():
    from radiopadre_client.server import PADRE_VENV, PADRE_WORKDIR, ABSROOTDIR, LOCAL_SESSION_DIR, SHADOWDIR
    from radiopadre_client.server import LOAD_NOTEBOOK, ROOTDIR

    activation_script = os.path.expanduser(os.path.join(config.SERVER_VENV, "bin/activate_this.py"))
    complete_cookie   = os.path.expanduser(os.path.join(config.SERVER_VENV, ".complete"))

    # See https://stackoverflow.com/questions/1871549/determine-if-python-is-running-inside-virtualenv
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        if sys.prefix == config.SERVER_VENV:
            message("Already running inside radiopadre virtual environment")
        else:
            bye("Can't run this script inside a non-radiopadre virtualenv. Please deactivate and rerun.")
    else:
        if os.path.exists(activation_script) and os.path.exists(complete_cookie) and not config.VENV_REINSTALL:
            message(f"Found radiopadre virtualenv in {config.SERVER_VENV}")
        elif config.AUTO_INIT or config.VENV_REINSTALL:
            if config.VENV_REINSTALL:
                message("Will reinstall radiopadre virtualenv using install-radiopadre")
            else:
                message("Can't find complete radiopadre virtualenv, bootstrapping with install-radiopadre")
            if shell("{}/bin/install-radiopadre {} {} reinstall".format(config.SERVER_INSTALL_PATH,
                                                                        "--no-casacore" if config.VENV_NO_CASACORE else "",
                                                                        "--no-js9" if config.VENV_NO_JS9 else "",
                                                                        )):
                bye("Installation script failed")

        message(f"Activating the radiopadre virtualenv via {activation_script}")
        with open(activation_script) as f:
            code = compile(f.read(), activation_script, 'exec')
            exec(code, dict(__file__=activation_script), {})

    if not config.INSIDE_CONTAINER_PORTS:
        message(f"  Using radiopadre install at {config.SERVER_INSTALL_PATH}")



def start_session(container_name, session_id, selected_ports, userside_ports, orig_rootdir, notebook_path,
                  browser_urls):

    from radiopadre_client.server import PADRE_VENV, PADRE_WORKDIR, ABSROOTDIR, LOCAL_SESSION_DIR, SHADOWDIR
    from radiopadre_client.server import LOAD_NOTEBOOK, ROOTDIR

    # get hostname
    os.environ["HOSTNAME"] = subprocess.check_output("/bin/hostname").decode()

    # get jupyter path
    notebook_dir = subprocess.check_output(f"{PADRE_VENV}/bin/pip show jupyter| "
                                           "grep Location:|cut -d ':' -f 2", shell=True).strip().decode()
    if not notebook_dir:
        raise subprocess.CalledProcessError(-1, "venv backend", "jupyter installation path not found")


    # check status of JS9. Ends up being True, or a RuntimeError

    js9dir = js9error = None
    js9status_file = PADRE_VENV + "/js9status"
    if not os.path.exists(js9status_file):
        js9error = "not found"
    else:
        js9dir = open(js9status_file).read().strip()
        if not js9dir.startswith("/"):
            js9error = js9dir
            js9dir = None

    os.environ['RADIOPADRE_JS9_DIR'] = js9dir or ''
    os.environ['RADIOPADRE_JS9_ERROR'] = js9error or ''
    if js9dir:
        message(f"  Found JS9 install in {js9dir}")
    else:
        message(f"  Warning: JS9 not functional ({js9error}). Reinstall radiopadre?")


    # # make link to JS9 install
    # if js9dir:
    #     if not os.path.exists(PADRE_WORKDIR + "/js9-www"):
    #         os.symlink(js9dir, PADRE_WORKDIR + "/js9-www")
    #     if not os.path.exists(PADRE_WORKDIR + "/js9colormaps.js"):
    #         message("making {} symlink".format(PADRE_WORKDIR + "/js9colormaps.js"))
    #         os.symlink(notebook_dir + "/notebook/static/js9colormaps.js", PADRE_WORKDIR + "/js9colormaps.js")
    #     if not os.path.exists(PADRE_WORKDIR + "/radiopadre-www"):
    #         os.symlink(PADRE_PATH + "/html", PADRE_WORKDIR + "/radiopadre-www")

    # add padre directory to PYTHONPATH
    if "PYTHONPATH" in os.environ:
        os.environ["PYTHONPATH"] = os.environ["PYTHONPATH"] + ":" + config.SERVER_INSTALL_PATH
    else:
        os.environ["PYTHONPATH"] = config.SERVER_INSTALL_PATH

    from radiopadre_client.server import JUPYTER_OPTS

    JUPYTER_OPTS.append("--port={}".format(selected_ports[0]))
    JUPYTER_OPTS += ["--no-browser", "--browser=/dev/null"] # --no-browser alone seems to be ignored

    if config.INSIDE_CONTAINER_PORTS:
        JUPYTER_OPTS += ["--allow-root", "--ip=0.0.0.0"] # --no-browser alone seems to be ignored

    if LOAD_NOTEBOOK:
        JUPYTER_OPTS.append(LOAD_NOTEBOOK)

    userside_jupyter_port, userside_helper_port, userside_http_port, userside_carta_port, userside_carta_ws_port = userside_ports
    jupyter_port, helper_port, http_port, carta_port, carta_ws_port  = selected_ports

    child_processes = []

    #os.environ['RADIOPADRE_SHADOW_URLBASE'] = urlbase = "http://localhost:{}/".format(forwarded_http_port)
    os.environ['RADIOPADRE_SHADOW_URLBASE'] = urlbase = "http://localhost:{}/{}/".format(userside_http_port, session_id)
    js9prefs = None
    print(userside_ports, selected_ports)
    print(os.environ)

    http_rewrites = [ "/radiopadre-www/={}/".format(config.SERVER_INSTALL_PATH + "/html") ]

    if js9dir:
        os.environ['RADIOPADRE_JS9_HELPER_PORT'] = str(userside_helper_port)
        js9prefs = LOCAL_SESSION_DIR + "/js9prefs.js"
        if not config.INSIDE_CONTAINER_PORTS:
            # create JS9 settings file (in container mode, this is created above, and mounted inside container already)
            open(js9prefs, "w").write("JS9Prefs.globalOpts.helperPort = {};\n".format(userside_helper_port))
        # URL to local settings file for this session
        os.environ['RADIOPADRE_JS9_DIR'] = "{}js9-www/".format(urlbase)
        os.environ['RADIOPADRE_JS9_SETTINGS'] = "{}{}".format(urlbase, js9prefs)

        http_rewrites.append("/js9-www/={}/".format(js9dir))
        http_rewrites.append("/js9colormaps.js={}".format(notebook_dir + "/notebook/static/js9colormaps.js"))

    try:
        helper_proc = None
        if js9dir:
            os.environ['JS9_LOCAL_URL_PREFIX'] = urlbase
            os.environ['JS9_LOCAL_FS_PREFIX'] = PADRE_WORKDIR + "/"
            js9helper = js9dir +"/js9Helper.js"
            if os.path.exists(js9helper):
                message(f"Starting {js9helper} on port {helper_port} in {SHADOWDIR}")
                nodejs = find_which("nodejs") or find_which("node")
                if not nodejs:
                    bye("Unable to find nodejs or node -- can't run js9helper. You need to apt-get install nodejs perhaps?")
                try:
                    os.chdir(SHADOWDIR)
                    child_processes.append(subprocess.Popen([nodejs.strip(), js9helper,
                        ('{{"helperPort": {}, "debug": {}, ' +
                         '"fileTranslate": ["^(http://localhost:[0-9]+/[0-9a-f]+{}|/static/)", ""] }}').format(
                                helper_port, 1 if config.VERBOSE else 0,
                                ABSROOTDIR)],
                            stdin=DEVZERO, stdout=sys.stdout, stderr=sys.stderr))
                finally:
                    os.chdir(ROOTDIR)
            else:
                message(f"Can't find JS9 helper at {js9helper}")
        else:
            message("JS9 not configured")

        message(f"Starting HTTP server process in {PADRE_WORKDIR} on port {http_port}")
        args = [f"{PADRE_VENV}/bin/python", f"{config.CLIENT_INSTALL_PATH}/bin/radiopadre-http-server.py",
                str(http_port) ] + http_rewrites

        try:
            os.chdir(PADRE_WORKDIR)
            child_processes.append(subprocess.Popen(args, stdin=DEVZERO,
                                                    stdout=sys.stdout if config.VERBOSE else DEVNULL,
                                                    stderr=sys.stderr if config.VERBOSE else DEVNULL))
        finally:
            os.chdir(ROOTDIR)

        ## start CARTA backend
        carta_dir = carta_exec = None

        if config.INSIDE_CONTAINER_PORTS:
            carta_dir, carta_exec = "/", "/carta/carta"
            if not os.access(carta_exec, os.X_OK):
                 carta_exec = None
        else:
            carta_exec = os.path.realpath(find_which("carta"))
            carta_dir = os.path.dirname(carta_exec)

        if not carta_exec:
            message("CARTA backend not found, omitting", file=sys.stderr)
        else:
            message(f"Found CARTA in {carta_exec} (dir {carta_dir})")
            if carta_dir:
                os.chdir(carta_dir)
            try:
                # if options.inside_container:
                #     xvfb  = find_which("which Xvfb")
                #     args = [xvfb, "-displayfd", "1", "-auth", "/dev/null" ]
                #     child_processes.append(subprocess.Popen(xvfb, stdin=DEVZERO,
                #                   stdout=sys.stdout if options.verbose else DEVNULL,
                #                   stderr=sys.stderr if options.verbose else DEVNULL, shell=True))
                #     os.environ['DISPLAY'] = ':0'

                args = [carta_exec, "--remote", "--root={}".format(ROOTDIR), "--folder={}".format(ROOTDIR),
                        "--port={}".format(carta_ws_port), "--fport={}".format(carta_port)]
                message("Starting CARTA backend {} (in {})".format(" ".join(args), os.getcwd()), file=sys.stderr)
                os.environ['RADIOPADRE_CARTA_PORT'] = str(userside_carta_port)
                os.environ['RADIOPADRE_CARTA_WS_PORT'] = str(userside_carta_ws_port)

                child_processes.append(subprocess.Popen(args, stdin=subprocess.PIPE,
                                                        stdout=sys.stderr if config.VERBOSE else DEVNULL,
                                                        stderr=sys.stderr if config.VERBOSE else DEVNULL))
            finally:
                os.chdir(ROOTDIR)

        ## start jupyter process

        jupyter_path = PADRE_VENV + "/bin/jupyter"
        message("Starting: " + jupyter_path + " " + " ".join(JUPYTER_OPTS))

        notebook_proc = subprocess.Popen([jupyter_path] + JUPYTER_OPTS,
                                          stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                                          env=os.environ)

        ## use this instead to debug the sessison
        #notebook_proc = subprocess.Popen([PADRE_VENV+"/bin/ipython"],
        #                                 stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
        #                                  env=os.environ)

        child_processes.append(notebook_proc)

        # launch browser
        url = "http://localhost:{}?token={}".format(userside_jupyter_port, session_id)
        if browser_urls:
            message("running {} {}\r".format(config.BROWSER, url))
            message("  if this fails, specify a correct browser invocation command with --browser-command and rerun,")
            message("  or else browse to the URL given above (\"Browse to URL:\") yourself.")
            try:
                time.sleep(2)
                subprocess.call([config.BROWSER, url], stdout=DEVNULL)
            except OSError as exc:
                if exc.errno == 2:
                    message(f"{config.BROWSER} not found")
                else:
                    raise
        elif not config.REMOTE_MODE_PORTS and not config.INSIDE_CONTAINER_PORTS:
            message("Please point your browser to {}".format(url))

        notebook_proc.wait()
        message("Notebook process done")
        child_processes.pop(-1)

    finally:
        message("Terminating child processes")
        for proc in child_processes:
            proc.terminate()
            proc.wait()

    message("Exiting")
