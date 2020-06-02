import subprocess, glob, os, os.path, re, sys, time, signal, atexit
from collections import OrderedDict

import iglesia
from iglesia.utils import message, warning, make_dir, make_radiopadre_dir, bye, shell, DEVNULL, ff, INPUT, check_output
from radiopadre_client import config
from radiopadre_client.config import USER, CONTAINER_PORTS, SERVER_INSTALL_PATH, CLIENT_INSTALL_PATH
from radiopadre_client.server import run_browser

from .backend_utils import await_server_startup, update_server_from_repository

docker = None
SESSION_INFO_DIR = '.'
running_container = None

def init(binary):
    global docker
    docker = binary
    _init_session_dir()

def _init_session_dir():
    radiopadre_dir = make_radiopadre_dir()
    global SESSION_INFO_DIR
    SESSION_INFO_DIR = ff("{radiopadre_dir}/sessions")
    make_dir(SESSION_INFO_DIR)

def _ps_containers():
    """Returns OrderedDict (ordered by uptime) of containers returned by docker ps.
    Dict is name -> [id, path, uptime, None, None]"""
    lines = subprocess.check_output([docker, "ps", "--filter", "label=radiopadre.user={}".format(USER),
                "--format", """{{.CreatedAt}}:::{{.ID}}:::{{.Names}}:::{{.Label "radiopadre.dir"}}"""]).decode().strip()
    container_list = sorted([line.split(":::") for line in lines.split("\n") if len(line.split(":::")) == 4], reverse=True)
    return OrderedDict([(name, [id_, path, time, None, None]) for time, id_, name, path in container_list])


def get_session_info_dir(container_name):
    return os.path.join(SESSION_INFO_DIR, container_name)


def read_session_info(container_name):
    """Reads the given session ID file. Returns session_id, ports, or else throws a ValueError"""
    dirname = get_session_info_dir(container_name)
    session_file = ff("{dirname}/info")

    if not os.path.exists(session_file):
        raise ValueError(ff("invalid session dir {dirname}"))

    comps = open(session_file, "rt").read().strip().split(" ")
    if len(comps) != 11:
        raise ValueError(ff("invalid session dir {dirname}"))
    session_id = comps[0]
    try:
        ports = map(int, comps[1:])
    except:
        raise ValueError(ff("invalid session dir {dirname}"))
    return session_id, ports


def save_session_info(container_name, selected_ports, userside_ports):
    session_info_dir = "{}/{}".format(SESSION_INFO_DIR, container_name)
    make_dir(session_info_dir)
    session_info_file = session_info_dir + "/info"
    open(session_info_file, "wt").write(" ".join(map(str, [config.SESSION_ID] + selected_ports + userside_ports)))
    os.chmod(session_info_file, 0o600)
    userside_helper_port = userside_ports[1]
    open(session_info_dir + "/js9prefs.js", "w").write(
        "JS9Prefs.globalOpts.helperPort = {};\n".format(userside_helper_port))


def list_sessions():
    """Returns OrderedDict (ordered by uptime) of running containers with their session IDs. Clears up dead sessions.
    Dict is id -> [name, path, uptime, session_id, ports]"""
    container_dict = _ps_containers()
    # match session files to containers
    for session_dir in glob.glob(SESSION_INFO_DIR + "/radiopadre-*"):
        name = os.path.basename(session_dir)
        if name not in container_dict:
            message("    container {} is no longer running, clearing up session dir".format(name))
            subprocess.call(["rm", "-fr", session_dir])
            continue
        try:
            container_dict[name][3], container_dict[name][4] = read_session_info(session_dir)
        except ValueError:
            message(ff("    invalid session dir {session_dir}"))
            continue
    output = OrderedDict()

    # check for containers without session info and form up output dict
    for name, (id_, path, time, session_id, ports) in container_dict.items():
        if session_id is None:
            message("    container {} has no session dir -- killing it".format(name))
            subprocess.call([docker, "kill", id_])
        else:
            output[id_] = [name, path, time, session_id, ports]

    return output


def identify_session(session_dict, arg):
    """Returns ID of container corresponding to ID or ordinal number. Throws errors on mismatch."""
    if len(arg) <= 4 and re.match('^\d+$', arg):
        arg = int(arg)
        if arg >= len(session_dict):
            bye("invalid session #{}, we only have {} running".format(arg, len(session_dict)))
        return session_dict.keys()[arg]
    elif arg not in session_dict:
        bye("invalid container ID {}".format(arg))
    return arg


