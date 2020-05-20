from __future__ import print_function
import os, os.path, sys, subprocess, time, glob, uuid, shutil, fnmatch

from . import config
import iglesia
from iglesia.utils import DEVNULL, DEVZERO, message, warning, bye, find_unused_port, find_which, ff
from .notebooks import default_notebook_code

backend = None

JUPYTER_OPTS = LOAD_DIR = LOAD_NOTEBOOK = None

def run_browser(*urls):
    """
    Runs a browser pointed to URL(s), in background if config.BROWSER_BG is True.

    If config.BROWSER_MULTI is set, runs a browser per URL, else feeds all URLs to one browser invocation

    Returns list of processes (in BROWSER_BG mode).
    """
    from . import config
    procs = []
    # open browser if needed
    if config.BROWSER:
        message("Running {} {}\r".format(config.BROWSER, " ".join(urls)))
        message("  if this fails, specify a correct browser invocation command with --browser and rerun,")
        message("  or else browse to the URL given above (\"Browse to URL:\") yourself.")
        # sometimes the notebook does not respond immediately, so take a second
        time.sleep(1)
        if config.BROWSER_MULTI:
            commands = [[config.BROWSER]+list(urls)]
        else:
            commands = [[config.BROWSER, url] for url in urls]

        for command in commands:
            try:
                if config.BROWSER_BG:
                    procs.append(subprocess.Popen(command, stdin=DEVZERO, stdout=sys.stdout, stderr=sys.stderr))
                else:
                    subprocess.call(command, stdout=DEVNULL)
            except OSError as exc:
                if exc.errno == 2:
                    message(ff("{config.BROWSER} not found"))
                else:
                    raise

    else:
        message("--no-browser given, or browser not set, not opening a browser for you\r")
        message("Please browse to: {}\n".format(" ".join(urls)))

    return procs


