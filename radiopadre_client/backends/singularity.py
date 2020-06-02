import os, subprocess, sys, time, re, calendar
import datetime

from iglesia.utils import message, warning, error, bye, make_dir, make_radiopadre_dir, shell, DEVNULL, ff, INPUT, check_output
from radiopadre_client import config

singularity = None
has_docker = None

from . import docker
from .docker import get_session_info_dir, save_session_info, _run_container, _init_session_dir, _collect_runscript_arguments
import iglesia

def init(binary, docker_binary=None):
    global singularity, has_docker
    singularity = binary
    _init_session_dir()
    if docker_binary:
        # check that we actually have docker permissions
        if check_output(docker_binary + " ps") is None:
            message("can't connect to docker daemon, will proceed without docker")
            has_docker = None
        else:
            has_docker = docker_binary
            docker.init(docker_binary)

def read_session_info(container_name):
    raise NotImplementedError("not available in singularity mode")

def list_sessions():
    return {}

def identify_session(session_dict, arg):
    raise NotImplementedError("not available in singularity mode")

def kill_sessions(session_dict, session_ids):
    raise NotImplementedError("not available in singularity mode")

def get_singularity_image(docker_image):
    dir = config.SINGULARITY_IMAGE_DIR or os.environ.get('RADIOPADRE_SINGULARITY_IMAGE_DIR') or iglesia.RADIOPADRE_DIR
    return "{}/{}.singularity.img".format(dir, docker_image.replace("/", "_"))

def update_installation(rebuild=False, docker_pull=True):
    global docker_image
    global singularity_image
    docker_image = config.DOCKER_IMAGE
    singularity_image = os.path.expanduser(get_singularity_image(docker_image))
    # this will be True if we need to build the image
    build_image = False

    # clearly true if no image
    if not os.path.exists(singularity_image):
        if config.SINGULARITY_AUTO_BUILD:
            message(ff("Singularity image {singularity_image} does not exist"))
            build_image = True
        else:
            error(ff("Singularity image {singularity_image} does not exist, and auto-build is disabled"))
            bye(ff("Re-run with --singularity-auto-build to proceed"))
    # also true if rebuild forced by flags or config or command line
    elif rebuild or config.SINGULARITY_REBUILD:
        config.SINGULARITY_AUTO_BUILD = build_image = True
        message(ff("--singularity-rebuild specified, removing singularity image {singularity_image}"))

    # pull down docker image first
    if has_docker and docker_pull:
        message("Checking docker image (from which our singularity image is built)")
        docker.update_installation(enable_pull=True)
    # if we're not forced to build yet, check for an update
    if config.UPDATE and not build_image:
        if has_docker:
            # check timestamp of docker image
            docker_image_time = None
            output = check_output(ff("{has_docker} image inspect {docker_image} -f '{{{{ .Created }}}}'")).strip()
            message(ff("  docker image timestamp is {output}"))
            # in Python 3.7 we have datetime.fromisoformat(date_string), but for now we muddle:
            match = output and re.match("(^.*)[.](\d+)Z", output)
            if match:
                try:
                    docker_image_time = calendar.timegm(time.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S"))
                    docker_image_time = datetime.datetime.utcfromtimestamp(docker_image_time)
                except ValueError:
                    pass
            sing_image_time = datetime.datetime.utcfromtimestamp(os.path.getmtime(singularity_image))
            message("  singularity image timestamp is {}".format(sing_image_time.isoformat()))
            if docker_image_time is None:
                warning(ff("can't parse docker image timestamp '{output}', rebuilding {singularity_image} just in case"))
                build_image = True
            elif docker_image_time > sing_image_time:
                warning(ff("rebuilding outdated singularity image {singularity_image}"))
                build_image = True
            else:
                message(ff("singularity image {singularity_image} is up-to-date"))
        else:
            message(ff("--update specified but no docker access, assuming {singularity_image} is up-to-date"))
    # now build if needed
    if build_image:
        warning(ff("Rebuilding singularity image from docker://{docker_image}"))
        warning(ff("  (This may take a few minutes....)"))
        singularity_image_new = singularity_image + ".new.img"
        if os.path.exists(singularity_image_new):
            os.unlink(singularity_image_new)
        cmd = [singularity, "build", singularity_image_new, ff("docker://{docker_image}")]
        message("running " + " ".join(cmd))
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as exc:
            if config.IGNORE_UPDATE_ERRORS:
                if os.path.exists(singularity_image):
                    warning("singularity build failed but --ignore-update-errors is set, proceeding with old image")
                else:
                    error("singularity build failed, --ignore-update-errors is set, but we have no older image")
                    raise
            else:
                raise
        # move old image
        message(ff("Build successful, renaming to {singularity_image}"))
        os.rename(singularity_image_new, singularity_image)
    else:
        message(ff("Using existing radiopadre singularity image {singularity_image}"))

    # not supported with Singularity
    config.CONTAINER_PERSIST = False

    # config.CONTAINER_DEBUG = False


def start_session(container_name, selected_ports, userside_ports, notebook_path, browser_urls):
    from iglesia import ABSROOTDIR, LOCAL_SESSION_DIR, SHADOW_SESSION_DIR
    radiopadre_dir = make_radiopadre_dir()
    docker_local = make_dir(radiopadre_dir + "/.docker-local")
    js9_tmp = make_dir(radiopadre_dir + "/.js9-tmp")
    session_info_dir = get_session_info_dir(container_name)

    # message(ff("Container name: {container_name}"))  # remote script will parse it

    os.environ["RADIOPADRE_CONTAINER_NAME"] = container_name
    os.environ["XDG_RUNTIME_DIR"] = ""
    docker_opts = ["--workdir", ABSROOTDIR]
    # setup mounts for work dir and home dir, if needed
    homedir = os.path.expanduser("~")
    docker_opts += [
        "-B", "{}:{}{}".format(ABSROOTDIR, ABSROOTDIR, ""), # ":ro" if orig_rootdir else ""),
        "-B", "{}/.radiopadre:{}/.radiopadre".format(homedir, homedir),
        # hides /home/user/.local, which if exposed, can confuse jupyter and ipython
        "-B", "{}:{}".format(docker_local, os.path.realpath(os.path.join(homedir, ".local"))),
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
    # if not config.CONTAINER_DEBUG:
    #     command = [singularity, "instance.start"] + docker_opts + \
    #               [singularity_image, container_name]
    #     message("running {}".format(" ".join(map(str, command))))
    #     subprocess.call(command)
    #     docker_opts = [singularity, "exec", "instance://{}".format(container_name)]
    # else:
    #     docker_opts = [singularity, "exec" ] + docker_opts + [singularity_image]
    docker_opts = [singularity, "run" ] + docker_opts + [singularity_image]
    container_ports = selected_ports

    # build up command-line arguments
    docker_opts += _collect_runscript_arguments(container_ports + userside_ports)

    if notebook_path:
        docker_opts.append(notebook_path)

    _run_container(container_name, docker_opts, jupyter_port=selected_ports[0], browser_urls=browser_urls,
                   singularity=True)

    if config.NBCONVERT:
        return

    try:
        while True:
            a = INPUT("Type 'exit' to kill the container session: ")
            if a.lower() == 'exit':
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
            subprocess.call([singularity, "instance.stop", singularity_image, container_name], stdout=DEVNULL)
        sys.exit(status)


def kill_container(name):
    singularity_image = get_singularity_image(config.DOCKER_IMAGE)
    shell(ff("{singularity} instance.stop {singularity_image} {name}"))
