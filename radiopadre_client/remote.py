import os, sys, subprocess, tempfile, re, time


from . import config

from .utils import DEVNULL, message, bye, find_unused_port, Poller
from .config import AUTOINSTALL_VERSION, AUTOINSTALL_PATH, AUTOINSTALL_REPO, AUTOINSTALL_BRANCH, AUTOINSTALL_CLIENT_VENV, REMOTE_PATH, REMOTE_HOST
from .notebooks import default_notebook_code


# Find remote radiopadre script
def run_remote_session(command, copy_initial_notebook, notebook_path, extra_arguments, options):

    SSH_MUX_OPTS = "-o ControlPath=/tmp/ssh_mux_radiopadre_%C -o ControlMaster=auto -o ControlPersist=1h".split()

    SCP_OPTS = ["scp"] + SSH_MUX_OPTS
    SSH_OPTS = ["ssh", "-tt"] + SSH_MUX_OPTS + [REMOTE_HOST]
    # SSH_OPTS = ["ssh"] + SSH_MUX_OPTS + [host]

    # master ssh connection, to be closed when we exit
    if options.verbose:
        message("Opening initial master connection to {} {}. You may be prompted for your password.".format(REMOTE_HOST,
                                                                                                            " ".join(
                                                                                                                SSH_OPTS)))
    else:
        message("Opening initial master connection to {}. You may be prompted for your password.".format(REMOTE_HOST))
    ssh_master = subprocess.check_call(SSH_OPTS + ["exit"], stderr=DEVNULL)


    # raw_input("Continue?")

    def help_yourself(problem, suggestion=None):
        """
        Prints a "help yourself" message and exits
        """
        message("{}".format(problem))
        message(f"Please ssh {REMOTE_HOST} and sort it out yourself, then rerun this script")
        if suggestion:
            message(f"({suggestion})")
        sys.exit(1)

    def ssh_remote(command, fail_retcode=None, stderr=DEVNULL):
        """Runs command on remote host. Returns its output if the exit status is 0, or None if the exit status matches fail_retcode.

        Any other non-zero exit status (or any other error) will result in an exception.
        """
        try:
            return subprocess.check_output(SSH_OPTS + [command], stderr=stderr)
        except subprocess.CalledProcessError as exc:
            if exc.returncode == fail_retcode:
                return None
            message(f"ssh {command} failed with exit code {exc.returncode}")
            raise

    def ssh_remote_v(command, fail_retcode=None):
        return ssh_remote(command, fail_retcode, stderr=sys.stderr)

    def ssh_remote_interactive(command, fail_retcode=None, stderr=DEVNULL):
        """Runs command on remote host. Returns its output if the exit status is 0, or None if the exit status matches fail_retcode.

        Any other non-zero exit status (or any other error) will result in an exception.
        """
        try:
            return subprocess.check_call(SSH_OPTS + [command], stderr=stderr)
        except subprocess.CalledProcessError as exc:
            if exc.returncode == fail_retcode:
                return None
            message(f"ssh {command} failed with exit code {exc.returncode}")
            raise

    def scp_to_remote(path, remote_path):
        return subprocess.check_output(SCP_OPTS + [path, "{}:{}".format(REMOTE_HOST, remote_path)])

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
        return (ssh_remote("which " + command, fail_retcode=1, stderr=DEVNULL) or "").strip()


    # Check for various remote bits

    if options.verbose:
        message(f"Checking installation on {REMOTE_HOST}.")
    has_venv = check_remote_command("virtualenv") and check_remote_command("pip")
    has_git = check_remote_command("git")
    has_singularity = check_remote_command("singularity")
    has_docker = check_remote_command("docker")

    ## Look for remote launch script

    padre_exec0 = f"{REMOTE_PATH}/bin/run-radiopadre" if REMOTE_PATH else "run-radiopadre" # path to remote padre executable
    padre_exec = None

    # look for remote radiopadre installation in container-dev mode

    if options.container_dev:
        if not check_remote_file("~/radiopadre", "-d"):
            message("no remote installation detected in ~/radiopadre: can't run --container-dev mode")
            sys.exit(1)

    # does the remote have a server virtual environment configured? Client better go through the same
    if options.virtual_env:
        ## Check for remote virtualenv

        SERVER_VENV = remote_client_venv = "~/.radiopadre/venv"
        if not check_remote_file(SERVER_VENV, "-d"):
            help_yourself(f"radiopadre: no virtual environment detected in {REMOTE_HOST}:{SERVER_VENV}, can't use --virtual-env mode.",
                          "Suggest reinstalling radiopadre manually")
        if not check_remote_file(f"{SERVER_VENV}/complete", "-f"):
            help_yourself(f"radiopadre: remote virtual environment {REMOTE_HOST}:{SERVER_VENV} appears incomplete.",
                          "Suggest reinstalling radiopadre manually")

        message(f"Detected server virtualenv {REMOTE_HOST}:{SERVER_VENV}, will use it for client script too")

        if check_remote_command(f"source {remote_client_venv}/bin/activate && which {padre_exec0}"):
            padre_exec = f"source {remote_client_venv}/bin/activate && {padre_exec0}"

    else:
        remote_client_venv = check_remote_file(f"{AUTOINSTALL_CLIENT_VENV}/bin/activate", "-f") and AUTOINSTALL_CLIENT_VENV

        # check that remote client venv is functional
        if remote_client_venv:
            message(f"Detected existing client virtualenv {REMOTE_HOST}:{remote_client_venv}")
            if ssh_remote(f"source {remote_client_venv}/bin/activate && which {padre_exec0}", fail_retcode=1):
                padre_exec = f"source {remote_client_venv}/bin/activate && {padre_exec0}"
        # else check if the run script is directly available
        else:
            padre_exec = check_remote_command(padre_exec0)
            pe = padre_exec or "not found"
            message(f"No client virtualenv {REMOTE_HOST}:{AUTOINSTALL_CLIENT_VENV}, run script is {padre_exec}")

    if padre_exec:
        message(f"using remote script {padre_exec}")
    else:
        message(f"No {padre_exec0} script found on {REMOTE_HOST}")
        if not options.auto_init:
            bye(f"no radiopadre-client installation detected on {REMOTE_HOST}. Try --auto-init?")

        message("Trying to --auto-init an installation for you")

        # try to auto-init a virtual environment
        if not remote_client_venv and AUTOINSTALL_CLIENT_VENV:
            message(f"Creating virtualenv {REMOTE_HOST}:{AUTOINSTALL_CLIENT_VENV}")
            ssh_remote_v(f"virtualenv -p python3 {AUTOINSTALL_CLIENT_VENV}")
            remote_client_venv = AUTOINSTALL_CLIENT_VENV

        # try to auto-init an installation
        if config.AUTOINSTALL_PATH and check_remote_file(config.AUTOINSTALL_PATH, "-d"):
            message("I will try to pip install -e {}:{}".format(REMOTE_HOST, config.AUTOINSTALL_PATH))
            install_path = config.AUTOINSTALL_PATH
            ssh_remote_v(f"source {remote_client_venv}/bin/activate && pip install -e {install_path}")

        elif config.AUTOINSTALL_REPO:
            install_path = REMOTE_PATH or "~/radiopadre-client"
            message("I could try to install {}:{} from {}".format(REMOTE_HOST, install_path, config.AUTOINSTALL_REPO))

            if not remote_client_venv:
                bye("However, it looks like AUTOINSTALL_CLIENT_VENV is not configured!")

            if not has_git:
                help_yourself(f"However, I don't see git installed on {REMOTE_HOST}",
                              f"Try 'sudo apt install git' on {REMOTE_HOST}")

            if check_remote_file(install_path, "-d"):
                message(f"However, the directory {REMOTE_HOST}:{install_path} already exists, so I'd rather not!")
                help_yourself(f"This may be a sign of a broken radiopadre installation on {REMOTE_HOST},",
                              f"For example, remove {REMOTE_HOST}:{install_path} to bootstrap from scratch.")

            # try git clone
            cmd = f"git clone -b {AUTOINSTALL_BRANCH} {AUTOINSTALL_REPO} {install_path}"
            message(f"Running {cmd} on {REMOTE_HOST}")
            ssh_remote_interactive(cmd, stderr=sys.stderr)

            # now pip install
            message(f"Doing pip install -e into {remote_client_venv}")
            ssh_remote_v(f"source {remote_client_venv}/bin/activate && pip install -e {install_path}")

        # else need to use pip
        elif AUTOINSTALL_VERSION:
            message(f"Doing pip install {AUTOINSTALL_VERSION} into {remote_client_venv}")
            ssh_remote(f"source {remote_client_venv}/bin/activate && pip install {AUTOINSTALL_VERSION}")

        else:
            bye("Neither an AUTOINSTALL_VERSION nor an AUTOINSTALL_REPO is configured, can't use --auto-init")

        # sanity check
        if ssh_remote(f"source {remote_client_venv}/bin/activate && which {padre_exec0}", fail_retcode=1):
            padre_exec = f"source {remote_client_venv}/bin/activate && {padre_exec0}"
        else:
            help_yourself(f"Something went wrong during installation, I still don't see the run-radiopadre script")

        message("Success!")

    # do we need an update of the client install?
    if options.update and config.AUTOINSTALL_REPO:
        install_path = REMOTE_PATH or "~/radiopadre-client"
        if check_remote_file(f"{install_path}/.git", "-d"):
            message(f"--update specified, will attempt a git pull in {REMOTE_HOST}:{install_path}")
            if has_git:
                ssh_remote_interactive(f"cd {install_path} && git pull")
            else:
                message("No git installed on remote, ignoring --update flag for the client")

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

    # run remote in container mode
    if not options.virtual_env:
        if options.singularity and not has_singularity:
            help_yourself("{} doesn't appear to have Singularity installed.".format(REMOTE_HOST),
                          "Ask the admin to install Docker on {}".format(REMOTE_HOST))
        if options.docker:
            has_singularity = False
            if not has_docker:
                help_yourself("{} doesn't appear to have Docker installed.".format(REMOTE_HOST),
                              "Ask the admin to install Docker on {} and to add you to the docker group.".format(
                                  REMOTE_HOST))

        if has_singularity:
            padre_exec += " --singularity"
            message(f"Using remote {has_singularity} to run in container mode")
        elif has_docker:
            padre_exec += " --docker"
            message(f"Using remote {has_docker} to run in container mode")
        else:
            help_yourself("{} doesn't appear to have Singularity or Docker installed.".format(REMOTE_HOST),
                          "Ask the admin to install either on {}. Otherwise, use --virtual-env mode?".format(REMOTE_HOST))

        if options.container_dev:
            assert (padre_exec is not None)
            padre_exec += " --container-dev"
            message(f"Running remote in container-dev mode with image {options.docker_image}")
        else:
            message(f"Running remote in container mode with image {options.docker_image}")

        if options.update:
            padre_exec += " --update --docker-image " + options.docker_image

    # else run remote in virtual-env mode (deprecated)
    else:
        padre_exec += " --virtual-env"


    # allocate 5 suggested ports (in resume mode, this will be overridden by the session settings)
    starting_port = 10000 + os.getuid() * 3
    ports = []
    for _ in range(5):
        starting_port = find_unused_port(starting_port + 1, 10000)
        ports.append(starting_port)

    if options.auto_init:
        padre_exec += " --auto-init"
    if options.venv_reinstall:
        padre_exec += " --venv-reinstall"
    if options.venv_no_casacore:
        padre_exec += " --venv-no-casacore"
    if options.venv_no_js9:
        padre_exec += " --venv-no-js9"
    if options.verbose:
        padre_exec += " --verbose"

    padre_exec += "  --remote {} {} {}".format(":".join(map(str, ports)),
                                               command if command is not "load" else notebook_path,
                                               " ".join(extra_arguments))

    # start ssh subprocess to launch notebook
    args = list(SSH_OPTS) + [padre_exec]

    message("running {}".format(" ".join(args)))
    ssh = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    poller = Poller()
    poller.register_process(ssh, REMOTE_HOST, REMOTE_HOST + " stderr")
    if not options.virtual_env:
        poller.register_file(sys.stdin, "stdin")

    container_name = None
    urls = []
    remote_running = False
    status = 0

    try:
        while remote_running is not None and poller.fdlabels:
            fdlist = poller.poll()
            for fname, fobj in fdlist:
                try:
                    line = fobj.readline()
                except EOFError:
                    line = ''
                if fobj is sys.stdin and line and line[0].upper() == "Q":
                    sys.exit(0)
                # break out if ssh closes
                if not line:
                    poller.unregister_file(fobj)
                    if ssh.stdout not in poller and ssh.stdin not in poller:
                        message(f"ssh process to {REMOTE_HOST} has exited")
                        remote_running = None
                        break
                    continue
                line = line.decode().rstrip()
                # print remote output
                print_output = False
                if fobj is ssh.stderr:
                    print_output = not line.startswith("Shared connection to")
                else:
                    print_output = not line.startswith("radiopadre:") or command != 'load'
                if options.verbose or print_output:
                    print("\r{}: {}\r".format(fname, line))
                if not line:
                    continue
                # if remote is not yet started, check output
                if not remote_running:
                    # check for session ID
                    match = re.match(".*Session ID/notebook token is '([0-9a-f]+)'", line)
                    if match:
                        session_id = match.group(1)
                        continue
                    # check for notebook port, and launch second ssh when we have it
                    match = re.match(".*Selected ports: ([\d]+):([\d]+):([\d]+):([\d]+):([\d]+)" +
                                     "\s+([\d]+):([\d]+):([\d]+):([\d]+):([\d]+)[\s]*$", line)
                    if match:
                        ports = list(map(int, match.groups()))
                        remote_jupyter_port, remote_js9helper_port, remote_http_port, remote_carta_port, \
                        remote_carta_ws_port = remote_ports = ports[:5]
                        local_ports = ports[5:]
                        if options.verbose:
                            message("Detected ports {}:{}:{}:{}:{} -> {}:{}:{}:{}:{}".format(*ports))
                        ssh2_args = ["ssh"] + SSH_MUX_OPTS + ["-O", "forward", REMOTE_HOST]
                        for loc, rem in zip(local_ports, remote_ports):
                            ssh2_args += ["-L", "localhost:{}:localhost:{}".format(loc, rem)]
                        # tell mux process to forward the ports
                        if options.verbose:
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
                        for url in urls:
                            # open browser if needed
                            if not options.no_browser:
                                message("running {} {}\r".format(options.browser_command, url))
                                message(
                                    "  if this fails, specify a correct browser invocation command with --browser-command and rerun,")
                                message("  or else browse to the URL given above (\"Browse to URL:\") yourself.")
                                try:
                                    subprocess.call([options.browser_command, url], stdout=DEVNULL)
                                except OSError as exc:
                                    if exc.errno == 2:
                                        message("{} not found".format(options.browser_command))
                                    else:
                                        raise
                            else:
                                message("-n/--no-browser given, not opening a browser for you\r")
                                message("Please browse to: {}\n".format(url))
                        message("The remote radiopadre session is now fully up")
                        if options.virtual_env:
                            message("Press Ctrl+C to kill the remote session")
                        else:
                            message("Press Q<Enter> to detach from remote session, or Ctrl+C to kill it")

    except SystemExit as exc:
        message(f"SystemExit: {exc.code}")
        status = exc.code

    except KeyboardInterrupt:
        message("Ctrl+C caught")
        status = 1

    if status and not options.virtual_env and container_name:
        message(f"killing remote container {container_name}")
        try:
            ssh_remote("docker kill {}".format(container_name))
        except subprocess.CalledProcessError as exc:
            message(exc.output)

    ssh.kill()

    return status