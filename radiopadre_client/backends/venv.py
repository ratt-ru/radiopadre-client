import sys, os, os.path, subprocess, time
from iglesia.utils import message, warning, error, debug, shell, bye, ff, INPUT, check_output

from radiopadre_client import config
from radiopadre_client.server import run_browser
import iglesia
from .backend_utils import await_server_startup, update_server_from_repository

def init():
    pass

def save_session_info(container_name, selected_ports, userside_ports):
    pass

def list_sessions():
    raise NotImplementedError("not available in virtualenv mode")

def identify_session(session_dict, arg):
    raise NotImplementedError("not available in virtualenv mode")

def kill_sessions(session_dict, session_ids):
    raise NotImplementedError("not available in virtualenv mode")

def _install_radiopadre():
    """Installs radiopadre. If init_venv=True, allowed to initialize a venv if it doesn't exist"""
    # check for existing venv
    if config.VENV_REINSTALL:
        init_venv = True
    else:
        if os.path.exists(ff("{config.RADIOPADRE_VENV}/bin/activate_this.py")):
            if subprocess.check_output()
                os.path.exists(ff("{config.RADIOPADRE_VENV}/{config.COMPLETE_INSTALL_COOKIE}")):
                message(ff("Found complete radiopadre virtualenv in {config.RADIOPADRE_VENV}"))
                return
            else:
                message(ff("Radiopadre virtualenv in {config.RADIOPADRE_VENV} is incomplete"))
        else:
            message(ff("Radiopadre virtualenv {config.RADIOPADRE_VENV} doesn't exist"))
            init_venv = True
        if not config.AUTO_INIT:
            bye("Try running with --auto-init to (re)install it.")

    if init_venv:
        message("Will try to completely reinstall radiopadre virtualenv using install-radiopadre")
    else:
        message("Will try complete radiopadre virtualenv installation using install-radiopadre")

    # find install-radiopadre
    install_script = ff("{config.SERVER_INSTALL_PATH}/bin/bootstrap-radiopadre-install")

    if not os.path.exists(install_script):
        message(ff("{install_script} not found"))
        if not config.SERVER_INSTALL_REPO:
            bye("Try running with a --server-install-repo?")
        cmd = ff("git clone -b {config.SERVER_INSTALL_BRANCH} {config.SERVER_INSTALL_REPO} {config.SERVER_INSTALL_PATH}")
        message(ff("Running {cmd}"))
        if shell(cmd):
            bye("git clone failed")
    elif config.UPDATE:
        cmd = ff("cd {config.SERVER_INSTALL_PATH} && git fetch origin && git checkout {config.SERVER_INSTALL_BRANCH} && git pull")
        message(ff("--update specified: {cmd}"))
        if shell(ff("{cmd}")):
            bye("update failed")

    cmd = "{} --venv {} {} {} {}".format(install_script, config.RADIOPADRE_VENV,
                "--no-casacore" if config.VENV_IGNORE_CASACORE else "",
                "--no-js9" if config.VENV_IGNORE_JS9 else "",
                "reinstall" if init_venv else "install",
                )
    message(ff("Running {cmd}"))
    if shell(cmd):
        bye("Installation script failed.")

def update_installation():
    # are we already running inside a virtualenv? Proceed directly if so
    #       (see https://stackoverflow.com/questions/1871549/determine-if-python-is-running-inside-virtualenv)

    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        if sys.prefix == config.RADIOPADRE_VENV:
            message(ff("Running inside radiopadre virtual environment {sys.prefix}"))
        else:
            message(ff("Running inside non-default virtual environment {sys.prefix}"))
            message(ff("Will assume radiopadre has been installed here."))
            config.RADIOPADRE_VENV = sys.prefix

        if config.VENV_REINSTALL:
            bye("Can't --venv-reinstall from inside the virtualenv itself.")

    # Otherwise check for virtualenv, nuke/remake one if needed, then activate it
    else:
        config.RADIOPADRE_VENV = os.path.expanduser(config.RADIOPADRE_VENV)
        activation_script = os.path.join(config.RADIOPADRE_VENV, "bin/activate_this.py")

        # see if a reinstall is needed
        if config.AUTO_INIT and config.VENV_REINSTALL and os.path.exists(config.RADIOPADRE_VENV):
            if not os.path.exists(activation_script):
                error(ff("{activation_script} does not exist. Bat country!"))
                bye(ff("Refusing to touch this virtualenv. Please remove it by hand if you must."))
            cmd = ff("rm -fr {config.RADIOPADRE_VENV}")
            warning(ff("Found a virtualenv in {config.RADIOPADRE_VENV}."))
            warning("However, --auto-init and --venv-reinstall is specified. About to run:")
            warning("    " + cmd)
            warning(ff("Your informed consent for this is required!"))
            inp = INPUT(ff("Please enter 'yes' to rm -fr {config.RADIOPADRE_VENV}: ")).strip()
            if inp != "yes":
                bye(ff("'{inp}' is not a 'yes'. Phew!"))
            message("OK, nuking it!")
            shell(cmd)

        if not os.path.exists(config.RADIOPADRE_VENV):
            if config.AUTO_INIT:
                message(ff("Creating virtualenv {config.RADIOPADRE_VENV}"))
                shell(ff("virtualenv -p python3 {config.RADIOPADRE_VENV}"))
            else:
                error(ff("Radiopadre virtualenv {config.RADIOPADRE_VENV} doesn't exist."))
                bye(ff("Try re-running with --auto-init to reinstall it."))

        message(ff("  Activating the radiopadre virtualenv via {activation_script}"))
        with open(activation_script) as f:
            code = compile(f.read(), activation_script, 'exec')
            exec(code, dict(__file__=activation_script), {})

    # see if we have a server repo cloned that needs an update
    update_server_from_repository()

    # now check for a radiopadre install inside the venv
    have_install = check_output("pip show radiopadre") is not None

    if have_install:
        install_info = dict([x.split(": ", 1) for x in have_install.split("\n")])
        version = install_info.get("Version", "unknown")
        if config.UPDATE:
            message(ff("A radiopadre package is installed in this virtualenv"))
        else:
            message(ff("  however --update is in effect Radiopadre package is installed in this virtualenv"))

    if not config.INSIDE_CONTAINER_PORTS:
        message(ff("  Radiopadre has been installed from {config.SERVER_INSTALL_PATH}"))



