import os, sys, subprocess, re, time

from . import config
from .default_config import DefaultConfig

from .utils import DEVNULL, message, bye, find_unused_port, Poller, run_browser


# Find remote radiopadre script
def run_remote_session(command, copy_initial_notebook, notebook_path, extra_arguments):

    SSH_MUX_OPTS = "-o ControlPath=/tmp/ssh_mux_radiopadre_%C -o ControlMaster=auto -o ControlPersist=1h".split()

    SCP_OPTS = ["scp"] + SSH_MUX_OPTS
    SSH_OPTS = ["ssh", "-tt"] + SSH_MUX_OPTS + [config.REMOTE_HOST]
    # SSH_OPTS = ["ssh"] + SSH_MUX_OPTS + [host]

    # master ssh connection, to be closed when we exit
    if config.VERBOSE:
        message("Opening initial master connection to {} {}. You may be prompted for your password.".format(config.REMOTE_HOST,
                                                                                                            " ".join(
                                                                                                                SSH_OPTS)))
    else:
        message("Opening initial master connection to {}. You may be prompted for your password.".format(config.REMOTE_HOST))
    ssh_master = subprocess.check_call(SSH_OPTS + ["exit"], stderr=DEVNULL)


    # raw_input("Continue?")

    def help_yourself(problem, suggestion=None):
        """
        Prints a "help yourself" message and exits
        """
        message("{}".format(problem))
        message(f"Please ssh {config.REMOTE_HOST} and sort it out yourself, then rerun this script")
        if suggestion:
            message(f"({suggestion})")
        sys.exit(1)

    def ssh_remote(command, fail_retcode=None, stderr=DEVNULL):
        """Runs command on remote host. Returns its output if the exit status is 0, or None if the exit status matches fail_retcode.

        Any other non-zero exit status (or any other error) will result in an exception.
        """
        try:
            return subprocess.check_output(SSH_OPTS + [command], stderr=stderr).decode()
        except subprocess.CalledProcessError as exc:
            if exc.returncode == fail_retcode:
                return None
            message(f"ssh {command} failed with exit code {exc.returncode}")
            raise

    def ssh_remote_v(command, fail_retcode=None):
        return ssh_remote(command, fail_retcode, stderr=sys.stderr)

    def ssh_remote_interactive(command, fail_retcode=None):
        """Runs command on remote host. Returns the exit status if 0, or None if the exit status matches fail_retcode.

        Any other non-zero exit status (or any other error) will result in an exception.
        """
        try:
            return subprocess.check_call(SSH_OPTS + [command])
        except subprocess.CalledProcessError as exc:
            if exc.returncode == fail_retcode:
                return None
            message(f"ssh {command} failed with exit code {exc.returncode}")
            raise

    def scp_to_remote(path, remote_path):
        return subprocess.check_output(SCP_OPTS + [path, "{}:{}".format(config.REMOTE_HOST, remote_path)])

    def check_remote_file(remote_file, test="-x"):
        """
        Checks that a remote file exists. 'test' is specified bash-style, e.g. "-x" for executable.
        Can also use -f and -f, for example.
        Returns True or False, or raises an exception on other errors.
        """
        return ssh_remote("if [ {} {} ]; then exit 0; else exit 199; fi".format(test, remote_file),
                          fail_retcode=199, stderr=DEVNULL) is not None

    def check_remote_command(command):
        """
        Checks that remote host has a particular command available (by running 'which' on the remote).
        Returns True or False, or raises an exception on other errors.
        """
        if config.SKIP_CHECKS:
            return command
        return (ssh_remote("which " + command, fail_retcode=1, stderr=DEVNULL) or "").strip()

    # --update or --auto-init disables --skip-checks
    if config.SKIP_CHECKS:
        if config.UPDATE:
            message("Noe that --update implies --no-skip-checks")
            config.SKIP_CHECKS = False
        elif config.AUTO_INIT:
            message("Note that --auto-init implies --no-skip-checks")
            config.SKIP_CHECKS = False

    # propagate our config to command-line arguments
    remote_config = config.get_config_dict()
    remote_config['BROWSER'] = 'None'
    remote_config['SKIP_CHECKS'] = False

    # Check for various remote bits
    if config.VERBOSE and not config.SKIP_CHECKS:
        message(f"Checking installation on {config.REMOTE_HOST}.")

    has_git = check_remote_command("git")

    USE_VENV = has_singularity = has_docker = None

    for backend in config.BACKEND:
        remote_config["BACKEND"] = backend
        if backend == "venv" and check_remote_command("virtualenv") and check_remote_command("pip"):
            USE_VENV = True
            break
        elif backend == "docker":
            has_docker = check_remote_command("docker")
            if has_docker:
                break
        elif backend == "singularity":
            has_singularity = check_remote_command("singularity")
            if has_singularity:
                break
        message(f"The '{backend}' back-end is not available on {config.REMOTE_HOST}, skipping.")
    else:
        bye(f"None of the specified back-ends are available on {config.REMOTE_HOST}.")

    if remote_config["BACKEND"] != "docker":
        config.CONTAINER_PERSIST = config.CONTAINER_DEBUG = False

    ## Look for remote launch script
    # (a) under VIRTUAL_ENV/bin
    # (b) with which

    runscript0 = "run-radiopadre"

    if config.SKIP_CHECKS:
        runscript=f"rs={config.RADIOPADRE_VENV}/bin/run-radiopadre; if [ ! -x $rs ]; then " \
                  f"source {config.RADIOPADRE_VENV}/bin/activate; rs=run-radiopadre; fi; $rs "
    else:
        runscript = None

        # (a) look inside venv
        if runscript is None and config.RADIOPADRE_VENV:
            if "~" in config.RADIOPADRE_VENV:
                config.RADIOPADRE_VENV = ssh_remote(f"echo {config.RADIOPADRE_VENV}").strip()  # expand "~" on remote
            if check_remote_file(f"{config.RADIOPADRE_VENV}/bin/activate", "-f"):
                if ssh_remote(f"source {config.RADIOPADRE_VENV}/bin/activate && which {runscript0}", fail_retcode=1):
                    runscript = f"source {config.RADIOPADRE_VENV}/bin/activate && {runscript0}"
                    message(f"Using remote client script within {config.RADIOPADRE_VENV}")
                else:
                    message(f"Remote venv {config.RADIOPADRE_VENV} exists, but does not contain a radiopadre-client installation.")
            else:
                message(f"No remote venv found at {config.RADIOPADRE_VENV}")

        # (b) just try `which` directly
        if runscript is None:
            runscript = check_remote_command(runscript0)
            if runscript:
                message(f"Using remote client script at {runscript}")
            else:
                message(f"No remote client script {runscript0} found")
                runscript = None

    # does the remote have a server virtual environment configured?
    # if USE_VENV:
    #     if "~" in config.RADIOPADRE_VENV:
    #         config.RADIOPADRE_VENV = ssh_remote(f"echo {config.RADIOPADRE_VENV}").strip()  # expand "~" on remote
    #
    #     if not check_remote_file(f"{config.RADIOPADRE_VENV}/bin/activate", "-f"):
    #         help_yourself(f"radiopadre: no virtual environment detected in {config.REMOTE_HOST}:{config.RADIOPADRE_VENV}, can't use --virtual-env mode.",
    #                       f"Suggest reinstalling radiopadre on {config.REMOTE_HOST} manually.")
    #     if not check_remote_file(f"{config.RADIOPADRE_VENV}/{config.COMPLETE_INSTALL_COOKIE}", "-f"):
    #         help_yourself(f"radiopadre: remote virtual environment {config.REMOTE_HOST}:{config.RADIOPADRE_VENV} appears incomplete.",
    #                       f"Suggest reinstalling radiopadre on {config.REMOTE_HOST} manually.")
    #
    #     message(f"Detected server virtualenv {config.REMOTE_HOST}:{config.RADIOPADRE_VENV}")

    if not USE_VENV and config.CONTAINER_DEV:
        if not config.SKIP_CHECKS and not check_remote_file(config.SERVER_INSTALL_PATH, "-d"):
            message(f"no remote installation detected in {config.SERVER_INSTALL_PATH}: can't run --container-dev mode")
            sys.exit(1)

    if not runscript:
        message(f"No {runscript0} script found on {config.REMOTE_HOST}")
        if not config.AUTO_INIT:
            bye(f"Try --auto-init?")
        if not config.RADIOPADRE_VENV:
            bye(f"Can't do --auto-init because --virtual-env is not set")

        message("Trying to --auto-init an installation for you")

        # try to auto-init a virtual environment
        if not check_remote_file(f"{config.RADIOPADRE_VENV}/bin/activate", "-f"):
            message(f"Creating virtualenv {config.REMOTE_HOST}:{config.RADIOPADRE_VENV}")
            ssh_remote_v(f"virtualenv -p python3 {config.RADIOPADRE_VENV}")
        else:
            message(f"Installing into existing virtualenv {config.REMOTE_HOST}:{config.RADIOPADRE_VENV}")

        # try to auto-init an installation
        if config.CLIENT_INSTALL_PATH and check_remote_file(config.CLIENT_INSTALL_PATH, "-d"):
            message("I will try to pip install -e {}:{}".format(config.REMOTE_HOST, config.CLIENT_INSTALL_PATH))
            install_path = config.CLIENT_INSTALL_PATH
            ssh_remote_v(f"source {config.RADIOPADRE_VENV}/bin/activate && pip install -e {install_path}")

        elif config.CLIENT_INSTALL_REPO:
            install_path = config.CLIENT_INSTALL_PATH or "~/radiopadre-client"
            message("I could try to install {}:{} from {}".format(config.REMOTE_HOST, install_path, config.CLIENT_INSTALL_REPO))

            if not has_git:
                help_yourself(f"However, I don't see git installed on {config.REMOTE_HOST}",
                              f"Try 'sudo apt install git' on {config.REMOTE_HOST}")

            if check_remote_file(install_path, "-d"):
                message(f"However, the directory {config.REMOTE_HOST}:{install_path} already exists, so I'd rather not!")
                help_yourself(f"This may be a sign of a broken radiopadre installation on {config.REMOTE_HOST},",
                              f"For example, remove {config.REMOTE_HOST}:{install_path} to bootstrap from scratch.")

            # try git clone
            cmd = f"git clone -b {config.CLIENT_INSTALL_BRANCH} {config.CLIENT_INSTALL_REPO} {install_path}"
            message(f"Running {cmd} on {config.REMOTE_HOST}")
            ssh_remote_interactive(cmd)

            # now pip install
            message(f"Doing pip install -e into {config.RADIOPADRE_VENV}")
            ssh_remote_v(f"source {config.RADIOPADRE_VENV}/bin/activate && pip install -e {install_path}")

        # else need to use pip
        elif config.CLIENT_INSTALL_PIP:
            message(f"Doing pip install {config.CLIENT_INSTALL_PIP} into {config.RADIOPADRE_VENV}")
            ssh_remote(f"source {config.RADIOPADRE_VENV}/bin/activate && pip install {config.CLIENT_INSTALL_PIP}")

        else:
            bye("To use auto-init, set CLIENT_INSTALL_PATH and/or CLIENT_INSTALL_PIP and/or CLIENT_INSTALL_REPO")

        # sanity check
        if ssh_remote(f"source {config.RADIOPADRE_VENV}/bin/activate && which {runscript0}", fail_retcode=1):
            runscript = f"source {config.RADIOPADRE_VENV}/bin/activate && {runscript0}"
        else:
            help_yourself(f"Something went wrong during installation, I still don't see the {runscript0} script")

        message("Success!")

    # do we need an update of the client install?
    if config.UPDATE:
        install_path = config.CLIENT_INSTALL_PATH or "~/radiopadre-client"
        if config.CLIENT_INSTALL_REPO and check_remote_file(f"{install_path}/.git", "-d"):
            message(f"--update specified, will attempt a git pull in {config.REMOTE_HOST}:{install_path}")
            if has_git:
                ssh_remote_interactive(f"cd {install_path} && git fetch origin && " +
                                       f"git checkout {config.CLIENT_INSTALL_BRANCH} && git merge FETCH_HEAD && " +
                                       f"source {config.RADIOPADRE_VENV}/bin/activate && pip3 install -e ."
                                       )
            else:
                message("No git installed on remote, ignoring --update flag for the client")
        elif config.CLIENT_INSTALL_PIP:
            message(f"Doing pip install -U {config.CLIENT_INSTALL_PIP} into {config.RADIOPADRE_VENV}")
            ssh_remote(f"source {config.RADIOPADRE_VENV}/bin/activate && pip3 install -U {config.CLIENT_INSTALL_PIP}")

    # copy notebook to remote
    if copy_initial_notebook:
        if not os.path.exists(copy_initial_notebook):
            bye("{} doesn't exist".format(copy_initial_notebook))
        if check_remote_file(notebook_path or ".", "-d"):
            nbpath = "{}/{}".format(notebook_path or ".", copy_initial_notebook)
            if check_remote_file(nbpath, "-f"):
                message(f"remote notebook {nbpath} exists, will not copy over")
            else:
                message(f"remote notebook {nbpath} doesn't exist, will copy over")
                scp_to_remote(copy_initial_notebook, notebook_path)
            notebook_path = nbpath

    # allocate 5 suggested ports (in resume mode, this will be overridden by the session settings)
    starting_port = 10000 + os.getuid() * 3
    ports = []
    for _ in range(5):
        starting_port = find_unused_port(starting_port + 1, 10000)
        ports.append(starting_port)

    remote_config["remote"] = ":".join(map(str, ports))

    # turn the remote_config dict into a command line
    runscript += " " + " ".join(config.get_options_list(remote_config, quote=True))

    runscript += " '{}' {}".format(command if command is not "load" else notebook_path,
                                   " ".join(extra_arguments))

    # start ssh subprocess to launch notebook
    args = list(SSH_OPTS) + ["shopt -s huponexit && "+
                             runscript]

    if config.VERBOSE:
        message("running {}".format(" ".join(args)))
    else:
        message(f"running client on {config.REMOTE_HOST}")
    ssh = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    poller = Poller()
    poller.register_process(ssh, config.REMOTE_HOST, config.REMOTE_HOST + " stderr")
    if not USE_VENV:
        poller.register_file(sys.stdin, "stdin")

    container_name = None
    urls = []
    remote_running = False
    status = 0
    child_processes = []

    try:
        while remote_running is not None and poller.fdlabels:
            fdlist = poller.poll()
            for fname, fobj in fdlist:
                try:
                    line = fobj.readline()
                except EOFError:
                    line = b''
                if fobj is sys.stdin and line and line[0].upper() == b'Q' and config.CONTAINER_PERSIST:
                    sys.exit(0)
                # break out if ssh closes
                if not line:
                    poller.unregister_file(fobj)
                    if ssh.stdout not in poller and ssh.stdin not in poller:
                        message(f"ssh process to {config.REMOTE_HOST} has exited")
                        remote_running = None
                        break
                    continue
                line = (line.decode() if type(line) is bytes else line).rstrip()
                # print remote output
                print_output = False
                if fobj is ssh.stderr:
                    print_output = not line.startswith("Shared connection to")
                else:
                    print_output = not line.startswith("radiopadre:") or command != 'load'
                if config.VERBOSE or print_output:
                    print("\r{}: {}\r".format(fname, line))
                if not line:
                    continue
                # if remote is not yet started, check output
                if not remote_running:
                    # check for session ID
                    match = re.match(".*Session ID/notebook token is '([0-9a-f]+)'", line)
                    if match:
                        config.SESSION_ID = match.group(1)
                        continue
                    # check for notebook port, and launch second ssh when we have it
                    re_ports = ":".join(["([\\d]+)"]*10)   # form up regex for ddd:ddd:...
                    match = re.match(f".*Selected ports: {re_ports}[\s]*$", line)
                    if match:
                        ports = list(map(int, match.groups()))
                        remote_ports = ports[:5]
                        local_ports = ports[5:]
                        if config.VERBOSE:
                            message("Detected ports {}:{}:{}:{}:{} -> {}:{}:{}:{}:{}".format(*ports))
                        ssh2_args = ["ssh"] + SSH_MUX_OPTS + ["-O", "forward", config.REMOTE_HOST]
                        for loc, rem in zip(local_ports, remote_ports):
                            ssh2_args += ["-L", "localhost:{}:localhost:{}".format(loc, rem)]
                        # tell mux process to forward the ports
                        if config.VERBOSE:
                            message("sending forward request to ssh mux process".format(ssh2_args))
                        subprocess.call(ssh2_args)
                        continue

                    # check for launch URL
                    match = re.match(".*Browse to URL: ([^\s]+)", line)
                    if match:
                        urls.append(match.group(1))
                        continue

                    # check for container name
                    match = re.match(".*Container name: ([^\s]+)", line)
                    if match:
                        container_name = match.group(1)
                        continue

                    if "Jupyter Notebook is running" in line:
                        remote_running = True
                        time.sleep(1)
                        child_processes += run_browser(*urls)
                        message("The remote radiopadre session is now fully up")
                        if USE_VENV or not config.CONTAINER_PERSIST:
                            message("Press Ctrl+C to kill the remote session")
                        else:
                            message("Press Q<Enter> to detach from remote session, or Ctrl+C to kill it")

    except SystemExit as exc:
        message(f"SystemExit: {exc.code}")
        status = exc.code

    except KeyboardInterrupt:
        message("Ctrl+C caught")
        status = 1

    if status and not USE_VENV and container_name:
        message(f"killing remote container {container_name}")
        try:
            if has_docker:
                ssh_remote(f"{has_docker} kill {container_name}")
            elif has_singularity:
                from .backends.singularity import get_singularity_image
                singularity_image = get_singularity_image(config.DOCKER_IMAGE)
                ssh_remote(f"{has_singularity} instance.stop {singularity_image} {container_name}")
        except subprocess.CalledProcessError as exc:
            message(exc.output.decode())

    ssh.kill()
    for proc in child_processes:
        proc.terminate()
        proc.wait()

    return status