def kill_sessions(session_dict, session_ids, ignore_fail=False):
    kill_cont = " ".join(session_ids)
    message("    killing containers: {}".format(kill_cont))
    for cont in session_ids:
        if cont not in session_dict:
            bye("no such radiopadre container: {}".format(cont))
        name, path, _, _, _ = session_dict[cont]
        session_id_file = "{}/{}".format(SESSION_INFO_DIR, name)
        if os.path.exists(session_id_file):
            subprocess.call(["rm", "-fr", session_id_file])
    shell(ff("{docker} kill {kill_cont}"), ignore_fail=True)


def update_installation(enable_pull=False):
    global docker_image
    enable_pull = enable_pull or config.AUTO_INIT or config.UPDATE
    if config.CONTAINER_DEV:
        update_server_from_repository()
    docker_image = config.DOCKER_IMAGE
    if check_output(ff("docker image inspect {docker_image}")) is None:
        if not enable_pull:
            bye(ff("  Radiopadre docker image {docker_image} not found. Re-run with --update perhaps?"))
        message(ff("  Radiopadre docker image {docker_image} not found locally"))
    else:
        message(ff("  Using radiopadre docker image {docker_image}"))
    if enable_pull:
        warning(ff("Calling docker pull {docker_image}"))
        warning("  (This may take a few minutes if the image is not up to date...)")
        try:
            subprocess.call([docker, "pull", docker_image])
        except subprocess.CalledProcessError as exc:
            if config.IGNORE_UPDATE_ERRORS:
                warning("docker pull failed, but --ignore-update-errors is set, proceeding anyway")
                return
            raise exc


def _collect_runscript_arguments(ports):
    from iglesia import SHADOW_HOME as PADRE_WORKDIR

    run_config = config.get_config_dict()
    run_config["BACKEND"] = "venv"
    run_config["UPDATE"] = False
    run_config["BROWSER"] = "None"
    run_config["INSIDE_CONTAINER"] = ":".join(map(str, ports))
    run_config["WORKDIR"] = PADRE_WORKDIR
    run_config["RADIOPADRE_VENV"] = "/.radiopadre/venv"

    # some keys shouldn't be passed to the in=-container script at all
    for key in ("CLIENT_INSTALL_PATH", "SERVER_INSTALL_PATH", "SINGULARITY_IMAGE_DIR",
                "AUTO_INIT", "SINGULARITY_REBUILD", "SINGULARITY_AUTO_BUILD"):
        if key in run_config:
            del run_config[key]

    return config.get_options_list(run_config, quote=False)
    #return ["run-radiopadre"] + config.get_options_list(run_config, quote=False)