def start_session(container_name, selected_ports, userside_ports, notebook_path, browser_urls):
    from iglesia import ROOTDIR
    from radiopadre_client.server import JUPYTER_OPTS

    # get hostname
    os.environ["HOSTNAME"] = subprocess.check_output("/bin/hostname").decode()

    # get jupyter path
    notebook_dir = subprocess.check_output(ff("{config.RADIOPADRE_VENV}/bin/pip show jupyter| ") +
                                           "grep Location:|cut -d ':' -f 2", shell=True).strip().decode()
    if not notebook_dir:
        raise subprocess.CalledProcessError(-1, "venv backend", "jupyter installation path not found")

    jupyter_port = selected_ports[0]
    userside_http_port = userside_ports[2]

    JUPYTER_OPTS += [ff("--port={jupyter_port}"), "--no-browser", "--browser=/dev/null"]     # --no-browser alone seems to be ignored

    if config.INSIDE_CONTAINER_PORTS:
        JUPYTER_OPTS += ["--allow-root", "--ip=0.0.0.0"]

    # if LOAD_NOTEBOOK:
    #     JUPYTER_OPTS.append(LOAD_NOTEBOOK if type(LOAD_NOTEBOOK) is str else LOAD_NOTEBOOK[0])

    # pass configured ports to radiopadre kernel
    os.environ['RADIOPADRE_SELECTED_PORTS'] = ":".join(map(str, selected_ports[1:]))
    os.environ['RADIOPADRE_USERSIDE_PORTS'] = ":".join(map(str, userside_ports[1:]))

    # get base path of radiopadre install
    radiopadre_base = subprocess.check_output(ff(""". {config.RADIOPADRE_VENV}/bin/activate && \
                        python -c "import importlib; print(importlib.find_loader('radiopadre').get_filename())" """),
                                              shell=True).decode().strip()

    radiopadre_base = os.path.dirname(os.path.dirname(radiopadre_base))
    message(ff("Detected radiopadre directory within virtualenv as {radiopadre_base}"))

    # default JS9 dir goes off the virtualenv
    os.environ.setdefault("RADIOPADRE_JS9_DIR", ff("{config.RADIOPADRE_VENV}/js9-www"))

    iglesia.init_helpers(radiopadre_base)

    if config.CARTA_BROWSER:
        url = ff("http://localhost:{iglesia.CARTA_PORT}/?socketUrl=ws://localhost:{iglesia.CARTA_WS_PORT}")
        message(ff("Browse to URL: {url} (CARTA file browser)"), color="GREEN")
        if browser_urls:
            browser_urls.append(url)

    ## start jupyter process
    jupyter_path = config.RADIOPADRE_VENV + "/bin/jupyter"
    message("Starting: {} {} in {}".format(jupyter_path, " ".join(JUPYTER_OPTS), ROOTDIR))

    notebook_proc = subprocess.Popen([jupyter_path] + JUPYTER_OPTS,
                                     stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                                     bufsize=1, universal_newlines=True, env=os.environ)

    ## use this instead to debug the sessison
    #notebook_proc = subprocess.Popen([config.RADIOPADRE_VENV+"/bin/ipython"],
    #                                 stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
    #                                  env=os.environ)

    iglesia.register_helpers(notebook_proc)

    # launch browser
    if browser_urls:
        iglesia.register_helpers(*run_browser(*browser_urls))
    elif not config.REMOTE_MODE_PORTS and not config.INSIDE_CONTAINER_PORTS:
        message("Please point your browser to {}".format(" ".join(browser_urls)))

    # pause to let the Jupyter server spin up
    wait = await_server_startup(jupyter_port, init_wait=0, process=notebook_proc)

    if wait is None:
        if notebook_proc.returncode is not None:
            bye(ff("jupyter unexpectedly exited with return code {notebook_proc.returncode}"))
        bye(ff("unable to connect to jupyter notebook server on port {jupyter_port}"))

    message(ff("The jupyter notebook server is running on port {jupyter_port} (after {wait:.2f} secs)"))

    try:
        while True:
            if config.INSIDE_CONTAINER_PORTS:
                debug("inside container -- sleeping indefinitely")
                time.sleep(100000)
            else:
                a = INPUT("Type 'exit' to kill the session: ")
                if notebook_proc.poll() is not None:
                    message("The notebook server has exited with code {}".format(notebook_proc.poll()))
                    sys.exit(0)
                if a.lower() == 'exit':
                    message("Exit request received")
                    sys.exit(0)
    except BaseException as exc:
        if type(exc) is KeyboardInterrupt:
            message("Caught Ctrl+C")
            status = 1
        elif type(exc) is EOFError:
            message("Input channel has closed")
            status = 1
        elif type(exc) is SystemExit:
            status = getattr(exc, 'code', 0)
            message("Exiting with status {}".format(status))
        else:
            message("Caught exception {} ({})".format(exc, type(exc)))
            status = 1
        sys.exit(status)

