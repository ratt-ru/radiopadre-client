import os, subprocess, sys, time

from radiopadre_client.utils import message, make_dir, shell, DEVNULL
from radiopadre_client import config

singularity = None

from .docker import get_session_info_dir, save_session_info, _run_container, _init_session_dir, _collect_runscript_arguments


def init(binary):
    global singularity
    singularity = binary
    _init_session_dir()

def read_session_info(container_name):
    raise NotImplementedError("not available in singularity mode")

def list_sessions():
    return {}

def identify_session(session_dict, arg):
    raise NotImplementedError("not available in singularity mode")

def kill_sessions(session_dict, session_ids):
    raise NotImplementedError("not available in singularity mode")

def get_singularity_image(docker_image):
    return "~/.radiopadre/{}.singularity.img".format(docker_image.replace("/", "_"))

def update_installation():
    global docker_image
    global singularity_image
    docker_image = config.DOCKER_IMAGE
    singularity_image = os.path.expanduser(get_singularity_image(docker_image))
    if config.UPDATE and os.path.exists(singularity_image):
        os.unlink(singularity_image)
    if not os.path.exists(singularity_image):
        message(f"  Rebuilding radiopadre Singularity image {singularity_image} from docker://{docker_image}")
        message(f"  (This may take a few minutes....)")
        subprocess.check_call([singularity, "build", singularity_image, "docker://{}".format(docker_image)])
    else:
        message(f"  Using radiopadre Singularity image {singularity_image}")

    # not supported with Singularity
    config.CONTAINER_PERSIST = config.CONTAINER_DEBUG = False


def start_session(container_name, selected_ports, userside_ports, orig_rootdir, notebook_path, browser_urls):
    from radiopadre_client.server import ABSROOTDIR, LOCAL_SESSION_DIR, SHADOW_SESSION_DIR

    docker_local = make_dir("~/.radiopadre/.docker-local")
    js9_tmp = make_dir("~/.radiopadre/.js9-tmp")
    session_info_dir = get_session_info_dir(container_name)

    message(f"Container name: {container_name}")  # remote script will parse it

    os.environ["RADIOPADRE_CONTAINER_NAME"] = container_name
    os.environ["XDG_RUNTIME_DIR"] = ""
    docker_opts = ["--workdir", ABSROOTDIR ]
    # setup mounts for work dir and home dir, if needed
    homedir = os.path.expanduser("~")
    docker_opts += [
        "-B", "{}:{}{}".format(ABSROOTDIR, ABSROOTDIR, ""), # ":ro" if orig_rootdir else ""),
        # hides /home/user/.local, which if exposed, can confuse jupyter and ipython
        "-B", "{}:{}/.local".format(docker_local, homedir),
        # mount session info directory (needed to serve e.g. js9prefs.js)
        "-B", "{}:{}".format(session_info_dir, LOCAL_SESSION_DIR),
        "-B", "{}:{}".format(session_info_dir, SHADOW_SESSION_DIR),
        # mount a writeable tmp dir for the js9 install -- needed by js9helper
        "-B", "{}:/.radiopadre/venv/js9-www/tmp".format(js9_tmp),
    ]
    if config.CONTAINER_DEV:
        if os.path.isdir(config.CLIENT_INSTALL_PATH):
            docker_opts += ["-B", "{}:/radiopadre-client".format(config.CLIENT_INSTALL_PATH)]
        if os.path.isdir(config.SERVER_INSTALL_PATH):
            docker_opts += ["-B", "{}:/radiopadre".format(config.SERVER_INSTALL_PATH)]
    if not config.CONTAINER_DEBUG:
        command = [singularity, "instance.start"] + docker_opts + \
                  [singularity_image, container_name]
        message("running {}".format(" ".join(map(str,command))))
        subprocess.call(command)
        docker_opts = [singularity, "exec", "instance://{}".format(container_name)]
    else:
        docker_opts = [singularity, "exec" ] + docker_opts + [singularity_image]
    container_ports = selected_ports

    # build up command-line arguments
    docker_opts += _collect_runscript_arguments(container_ports + userside_ports)

    if notebook_path:
        docker_opts.append(notebook_path)

    _run_container(container_name, docker_opts, jupyter_port=selected_ports[0], browser_urls=browser_urls,
                   singularity=True)


    if config.REMOTE_MODE_PORTS:
        if config.VERBOSE:
            message("sleeping")
        while True:
            time.sleep(1000000)
    else:
        try:
            while True:
                input("Use Ctrl+C to kill the container session")
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
                subprocess.call([singularity, "instance.stop", singularity_image, container_name], stdout=DEVNULL)
            sys.exit(status)


def kill_container(name):
    singularity_image = get_singularity_image(config.DOCKER_IMAGE)
    shell(f"{singularity} instance.stop {singularity_image} {name}")