def start_session(container_name, selected_ports, userside_ports, notebook_path, browser_urls):
    from iglesia import ABSROOTDIR, LOCAL_SESSION_DIR, SHADOW_SESSION_DIR, SNOOP_MODE
    radiopadre_dir = make_radiopadre_dir()
    docker_local = make_dir(radiopadre_dir + "/.docker-local")
    js9_tmp = make_dir(radiopadre_dir + "/.js9-tmp")
    session_info_dir = get_session_info_dir(container_name)

    message(ff("Container name: {container_name}"))  # remote script will parse it

    docker_opts = [ docker, "run", "--rm", "--name", container_name, 
                        "--cap-add=SYS_ADMIN",
                        "-w", ABSROOTDIR,
                        "--user", "{}:{}".format(os.getuid(), os.getgid()),
                        "-e", "USER={}".format(os.environ["USER"]),
                        "-e", "HOME={}".format(os.environ["HOME"]),
                        "-e", ff("RADIOPADRE_CONTAINER_NAME={container_name}"),
                        "-e", ff("RADIOPADRE_SESSION_ID={config.SESSION_ID}"),
                    ]
    # enable detached mode if not debugging, and also if not doing conversion non-interactively
    if not config.CONTAINER_DEBUG and not config.NBCONVERT:
        docker_opts.append("-d")
    for port1, port2 in zip(selected_ports, CONTAINER_PORTS):
        docker_opts += [ "-p", "{}:{}/tcp".format(port1, port2)]
    container_ports = list(CONTAINER_PORTS)
    # setup mounts for work dir and home dir, if needed
    homedir = os.path.expanduser("~")
    docker_opts += [
                     "-v", "{}:{}{}".format(ABSROOTDIR, ABSROOTDIR, ":ro" if SNOOP_MODE else ""),
                     "-v", "{}:{}".format(homedir, homedir),
                     ## hides /home/user/.local, which can confuse jupyter and ipython
                     ## into seeing e.g. kernelspecs that they should not see
                     "-v", "{}:{}/.local".format(docker_local, homedir),
                     # mount session info directory (needed to serve e.g. js9prefs.js)
                     "-v", "{}:{}".format(session_info_dir, LOCAL_SESSION_DIR),
                     "-v", "{}:{}".format(session_info_dir, SHADOW_SESSION_DIR),
                     # mount a writeable tmp dir for the js9 install -- needed by js9helper
                     "-v", "{}:/.radiopadre/venv/js9-www/tmp".format(js9_tmp),
                     "--label", "radiopadre.user={}".format(USER),
                     "--label", "radiopadre.dir={}".format(os.getcwd()),
    ]
    if config.CONTAINER_DEV:
        if os.path.isdir(SERVER_INSTALL_PATH):
            docker_opts += [ "-v", "{}:/radiopadre".format(SERVER_INSTALL_PATH) ]
        if os.path.isdir(CLIENT_INSTALL_PATH):
            docker_opts += [ "-v", "{}:/radiopadre-client".format(CLIENT_INSTALL_PATH) ]
    # add image
    docker_opts.append(docker_image)

    # build up command-line arguments
    docker_opts += _collect_runscript_arguments(container_ports + userside_ports)

    if notebook_path:
        docker_opts.append(notebook_path)

    _run_container(container_name, docker_opts, jupyter_port=selected_ports[0], browser_urls=browser_urls)

    if config.NBCONVERT:
        return

    global running_container
    running_container = container_name
    atexit.register(reap_running_container)

    if config.CONTAINER_PERSIST and config.CONTAINER_DETACH:
        message("exiting: container session will remain running.")
        running_container = None # to avoid reaping
        sys.exit(0)
    else:
        if config.CONTAINER_PERSIST:
            prompt = "Type 'exit' to kill the container session, or 'D' to detach: "
        else:
            prompt = "Type 'exit' to kill the container session: "
        try:
            while True:
                a = INPUT(prompt)
                if a.lower() == 'exit':
                    sys.exit(0)
                if a.upper() == 'D' and config.CONTAINER_PERSIST and container_name:
                    running_container = None  # to avoid reaping
                    sys.exit(0)
        except BaseException as exc:
            if type(exc) is KeyboardInterrupt:
                message("Caught Ctrl+C")
                status = 1
            elif type(exc) is SystemExit:
                status = getattr(exc, 'code', 0)
                message("Exiting with status {}".format(status))
            else:
                message("Caught exception {} ({})".format(exc, type(exc)))
                status = 1
            # if not status:
            #     running_container = None  # to avoid reaping
            sys.exit(status)

def _run_container(container_name, docker_opts, jupyter_port, browser_urls, singularity=False):

    message("Running {}".format(" ".join(map(str, docker_opts))))
    if singularity:
        message(
            "  (When using singularity and the image is not yet available locally, this can take a few minutes the first time you run.)")

    if config.CONTAINER_DEBUG:
        docker_process = subprocess.Popen(docker_opts, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    else:
        docker_process = subprocess.Popen(docker_opts, stdout=DEVNULL,
                                           stderr=DEVNULL if config.NON_INTERACTIVE else sys.stderr)
                                      #stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                                      #env=os.environ)

    if config.NBCONVERT:
        message("Waiting for conversion to finish")
        docker_process.wait()
        return None

    else:

        # pause to let the Jupyter server spin up
        wait = await_server_startup(jupyter_port, process=docker_process, init_wait=1, server_name="notebook container")

        if wait is None:
            if docker_process.returncode is not None:
                bye(ff("container unexpectedly exited with return code {docker_process.returncode}"))
            bye(ff("unable to connect to jupyter notebook server on port {jupyter_port}"))

        message(
            ff("Container started. The jupyter notebook server is running on port {jupyter_port} (after {wait:.2f} secs)"))

        if browser_urls:
            iglesia.register_helpers(*run_browser(*browser_urls))
            # give things a second (to let the browser command print its stuff, if it wants to)
            time.sleep(1)

    return docker_process

def kill_container(name):
    message(ff("Killing container {name}"))
    shell(ff("{docker} kill {name}"), ignore_fail=True)

def reap_running_container():
    global running_container
    if running_container:
        kill_container(running_container)
    running_container = None