def run_radiopadre_server(command, arguments, notebook_path, workdir=None):
    global backend

    # message("Welcome to Radiopadre!")
    USE_VENV = USE_DOCKER = USE_SINGULARITY = False

    for backend in config.BACKEND:
        if backend == "venv" and find_which("virtualenv"):
            USE_VENV = True
            import radiopadre_client.backends.venv
            backend = radiopadre_client.backends.venv
            backend.init()
            break
        elif backend == "docker":
            has_docker = find_which("docker")
            if has_docker:
                USE_DOCKER = True
                message(ff("Using {has_docker} for container mode"))
                import radiopadre_client.backends.docker
                backend = radiopadre_client.backends.docker
                backend.init(binary=has_docker)
                break
        elif backend == "singularity":
            has_docker = find_which("docker")
            has_singularity = find_which("singularity")
            if has_singularity:
                USE_SINGULARITY = True
                message(ff("Using {has_singularity} for container mode"))
                import radiopadre_client.backends.singularity
                backend = radiopadre_client.backends.singularity
                backend.init(binary=has_singularity, docker_binary=has_docker)
                break
        message(ff("The '{backend}' back-end is not available."))
    else:
        bye(ff("None of the specified back-ends are available."))

    # if not None, gives the six port assignments
    attaching_to_ports = container_name = None

    # ### ps/ls command
    if command == 'ps' or command == 'ls':
        session_dict = backend.list_sessions()
        num = len(session_dict)
        message("{} session{} running".format(num, "s" if num != 1 else ""))
        for i, (id, (name, path, uptime, session_id, ports)) in enumerate(session_dict.items()):
            print("{i}: id {id}, name {name}, in {path}, up since {uptime}".format(**locals()))
        sys.exit(0)

    # ### kill command
    if command == 'kill':
        session_dict = backend.list_sessions()
        if not session_dict:
            bye("no sessions running, nothing to kill")
        if arguments[0] == "all":
            kill_sessions = session_dict.keys()
        else:
            kill_sessions = [backend.identify_session(session_dict, arg) for arg in arguments]
        backend.kill_sessions(session_dict, kill_sessions)
        sys.exit(0)

    ## attach command
    if command == "resume":
        session_dict = backend.list_sessions()
        if arguments:
            id_ = backend.identify_session(session_dict, arguments[0])
        else:
            if not session_dict:
                bye("no sessions running, nothing to attach to")
            config.SESSION_ID = session_dict.keys()[0]
        container_name, path, _, _, attaching_to_ports = session_dict[id_]
        message(ff("  Attaching to existing session {config.SESSION_ID} running in {path}"))

    # load command
    elif command == 'load':
        attaching_to_ports = None

    # else unknown command
    else:
        bye("unknown command {}".format(command))

    running_session_dict = None

    # ### SETUP LOCAL SESSION PROPERTIES: container_name, session_id, port assignments

    # REATTACH MODE: everything is read from the session file
    if attaching_to_ports:
        # session_id and container_name already set above. Ports read from session file and printed to the console
        # for the benefit of the remote end (if any)
        jupyter_port, helper_port, http_port, carta_port, carta_ws_port = selected_ports = attaching_to_ports[:5]
        userside_ports = attaching_to_ports[5:]
    # INSIDE CONTAINER: internal ports are fixed, userside ports are passed in, name is passed in, session ID is read from file
    elif config.INSIDE_CONTAINER_PORTS:
        message("started the radiopadre container")
        container_name = os.environ['RADIOPADRE_CONTAINER_NAME']
        config.SESSION_ID = os.environ['RADIOPADRE_SESSION_ID']
        selected_ports = config.INSIDE_CONTAINER_PORTS[:5]
        userside_ports = config.INSIDE_CONTAINER_PORTS[5:]
        message("  Inside container, using ports {}".format(" ".join(map(str, config.INSIDE_CONTAINER_PORTS))))
    # NORMAL MODE: find unused internal ports. Userside ports are passed from remote if in remote mode, or same in local mode
    else:
        if not USE_VENV:
            container_name = "radiopadre-{}-{}".format(config.USER, uuid.uuid4().hex)
            message(ff("Starting new session in container {container_name}"))
            # get dict of running sessions (for GRIM_REAPER later)
            running_session_dict = backend.list_sessions()
        else:
            container_name = None
            message("Starting new session in virtual environment")
        selected_ports = [find_unused_port(1024)]
        for i in range(4):
            selected_ports.append(find_unused_port(selected_ports[-1] + 1))

        if config.REMOTE_MODE_PORTS:
            userside_ports = config.REMOTE_MODE_PORTS
        else:
            userside_ports = selected_ports

        os.environ['RADIOPADRE_SESSION_ID'] = config.SESSION_ID = uuid.uuid4().hex

        # write out session file
        if container_name:
            backend.save_session_info(container_name, selected_ports, userside_ports)

    global userside_jupyter_port  # needed for it to be visible to ff() from a list comprehension
    jupyter_port, helper_port, http_port, carta_port, carta_ws_port = selected_ports
    userside_jupyter_port, userside_helper_port, userside_http_port, userside_carta_port, userside_carta_ws_port = userside_ports

    # print port assignments to console -- in remote mode, remote script will parse this out
    if not config.INSIDE_CONTAINER_PORTS:
        message("  Selected ports: {}".format(":".join(map(str, selected_ports + userside_ports))))
        message(ff("  Session ID/notebook token is '{config.SESSION_ID}'"))
        if container_name is not None:
            message(ff("  Container name: {container_name}"))

    # ### will we be starting a browser?

    browser = False
    if config.INSIDE_CONTAINER_PORTS:
        if config.VERBOSE:
            message("  Running inside container -- not opening a browser in here.")
    elif config.REMOTE_MODE_PORTS:
        if config.VERBOSE:
            message("  Remote mode -- not opening a browser locally.")
    elif os.environ.get("SSH_CLIENT"):
        message("You appear to have logged in via ssh.")
        message("You're logged in via ssh, so I'm not opening a web browser for you.")
        message("Please manually browse to the URL printed by Jupyter below. You will probably want to employ ssh")
        message("port forwarding if you want to browse this notebook from your own machine.")
        browser = False
    else:
        message("You appear to have a local session.")
        if not config.BROWSER:
            message("--no-browser is set, we will not invoke a browser.")
            message("Please manually browse to the URL printed below.")
            browser = False
        else:
            message(ff(
                "We'll attempt to open a web browser (using '{config.BROWSER}') as needed. Use --no-browser to disable this."))
            browser = True

    # ### ATTACHING TO EXISTING SESSION: complete the attachment and exit

    if attaching_to_ports:
        url = ff("http://localhost:{userside_jupyter_port}/tree#running?token={session_id}")
        # in local mode, see if we need to open a browser. Else just print the URL -- remote script will pick it up
        if not config.REMOTE_MODE_PORTS and browser:
            message(ff("driving browser: {config.BROWSER} {url}"))
            subprocess.call([config.BROWSER, url], stdout=DEVNULL)
            time.sleep(1)
        else:
            message(ff("Browse to URL: {url}"), color="GREEN")
        # emit message so remote initiates browsing
        if config.REMOTE_MODE_PORTS:
            message("The Jupyter Notebook is running inside the reattached session, presumably")
            if config.VERBOSE:
                message("sleeping")
            while True:
                time.sleep(1000000)
        sys.exit(0)

    # ### NEW SESSION: from this point on, we're opening a new session

    # ### setup working directory and notebook paths
    global LOAD_DIR
    global LOAD_NOTEBOOK

    # if explicit notebook directory is given, change into it before doing anything else
    if notebook_path:
        if os.path.isdir(notebook_path):
            os.chdir(notebook_path)
            notebook_path = '.'
            LOAD_DIR = True
            LOAD_NOTEBOOK = None
        else:
            nbdir = os.path.dirname(notebook_path)
            if nbdir:
                if not os.path.isdir(nbdir):
                    bye("{} doesn't exist".format(nbdir))
                os.chdir(nbdir)
            notebook_path = os.path.basename(notebook_path)
            LOAD_DIR = False
            LOAD_NOTEBOOK = notebook_path
    else:
        LOAD_DIR = '.'
        LOAD_NOTEBOOK = None

    # message(ff("{LOAD_DIR} {LOAD_NOTEBOOK} {notebook_path}"))

    #
    if config.NBCONVERT and not LOAD_NOTEBOOK:
        bye("a notebook must be specified in order to use --nbconvert")

    # if using containers (and not inside a container), see if older sessions need to be reaped
    if running_session_dict and config.GRIM_REAPER:
        kill_sessions = []
        for cont, (_, path, _, sid, _) in running_session_dict.items():
            if sid != config.SESSION_ID and os.path.samefile(path, os.getcwd()):
                message(ff("reaping older session {sid}"))
                kill_sessions.append(cont)

        if kill_sessions:
            backend.kill_sessions(running_session_dict, kill_sessions, ignore_fail=True)

    # virtual environment
    os.environ["RADIOPADRE_VENV"] = config.RADIOPADRE_VENV

    # init paths & environment
    iglesia.init()
    iglesia.set_userside_ports(userside_ports)

    global JUPYTER_OPTS
    if config.NBCONVERT:
        JUPYTER_OPTS = ["nbconvert", "--ExecutePreprocessor.timeout=600",
                        "--no-input",
                        "--to", "html_embed", "--execute"]
        os.environ["RADIOPADRE_NBCONVERT"] = "True"
    else:
        JUPYTER_OPTS = ["notebook",
                        "--ContentsManager.pre_save_hook=radiopadre_utils.notebook_utils._notebook_save_hook",
                        "--ContentsManager.allow_hidden=True"]
        os.environ.pop("RADIOPADRE_NBCONVERT", None)

    # update installation etc.
    backend.update_installation()

    # (when running natively (i.e. in a virtual environment), the notebook app doesn't pass the token to the browser
    # command properly... so let it pick its own token then)
    # if options.remote or options.config.INSIDE_CONTAINER_PORTS or not options.virtual_env:
    JUPYTER_OPTS += [
        ff("--NotebookApp.token='{config.SESSION_ID}'"),
        ff("--NotebookApp.custom_display_url='http://localhost:{userside_jupyter_port}'")
    ]

    #=== figure out whether we initialize or load a notebook
    os.chdir(iglesia.SERVER_BASEDIR)
    if iglesia.SNOOP_MODE:
        warning(ff("{iglesia.ABSROOTDIR} is not writable for you, so radiopadre is operating in snoop mode."))

    ALL_NOTEBOOKS = glob.glob("*.ipynb")

    if iglesia.SNOOP_MODE and not ALL_NOTEBOOKS:
        orig_notebooks = glob.glob(os.path.join(iglesia.ABSROOTDIR, "*.ipynb"))
        if orig_notebooks:
            message("  No notebooks in shadow directory: will copy notebooks from target.")
            message("  Copying {} notebooks from {}".format(len(orig_notebooks), iglesia.ABSROOTDIR))
            for nb in orig_notebooks:
                shutil.copyfile(nb, './' + os.path.basename(nb))
            ALL_NOTEBOOKS = glob.glob("*.ipynb")

    message("  Available notebooks: " + " ".join(ALL_NOTEBOOKS))

    if not config.INSIDE_CONTAINER_PORTS:

        # if no notebooks in place, see if we need to create a default
        if not ALL_NOTEBOOKS:
            if config.DEFAULT_NOTEBOOK:
                message(ff("  No notebooks yet: will create {config.DEFAULT_NOTEBOOK}"))
                LOAD_DIR = True
                open(config.DEFAULT_NOTEBOOK, 'wt').write(default_notebook_code)
                ALL_NOTEBOOKS = [config.DEFAULT_NOTEBOOK]
            else:
                message("  No notebooks and no default. Displaying directory only.")
                LOAD_DIR = True
                LOAD_NOTEBOOK = None

        # expand globs and apply auto-load as needed
        if LOAD_NOTEBOOK:
            LOAD_NOTEBOOK = [nb for nb in ALL_NOTEBOOKS if fnmatch.fnmatch(os.path.basename(nb), LOAD_NOTEBOOK)]
        elif config.AUTO_LOAD == "1":
            LOAD_NOTEBOOK = ALL_NOTEBOOKS[0] if ALL_NOTEBOOKS else None
            message(ff("  Auto-loading {LOAD_NOTEBOOK[0]}."))
        elif config.AUTO_LOAD:
            LOAD_NOTEBOOK = [nb for nb in ALL_NOTEBOOKS if fnmatch.fnmatch(os.path.basename(nb), config.AUTO_LOAD)]
            if LOAD_NOTEBOOK:
                message("  Auto-loading {}".format(" ".join(LOAD_NOTEBOOK)))
            else:
                message(ff("  No notebooks matching --auto-load {config.AUTO_LOAD}"))

    urls = []
    if LOAD_DIR:
        urls.append(ff("http://localhost:{userside_jupyter_port}/?token={config.SESSION_ID}"))
    if LOAD_NOTEBOOK:
        urls += [ff("http://localhost:{userside_jupyter_port}/notebooks/{nb}?token={config.SESSION_ID}")
                 for nb in LOAD_NOTEBOOK]

    if not config.NBCONVERT:
        for url in urls:
            message(ff("Browse to URL: {url}"), color="GREEN")

        if config.CARTA_BROWSER:
            url = ff("http://localhost:{iglesia.CARTA_PORT}/?socketUrl=ws://localhost:{iglesia.CARTA_WS_PORT}")
            message(ff("Browse to URL: {url} (CARTA file browser)"), color="GREEN")
            urls.append(url)

    # now we're ready to start the session

    backend.start_session(container_name, selected_ports, userside_ports,
                          notebook_path, browser and urls)
