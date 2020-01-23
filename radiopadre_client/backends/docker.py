import subprocess, glob, os, os.path, re, sys, socket, time
from collections import OrderedDict

from radiopadre_client.utils import message, make_dir, bye, shell, DEVNULL, run_browser
from radiopadre_client import config
from radiopadre_client.config import USER, CONTAINER_PORTS, SERVER_INSTALL_PATH, CLIENT_INSTALL_PATH

docker = None
SESSION_INFO_DIR = '.'

def init(binary):
    global docker
    docker = binary
    _init_session_dir()

def _init_session_dir():
    make_dir("~/.radiopadre")
    global SESSION_INFO_DIR
    SESSION_INFO_DIR = os.path.expanduser("~/.radiopadre/.sessions")
    make_dir(SESSION_INFO_DIR)

def _ps_containers():
    """Returns OrderedDict (ordered by uptime) of containers returned by docker ps.
    Dict is name -> [id, path, uptime, None, None]"""
    lines = subprocess.check_output([docker, "ps", "--filter", "label=radiopadre.user={}".format(USER),
                "--format", """{{.CreatedAt}}:::{{.ID}}:::{{.Names}}:::{{.Label "radiopadre.dir"}}"""]).strip()
    container_list = sorted([line.split(":::") for line in lines.split("\n") if len(line.split(":::")) == 4], reverse=True)
    return OrderedDict([(name, [id_, path, time, None, None]) for time, id_, name, path in container_list])


def get_session_info_dir(container_name):
    return os.path.join(SESSION_INFO_DIR, container_name)


def read_session_info(container_name):
    """Reads the given session ID file. Returns session_id, ports, or else throws a ValueError"""
    dirname = get_session_info_dir(container_name)

    comps = open(dirname + "/info").read().strip().split(" ")
    if len(comps) != 11:
        raise ValueError("invalid session dir " + dirname)
    session_id = comps[0]
    try:
        ports = map(int, comps[1:])
    except:
        raise ValueError("invalid session dir " + dirname)
    return session_id, ports


def save_session_info(container_name, session_id, selected_ports, userside_ports):
    session_info_dir = "{}/{}".format(SESSION_INFO_DIR, container_name)
    make_dir(session_info_dir)
    session_info_file = session_info_dir + "/info"
    open(session_info_file, "w").write(" ".join(map(str, [session_id] + selected_ports + userside_ports)))
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
            message("container {} is no longer running, clearing up session dir".format(name))
            subprocess.call(["rm", "-fr", session_dir])
            continue
        try:
            container_dict[name][3], container_dict[name][4] = read_session_info(session_dir)
        except ValueError:
            message(f"invalid session dir {session_dir}")
            continue
    output = OrderedDict()

    # check for containers without session info and form up output dict
    for name, (id_, path, time, session_id, ports) in container_dict.items():
        if session_id is None:
            message("container {} has no session dir -- killing it".format(name))
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


def kill_sessions(session_dict, session_ids):
    kill_cont = " ".join(session_ids)
    message("killing containers: {}".format(kill_cont))
    for cont in session_ids:
        if cont not in session_dict:
            bye("no such radiopadre container: {}".format(cont))
        name, path, _, _, _ = session_dict[cont]
        session_id_file = "{}/{}".format(SESSION_INFO_DIR, name)
        if os.path.exists(session_id_file):
            subprocess.call(["rm", "-fr", session_id_file])
    shell(f"{docker} kill " + kill_cont)


def update_installation():
    global docker_image
    docker_image = config.DOCKER_IMAGE
    message(f"  Using radiopadre Docker image {docker_image}")
    if config.UPDATE:
        message("  Calling docker pull to make sure the image is up-to-date.")
        message("  (This may take a few minutes if it isn't....)")
        subprocess.call([docker, "pull", docker_image])


