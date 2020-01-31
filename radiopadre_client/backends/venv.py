import sys, os, os.path, subprocess
from radiopadre_client.utils import message, shell, bye, find_which, DEVNULL, DEVZERO, run_browser, ff

from radiopadre_client import config

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

def _install_radiopadre(init_venv=False):

    # check for existing venv
    if config.VENV_REINSTALL:
        init_venv = True
    else:
        if os.path.exists(ff("{config.RADIOPADRE_VENV}/bin/activate_this.py")):
            if os.path.exists(ff("{config.RADIOPADRE_VENV}/{config.COMPLETE_INSTALL_COOKIE}")):
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
    install_script = ff("{config.SERVER_INSTALL_PATH}/bin/install-radiopadre")

    if not os.path.exists(install_script):
        message(ff("{config.SERVER_INSTALL_PATH}/bin/install-radiopadre not found"))
        if not config.SERVER_INSTALL_REPO:
            bye("Try running with a --server-install-repo?")
        cmd = ff("git clone -b {config.SERVER_INSTALL_BRANCH} {config.SERVER_INSTALL_REPO} {config.SERVER_INSTALL_PATH}")
        message(ff("Running {cmd}"))
        if shell(cmd):
            bye("git clone failed")
    elif config.UPDATE:
        message(ff("--update specified, will attempt a git pull in {config.SERVER_INSTALL_REPO}"))
        if shell(ff("cd {config.SERVER_INSTALL_REPO} && git pull")):
            bye("git pull failed")

    cmd = "{}/bin/install-radiopadre --venv {} {} {} {}".format(config.SERVER_INSTALL_PATH, config.RADIOPADRE_VENV,
                "--no-casacore" if config.VENV_IGNORE_CASACORE else "",
                "--no-js9" if config.VENV_IGNORE_JS9 else "",
                "reinstall" if init_venv else "install",
                )
    message(ff("Running {cmd}"))
    if shell(cmd):
        bye("Installation script failed.")


def update_installation():
    # See https://stackoverflow.com/questions/1871549/determine-if-python-is-running-inside-virtualenv
    # are we already running inside a virtualenv?
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        if sys.prefix == config.RADIOPADRE_VENV:
            message("Already running inside radiopadre virtual environment")
        else:
            message(ff("Running inside non-default virtual environment {sys.prefix}"))
            message(ff("Will assume radiopadre has been installed here."))
            config.RADIOPADRE_VENV = sys.prefix

        if config.VENV_REINSTALL:
            bye("Can't --venv-reinstall from inside a virtualenv.")

        _install_radiopadre(init_venv=False)
    else:
        _install_radiopadre(init_venv=True)

        activation_script = os.path.expanduser(os.path.join(config.RADIOPADRE_VENV, "bin/activate_this.py"))
        message(ff("Activating the radiopadre virtualenv via {activation_script}"))
        with open(activation_script) as f:
            code = compile(f.read(), activation_script, 'exec')
            exec(code, dict(__file__=activation_script), {})

    if not config.INSIDE_CONTAINER_PORTS:
        message(ff("  Using radiopadre install at {config.SERVER_INSTALL_PATH}"))



def start_session(container_name, selected_ports, userside_ports, orig_rootdir, notebook_path,
                  browser_urls):
    from radiopadre_client.server import ROOTDIR, JUPYTER_OPTS

    # get hostname
    os.environ["HOSTNAME"] = subprocess.check_output("/bin/hostname").decode()

    # get jupyter path
    notebook_dir = subprocess.check_output(ff("{config.RADIOPADRE_VENV}/bin/pip show jupyter| ") +
                                           "grep Location:|cut -d ':' -f 2", shell=True).strip().decode()
    if not notebook_dir:
        raise subprocess.CalledProcessError(-1, "venv backend", "jupyter installation path not found")

    jupyter_port = selected_ports[0]
    userside_http_port = userside_ports[3]

    JUPYTER_OPTS += [ff("--port={jupyter_port}"), "--no-browser", "--browser=/dev/null"]     # --no-browser alone seems to be ignored

    if config.INSIDE_CONTAINER_PORTS:
        JUPYTER_OPTS += ["--allow-root", "--ip=0.0.0.0"]

    # if LOAD_NOTEBOOK:
    #     JUPYTER_OPTS.append(LOAD_NOTEBOOK if type(LOAD_NOTEBOOK) is str else LOAD_NOTEBOOK[0])

    # pass configured ports to radiopadre kernel
    os.environ['RADIOPADRE_SELECTED_PORTS'] = ":".join(map(str, selected_ports[1:]))
    os.environ['RADIOPADRE_USERSIDE_PORTS'] = ":".join(map(str, userside_ports[1:]))
    os.environ['RADIOPADRE_SHADOW_URLBASE'] = urlbase = ff("http://localhost:{userside_http_port}/{config.SESSION_ID}/")

    child_processes = []

    try:
        ## start jupyter process
        jupyter_path = config.RADIOPADRE_VENV + "/bin/jupyter"
        message("Starting: {} {} in {}".format(jupyter_path,  " ".join(JUPYTER_OPTS), ROOTDIR))

        notebook_proc = subprocess.Popen([jupyter_path] + JUPYTER_OPTS,
                                         stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                                         env=os.environ)

        ## use this instead to debug the sessison
        #notebook_proc = subprocess.Popen([config.RADIOPADRE_VENV+"/bin/ipython"],
        #                                 stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
        #                                  env=os.environ)

        child_processes.append(notebook_proc)

        # launch browser
        if browser_urls:
            child_processes += run_browser(*browser_urls)
        elif not config.REMOTE_MODE_PORTS and not config.INSIDE_CONTAINER_PORTS:
            message("Please point your browser to {}".format(" ".join(browser_urls)))

        notebook_proc.wait()
        message("Notebook process done")
        child_processes.pop(-1)

    finally:
        if child_processes:
            message("Terminating {} remaining child processes".format(len(child_processes)))
            for proc in child_processes:
                proc.terminate()
                proc.wait()

    message("Exiting")
