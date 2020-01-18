import os, os.path, sys, subprocess, re, time, glob, uuid, shutil, socket
from collections import OrderedDict

from .utils import DEVNULL, DEVZERO, message, bye, shell, find_unused_port, find_which, make_dir, make_link
from .config import USER, DEFAULT_DOCKER_IMAGE, CONTAINER_PORTS
from .notebooks import default_notebook_code

backend = None

PADRE_WORKDIR = PADRE_VENV = ABSROOTDIR = ROOTDIR = SHADOWDIR = None

LOCAL_SESSION_DIR = SHADOW_SESSION_DIR = None

JUPYTER_OPTS = LOAD_DIR = LOAD_NOTEBOOK = None

def run_radiopadre_server(command, arguments, notebook_path, options):
    global backend

    message("Welcome to Radiopadre!")

    if options.virtual_env:
        import radiopadre_client.backends.venv
        backend = radiopadre_client.backends.venv
        backend.init(options)

    if options.virtual_env or options.inside_container:
        docker = singularity = None
    else:
        singularity = find_which("singularity")
        docker = find_which("docker")
        if options.singularity and not singularity:
            bye("singularity binary not found")
        if options.docker:
            singularity = None
            if not docker:
                bye("docker binary not found")
        if singularity:
            message(f"Using {singularity} for container mode")
            import radiopadre_client.backends.singularity
            backend = radiopadre_client.backends.singularity
            backend.init(options, binary=singularity)
            docker = None
        elif docker:
            message(f"Using {docker} for container mode")
            import radiopadre_client.backends.docker
            backend = radiopadre_client.backends.docker
            backend.init(options, binary=docker)
        else:
            bye("neither singularity nor docker found. Use --virtual-env perhaps?")


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
            id_ = session_dict.keys()[0]
        container_name, path, _, session_id, attaching_to_ports = session_dict[id_]
        message(f"  Attaching to existing session (ID: {id_}) running in {path}")

    # load command
    elif command == 'load':
        attaching_to_ports = None

    # else unknown command
    else:
        bye("unknown command {}".format(command))


    # ### SETUP LOCAL SESSION PROPERTIES: container_name, session_id, port assignments

    # REATTACH MODE: everything is read from the session file
    if attaching_to_ports:
        # session_id and container_name already set above. Ports read from session file and printed to the console
        # for the benefit of the remote end (if any)
        jupyter_port, helper_port, http_port, carta_port, carta_ws_port = selected_ports = attaching_to_ports[:5]
        userside_ports = attaching_to_ports[5:]
    # INSIDE CONTAINER: internal ports are fixed, userside ports are passed in, name is passed in, session ID is read from file
    elif options.inside_container:
        message("started the radiopadre container")
        container_name = os.environ['RADIOPADRE_CONTAINER_NAME']
        session_id, _ = backend.read_session_info(container_name)
        os.environ['RADIOPADRE_SESSION_ID'] = session_id
        ports = map(int, options.inside_container.split(":"))
        selected_ports = ports[:5]
        userside_ports = ports[5:]
        message("  Inside container, using ports {}".format(ports))
    # NORMAL MODE: find unused internal ports. Userside ports are passed from remote if in remote mode, or same in local mode
    else:
        if not options.virtual_env:
            container_name = "radiopadre-{}-{}".format(USER, uuid.uuid4().hex)
            message(f"  Starting new session in container {container_name}")
        else:
            container_name = None
            message("  Starting new session in virtual environment")
        selected_ports = [find_unused_port(1024)]
        for i in range(4):
            selected_ports.append(find_unused_port(selected_ports[-1] + 1))

        if options.remote:
            userside_ports = list(map(int, options.remote.split(":")))
        else:
            userside_ports = selected_ports

        os.environ['RADIOPADRE_SESSION_ID'] = session_id = uuid.uuid4().hex

        # write out session file
        if container_name:
            backend.save_session_info(container_name, session_id, selected_ports, userside_ports)

    jupyter_port, helper_port, http_port, carta_port, carta_ws_port = selected_ports
    userside_jupyter_port, userside_helper_port, userside_http_port, userside_carta_port, userside_carta_ws_port = userside_ports

    # print port assignments to console -- in remote mode, remote script will parse this out
    if not options.inside_container:
        message("  Selected ports: {}:{}:{}:{}:{} {}:{}:{}:{}:{}".format(*(selected_ports + userside_ports)))
        message("  Session ID/notebook token is '{}'".format(session_id))
        if container_name is not None:
            message(f"  Container name: {container_name}")


    # ### will we be starting a browser?

    browser = False
    if options.inside_container:
        if options.verbose:
            message("  Running inside container -- not opening a browser in here.")
    elif options.remote:
        if options.verbose:
            message("  Remote mode -- not opening a browser locally.")
    elif os.environ.get("SSH_CLIENT"):
        message("You appear to have logged in via ssh.")
        message("You're logged in via ssh, so I'm not opening a web browser for you.")
        message("Please manually browse to the URL printed by Jupyter below. You will probably want to employ ssh")
        message("port forwarding if you want to browse this notebook from your own machine.")
        browser = False
    else:
        message("You appear to have a local session.")
        if options.no_browser:
            message("--no-browser is set, we will not invoke a browser.")
            message("Please manually browse to the URL printed below.")
            browser = False
        else:
            message(f"We'll attempt to open a web browser (using '{options.browser_command}') as needed. Use --no-browser to disable this.")
            browser = True

    # ### ATTACHING TO EXISTING SESSION: complete the attachment and exit

    if attaching_to_ports:
        url = "http://localhost:{}/tree#running?token={}".format(userside_jupyter_port, session_id)
        # in local mode, see if we need to open a browser. Else just print the URL -- remote script will pick it up
        if not options.remote and browser:
            message(f"driving browser: {options.browser_command} {url}")
            subprocess.call([options.browser_command, url], stdout=DEVNULL)
            time.sleep(1)
        else:
            message(f"Browse to URL: {url}")
        # emit message so remote initiates browsing
        if options.remote:
            message("The Jupyter Notebook is running inside the reattached session, presumably")
            if options.verbose:
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
        if not os.path.exists(notebook_path):
            bye("{} doesn't exist".format(notebook_path))
        if os.path.isdir(notebook_path):
            os.chdir(notebook_path)
            notebook_path = '.'
            LOAD_DIR = True
            LOAD_NOTEBOOK = None
        else:
            nbdir = os.path.dirname(notebook_path)
            if nbdir:
                os.chdir(nbdir)
            notebook_path = os.path.basename(notebook_path)
            LOAD_DIR = False
            LOAD_NOTEBOOK = notebook_path
    else:
        LOAD_DIR = '.'
        LOAD_NOTEBOOK = None

    global PADRE_WORKDIR, PADRE_VENV, ABSROOTDIR, ROOTDIR, SHADOWDIR, LOCAL_SESSION_DIR, SHADOW_SESSION_DIR

    # cache and shadow dir base
    PADRE_WORKDIR = options.workdir or os.path.expanduser("~/.radiopadre")
    os.environ['RADIOPADRE_SHADOW_HOME'] = PADRE_WORKDIR

    # virtual environment
    PADRE_VENV = "/.radiopadre/venv" if options.inside_container else PADRE_WORKDIR + "/venv"
    os.environ["RADIOPADRE_VENV"] = PADRE_VENV

    # target directory
    ABSROOTDIR = ROOTDIR = os.path.abspath(os.getcwd())              # e.g. /home/other/path

    # shadow of target directory
    SHADOWDIR = PADRE_WORKDIR + ROOTDIR                 # e.g. ~/.radiopadre/home/other/path
    if not os.path.exists(SHADOWDIR):
        os.system("mkdir -p {}".format(SHADOWDIR))
    # This is where the per-session js9prefs.js goes. In virtualenv mode, this is just a directory
    # In docker mode, we mount session_info_dir on this
    LOCAL_SESSION_DIR = ABSROOTDIR + "/.radiopadre-session"
    SHADOW_SESSION_DIR = SHADOWDIR + "/.radiopadre-session"

    # make .radiopadre and .radiopadre-session in target dir, or in shadow dir
    cachedir = ABSROOTDIR + "/.radiopadre"
    cachelink = SHADOWDIR + "/.radiopadre"
    if os.access(ABSROOTDIR, os.W_OK):
        make_dir(cachedir)
        make_link(cachedir, cachelink, rm_fr=True)
        make_dir(LOCAL_SESSION_DIR)
        make_link(LOCAL_SESSION_DIR, SHADOW_SESSION_DIR, rm_fr=True)
    else:
        if os.path.islink(cachelink):
            os.unlink(cachelink)
        make_dir(cachelink)
        if os.path.islink(SHADOW_SESSION_DIR):
            os.unlink(SHADOW_SESSION_DIR)
        make_dir(SHADOW_SESSION_DIR)

    global JUPYTER_OPTS
    JUPYTER_OPTS = [
        "notebook",
        "--ContentsManager.pre_save_hook=radiopadre_utils.notebook_utils._notebook_save_hook",
        "--ContentsManager.allow_hidden=True" ]

    # update installation etc.
    backend.update_installation(options)

    # directory where we were originally run
    os.environ['RADIOPADRE_ABSROOTDIR'] = ABSROOTDIR

    # check if a root directory needs to be faked
    # if not, make .radiopadre workdir
    if os.access(ROOTDIR, os.W_OK):
        os.environ['RADIOPADRE_SERVER_BASEDIR'] = ABSROOTDIR
        orig_rootdir = None
    else:
        message(f"  Target is {ROOTDIR}, which is not user-writeable. Will use a shadow directory instead.")
        message(f"  Shadow directory is {SHADOWDIR}")
        orig_rootdir = ROOTDIR
        os.environ['RADIOPADRE_SERVER_BASEDIR'] = ROOTDIR = SHADOWDIR
        os.chdir(SHADOWDIR)

    make_dir(".radiopadre")


    # when running natively (i.e. in a virtual environment), the notebook app doesn't pass the token to
    # the browser command properly... so let it pick its own token then
    #if options.remote or options.inside_container or not options.virtual_env:
    JUPYTER_OPTS += [
        "--NotebookApp.token='{}'".format(session_id),
        "--NotebookApp.custom_display_url='http://localhost:{}'".format(userside_jupyter_port)
    ]

    #=== figure out whether we initialize or load a notebook

    ALL_NOTEBOOKS = glob.glob("*.ipynb")

    if orig_rootdir and not ALL_NOTEBOOKS:
        orig_notebooks = glob.glob(os.path.join(orig_rootdir, "*.ipynb"))
        if orig_notebooks:
            message("  No notebooks in shadow directory, will copy notebooks from target.")
            message("  Copying {} notebooks from {}".format(len(orig_notebooks), orig_rootdir))
            for nb in orig_notebooks:
                shutil.copyfile(nb, './' + os.path.basename(nb))
            ALL_NOTEBOOKS = glob.glob("*.ipynb")

    message("  Available notebooks: " + " ".join(ALL_NOTEBOOKS))

    if LOAD_NOTEBOOK is None and not options.inside_container:

        DEFAULT_NAME = "radiopadre-default.ipynb"

        if not ALL_NOTEBOOKS:
            if not options.no_default:
                message("  No notebooks: will create {DEFAULT_NAME}")
                LOAD_DIR = True
                open(DEFAULT_NAME, 'w').write(default_notebook_code)
            else:
                message("  No notebooks but --no-default given. Displaying directory only.")
                LOAD_DIR = True
                LOAD_NOTEBOOK = None
        else:
            if LOAD_NOTEBOOK:
                if LOAD_NOTEBOOK in ALL_NOTEBOOKS:
                    message(f"  Will load {LOAD_NOTEBOOK} as requested.")
                else:
                    message(f"  {LOAD_NOTEBOOK} not found. Displaying directory only.")
                    LOAD_DIR = True
                    LOAD_NOTEBOOK = None
            else:
                if not options.no_auto_load:
                    LOAD_NOTEBOOK = ALL_NOTEBOOKS[0]
                    message(f"  Auto-loading {LOAD_NOTEBOOK}.")

    urls = []
    if LOAD_NOTEBOOK:
        urls.append("http://localhost:{}/notebooks/{}?token={}".format(userside_jupyter_port, LOAD_NOTEBOOK, session_id))
    if LOAD_DIR:
        urls.append("http://localhost:{}/?token={}".format(userside_jupyter_port, session_id))

    # desist from printing this if running purely locally, in a virtualenv, as the notebook app handles this for us
    if options.remote or options.inside_container or not options.virtual_env:
        for url in urls:
            message(f"Browse to URL: {url}")

    # now we're ready to start the session

    backend.start_session(options, container_name, session_id, selected_ports, userside_ports, orig_rootdir,
                          notebook_path, browser and urls)