def start_session(container_name, session_id, selected_ports, userside_ports, orig_rootdir, notebook_path, browser_urls):
    from radiopadre_client.server import PADRE_WORKDIR, ABSROOTDIR, LOCAL_SESSION_DIR, SHADOW_SESSION_DIR

    docker_local = make_dir("~/.radiopadre/.docker-local")
    js9_tmp = make_dir("~/.radiopadre/.js9-tmp")
    session_info_dir = get_session_info_dir(container_name)

    message(f"Container name: {container_name}")  # remote script will parse it

    docker_opts = [ docker, "run", "--rm", "--name", container_name, "-w", ABSROOTDIR,
                        "--user", "{}:{}".format(os.getuid(), os.getgid()),
                        "-e", "USER={}".format(os.environ["USER"]),
                        "-e", "HOME={}".format(os.environ["HOME"]),
                        "-e", "RADIOPADRE_CONTAINER_NAME={}".format(container_name)
                  ]
    # enable detached mode if not debugging
    if not config.DOCKER_DEBUG:
        docker_opts.append("-d")
    for port1, port2 in zip(selected_ports, CONTAINER_PORTS):
        docker_opts += [ "-p", "{}:{}/tcp".format(port1, port2)]
    container_ports = list(CONTAINER_PORTS)
    # setup mounts for work dir and home dir, if needed
    homedir = os.path.expanduser("~")
    docker_opts += [
                     "-v", "{}:{}{}".format(ABSROOTDIR, ABSROOTDIR, ":ro" if orig_rootdir else ""),
                     "-v", "{}:{}".format(homedir, homedir),
                     # hides /home/user/.local, which if exposed, can confuse jupyter and ipython
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

    docker_opts += [ "run-radiopadre",
                     "--inside-container", ":".join(map(str, container_ports + userside_ports)),
                     "--workdir", PADRE_WORKDIR,
                     "--radiopadre-venv", "/.radiopadre/venv"
                   ]

    if notebook_path:
        docker_opts.append(notebook_path)

    _run_container(container_name, docker_opts, jupyter_port=selected_ports[0], browser_urls=browser_urls)


    if config.DOCKER_DETACH:
        message("exiting: container session will remain running.")
        sys.exit(0)

    elif config.REMOTE_MODE_PORTS:
        if config.VERBOSE:
            message("sleeping")
        while True:
            time.sleep(1000000)
    else:
        try:
            while True:
                a = input("Type Q<Enter> to detach from the container session, or Ctrl+C to kill it: ")
                if a and a[0].upper() == 'Q':
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
            if status:
                message("Killing the container")
                subprocess.call([docker, "kill", container_name], stdout=DEVNULL)
            sys.exit(status)


def _run_container(container_name, docker_opts, jupyter_port, browser_urls, singularity=False):

    child_processes = []

    # add arguments
    if config.DOCKER_DEBUG:
        docker_opts.append("--docker-debug")
    if config.VERBOSE:
        docker_opts.append("--verbose")
    if config.DEFAULT_NOTEBOOK:
        docker_opts.append(f"--default-notebook {config.DEFAULT_NOTEBOOK}" if config.DEFAULT_NOTEBOOK else
                           "--no-default-notebook")

    message("Running {}".format(" ".join(map(str, docker_opts))))
    if singularity:
        message("  (When using singularity and the image is not yet available locally, this can take a few minutes the first time you run.)")

    if config.DOCKER_DEBUG:
        docker_process = subprocess.Popen(docker_opts, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    else:
        docker_process = subprocess.Popen(docker_opts, stdout=DEVNULL)
                                      #stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                                      #env=os.environ)
    child_processes.append(docker_process)

    # pause to let the Jupyter server spin up
    t0 = time.time()
    time.sleep(5)
    # then try to connect to it
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for retry in range(1000):
        try:
            sock.connect(("localhost", jupyter_port))
            message("Container started: the Jupyter Notebook is running on port {} (after {} secs)".format(
                        jupyter_port, time.time() - t0))
            del sock
            break
        except socket.error:
            time.sleep(.1)
    else:
        bye("unable to connect to Jupyter Notebook server on port {jupyter_port}")

    if browser_urls:
        child_processes += run_browser(*browser_urls)
        # give things a second (to let the browser command print its stuff, if it wants to)
        time.sleep(1)


    return docker_process

