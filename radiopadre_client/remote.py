import os, sys, subprocess, re, time, traceback

from . import config

import iglesia
from iglesia.utils import DEVNULL, message, warning, error, debug, bye, find_unused_port, Poller, ff, INPUT

from radiopadre_client.server import run_browser

# which method to use to dispatch messages from remote. Default is message().
_dispatch_message = {': WARNING: ':warning, ': ERROR: ':error, ': DEBUG:':debug}

# Find remote radiopadre script
def run_remote_session(command, copy_initial_notebook, notebook_path, extra_arguments):

    SSH_MUX_OPTS = "-o ControlPath=/tmp/ssh_mux_radiopadre_%C -o ControlMaster=auto -o ControlPersist=1h".split()

    SCP_OPTS = ["scp"] + SSH_MUX_OPTS
#    SSH_OPTS = ["ssh", "-t"] + SSH_MUX_OPTS + [config.REMOTE_HOST]
    SSH_OPTS = ["ssh"] + SSH_MUX_OPTS + [config.REMOTE_HOST]

# See, possibly: https://stackoverflow.com/questions/44348083/how-to-send-sigint-ctrl-c-to-current-remote-process-over-ssh-without-t-optio

    # master ssh connection, to be closed when we exit
    message(ff("Opening ssh connection to {config.REMOTE_HOST}. You may be prompted for your password."))
    debug("  {}".format(" ".join(SSH_OPTS)))
    ssh_master = subprocess.check_call(SSH_OPTS + ["exit"], stderr=DEVNULL)


    # raw_input("Continue?")

    def help_yourself(problem, suggestion=None):
        """
        Prints a "help yourself" message and exits
        """
        message("{}".format(problem))
        message(ff("Please ssh {config.REMOTE_HOST} and sort it out yourself, then rerun this script"))
        if suggestion:
            message(ff("({suggestion})"))
        sys.exit(1)

    def ssh_remote(command, fail_retcode=None, stderr=DEVNULL):
        """Runs command on remote host. Returns its output if the exit status is 0, or None if the exit status matches fail_retcode.

        Any other non-zero exit status (or any other error) will result in an exception.
        """
        try:
            return subprocess.check_output(SSH_OPTS + [command], stderr=stderr).decode('utf-8')
        except subprocess.CalledProcessError as exc:
            if exc.returncode == fail_retcode:
                return None
            message(ff("ssh {command} failed with exit code {exc.returncode}"))
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
            message(ff("ssh {command} failed with exit code {exc.returncode}"))
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
            message("Note that --update implies --no-skip-checks")
            config.SKIP_CHECKS = False
        elif config.AUTO_INIT:
            message("Note that --auto-init implies --no-skip-checks")
            config.SKIP_CHECKS = False

    # propagate our config to command-line arguments
    remote_config = config.get_config_dict()
    remote_config['BROWSER'] = 'None'
    remote_config['SKIP_CHECKS'] = False
    remote_config['VENV_REINSTALL'] = False

    # Check for various remote bits
    if config.VERBOSE and not config.SKIP_CHECKS:
        message(ff("Checking installation on {config.REMOTE_HOST}."))

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
        message(ff("The '{backend}' back-end is not available on {config.REMOTE_HOST}, skipping."))
    else:
        bye(ff("None of the specified back-ends are available on {config.REMOTE_HOST}."))

    if remote_config["BACKEND"] != "docker":
        config.CONTAINER_PERSIST = config.CONTAINER_DEBUG = False

    # which runscript to look for
    runscript0 = "run-radiopadre"

    # shorthand for remote virtualenv
    remote_venv = ff("{config.REMOTE_HOST}:{config.RADIOPADRE_VENV}")

    # pip install command with -v repeated for each VERBOSE increment
    pip_install = "pip install " + "-v "*min(max(config.VERBOSE-1, 0), 3)

    # do we want to do an install/update -- will be forced to True (if we must install),
    # or False if we can't update
    do_update = config.UPDATE

    if config.SKIP_CHECKS:
        runscript = ff("rs={config.RADIOPADRE_VENV}/bin/run-radiopadre; if [ ! -x $rs ]; then " +
                     "source {config.RADIOPADRE_VENV}/bin/activate; rs=run-radiopadre; fi; $rs ")
        do_update = False
    else:
        runscript = None

        # (a) if --auto-init and --venv-reinstall specified, zap remote virtualenv if present
        if config.AUTO_INIT and config.VENV_REINSTALL:
            if not config.RADIOPADRE_VENV:
                bye(ff("Can't do --auto-init --venv-reinstall because --radiopadre-venv is not set"))
            if "~" in config.RADIOPADRE_VENV:
                config.RADIOPADRE_VENV = ssh_remote(ff("echo {config.RADIOPADRE_VENV}")).strip()  # expand "~" on remote
            if check_remote_file(ff("{config.RADIOPADRE_VENV}"), "-d"):
                if not check_remote_file(ff("{config.RADIOPADRE_VENV}/bin/activate"), "-f"):
                    error(ff("{remote_venv}/bin/activate} does not exist. Bat country!"))
                    bye(ff("Refusing to touch this virtualenv. Please remove it by hand if you must."))
                cmd = ff("rm -fr {config.RADIOPADRE_VENV}")
                warning(ff("Found a virtualenv in {remote_venv}."))
                warning("However, --venv-reinstall was specified. About to run:")
                warning(ff("    ssh {config.REMOTE_HOST} "+cmd))
                if config.FULL_CONSENT:
                    warning("--full-consent given, so not asking for confirmation.")
                else:
                    warning(ff("Your informed consent is required!"))
                    inp = INPUT(ff("Please enter 'yes' to rm -fr {remote_venv}: ")).strip()
                    if inp != "yes":
                        bye(ff("'{inp}' is not a 'yes'. Phew!"))
                    message("OK, nuking it!")
                ssh_remote(cmd)
            # force update
            do_update = True

        # (b) look inside venv
        if runscript is None and config.RADIOPADRE_VENV:
            if "~" in config.RADIOPADRE_VENV:
                config.RADIOPADRE_VENV = ssh_remote(ff("echo {config.RADIOPADRE_VENV}")).strip()  # expand "~" on remote
            if check_remote_file(ff("{config.RADIOPADRE_VENV}/bin/activate"), "-f"):
                if ssh_remote(ff("source {config.RADIOPADRE_VENV}/bin/activate && which {runscript0}"), fail_retcode=1):
                    runscript = ff("source {config.RADIOPADRE_VENV}/bin/activate && {runscript0}")
                    message(ff("Using remote client script within {config.RADIOPADRE_VENV}"))
                else:
                    message(ff(
                        "Remote virtualenv {config.RADIOPADRE_VENV} exists, but does not contain a radiopadre-client installation."))
            else:
                message(ff("No remote virtualenv found at {config.REMOTE_HOST}:{config.RADIOPADRE_VENV}"))

        # (c) just try `which` directly
        if runscript is None:
            runscript = check_remote_command(runscript0)
            if runscript:
                message(ff("Using remote client script at {runscript}"))
                do_update = False
                if config.UPDATE:
                    warning(ff("ignoring --update for client since it isn't in a virtualenv"))
            else:
                message(ff("No remote client script {runscript0} found"))
                runscript = None

    ## No runscript found on remote?
    ## First, figure out whether to reinstall a virtualenv for it
    if not runscript:
        message(ff("No {runscript0} script found on {config.REMOTE_HOST}"))
        if not config.AUTO_INIT:
            bye(ff("Try re-running with --auto-init to install radiopadre-client on {config.REMOTE_HOST}."))
        if not config.RADIOPADRE_VENV:
            bye(ff("Can't do --auto-init because --virtual-env is not set."))

        message("Trying to --auto-init an installation for you...")

        # try to auto-init a virtual environment
        if not check_remote_file(ff("{config.RADIOPADRE_VENV}/bin/activate"), "-f"):
            message(ff("Creating virtualenv {remote_venv}"))
            ssh_remote_v(ff("virtualenv -p python3 {config.RADIOPADRE_VENV}"))
            if config.VENV_EXTRAS:
                extras = " ".join(config.VENV_EXTRAS.split(","))
                message(ff("Installing specified extras: {extras}"))
                ssh_remote_v(ff("source {config.RADIOPADRE_VENV}/bin/activate && {pip_install} {extras}"))
        else:
            message(ff("Installing into existing virtualenv {remote_venv}"))

    # Now, figure out how to install or update the client package
    if not runscript or do_update:
        # installing from a specified existing path
        if config.CLIENT_INSTALL_PATH and check_remote_file(config.CLIENT_INSTALL_PATH, "-d"):
            install_path = config.CLIENT_INSTALL_PATH
            message(ff("--client-install-path {install_path} is configured and exists on {config.REMOTE_HOST}."))
            # update if managed by git
            if check_remote_file(ff("{install_path}/.git"), "-d") and config.UPDATE:
                if has_git:
                    if config.CLIENT_INSTALL_BRANCH:
                        cmd = ff("cd {install_path} && git fetch origin && git checkout {config.CLIENT_INSTALL_BRANCH} && git pull")
                    else:
                        cmd = ff("cd {install_path} && git pull")
                    warning(ff(
                        "--update specified and git detected, will attempt to update via"))
                    message(ff("    {cmd}"))
                    ssh_remote_v(cmd)
                else:
                    warning(ff("--update specified, but no git command found on {config.REMOTE_HOST}"))
            install_path = "-e " + install_path
        # else, installing from git
        elif config.CLIENT_INSTALL_REPO:
            if config.CLIENT_INSTALL_REPO == "default":
                config.CLIENT_INSTALL_REPO = config.DEFAULT_CLIENT_INSTALL_REPO
            branch = config.CLIENT_INSTALL_BRANCH or "master"
            if config.CLIENT_INSTALL_PATH:
                message(ff("--client-install-path and --client-install-repo configured, will attempt"))
                cmd = ff("git clone -b {branch} {config.CLIENT_INSTALL_REPO} {config.CLIENT_INSTALL_PATH}")
                message(ff("    ssh {config.REMOTE_HOST} {cmd}"))
                ssh_remote_v(cmd)
                install_path = ff("-e {config.CLIENT_INSTALL_PATH}")
            else:
                message(ff("--client-install-repo is configured, will try to install directly from git"))
                install_path = ff("git+{config.CLIENT_INSTALL_REPO}@{branch}")

            # now pip install
            message(ff("Doing pip install -e {install_path} in {config.RADIOPADRE_VENV}"))
            ssh_remote_v(ff("source {config.RADIOPADRE_VENV}/bin/activate && {pip_install} -e {install_path}"))
        # else, installing directly from pip
        elif config.CLIENT_INSTALL_PIP:
            message(ff("--client-install-pip {config.CLIENT_INSTALL_PIP} is configured."))
            install_path = config.CLIENT_INSTALL_PIP
        else:
            bye("no radiopadre-client installation method specified (see --client-install options)")

        # now install
        message(ff("Will attempt to pip install -U {install_path} in {remote_venv}"))
        ssh_remote_v(ff("source {config.RADIOPADRE_VENV}/bin/activate && {pip_install} -U {install_path}"))

        # sanity check
        if ssh_remote(ff("source {config.RADIOPADRE_VENV}/bin/activate && which {runscript0}"), fail_retcode=1):
            runscript = ff("source {config.RADIOPADRE_VENV}/bin/activate && {runscript0}")
        else:
            bye(ff("Something went wrong during installation on {config.REMOTE_HOST}, since I still don't see the {runscript0} script"))

        message("Success!")

    # copy notebook to remote
    if copy_initial_notebook:
        if not os.path.exists(copy_initial_notebook):
            bye("{} doesn't exist".format(copy_initial_notebook))
        if check_remote_file(notebook_path or ".", "-d"):
            nbpath = "{}/{}".format(notebook_path or ".", copy_initial_notebook)
            if check_remote_file(nbpath, "-ff("):
                message(ff("remote notebook {nbpath} exists, will not copy over"))
            else:
                message(ff("remote notebook {nbpath} doesn't exist, will copy over"))
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
        message(ff("running radiopadre client on {config.REMOTE_HOST}"))
    ssh = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1,
                           universal_newlines=True)

    poller = Poller()
    poller.register_process(ssh, config.REMOTE_HOST, config.REMOTE_HOST + " stderr")
    if not USE_VENV:
        poller.register_file(sys.stdin, "stdin")

    container_name = None
    urls = []
    remote_running = False
    status = 0

    try:
        while remote_running is not None and poller.fdlabels:
            fdlist = poller.poll(verbose=config.VERBOSE>1)
            for fname, fobj in fdlist:
                try:
                    line = fobj.readline()
                except EOFError:
                    line = b''
                empty_line = not line
                line = (line.decode('utf-8') if type(line) is bytes else line).rstrip()
                if fobj is sys.stdin and line == 'D' and config.CONTAINER_PERSIST:
                    sys.exit(0)
                # break out if ssh closes
                if empty_line:
                    poller.unregister_file(fobj)
                    if ssh.stdout not in poller and ssh.stderr not in poller:
                        message(ff("The ssh process to {config.REMOTE_HOST} has exited"))
                        remote_running = None
                        break
                    continue
                # print remote output
                print_output = False
                if fobj is ssh.stderr:
                    print_output = not line.startswith("Shared connection to")
                else:
                    print_output = not line.startswith("radiopadre:") or command != 'load'
                if not empty_line and (config.VERBOSE or print_output):
                    for key, dispatch in _dispatch_message.items():
                        if key in line:
                            dispatch(u"{}: {}".format(fname, line))
                            break
                    else:
                        message(u"{}: {}".format(fname, line))
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
                    match = re.match(ff(".*Selected ports: {re_ports}[\s]*$"), line)
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
                    match = re.match(".*Browse to URL: ([^\s\033]+)", line)
                    if match:
                        urls.append(match.group(1))
                        continue

                    # check for container name
                    match = re.match(".*Container name: ([^\s\033]+)", line)
                    if match:
                        container_name = match.group(1)
                        continue

                    if "jupyter notebook server is running" in line:
                        remote_running = True
                        time.sleep(1)
                        iglesia.register_helpers(*run_browser(*urls))
                        message("The remote radiopadre session is now fully up")
                        if USE_VENV or not config.CONTAINER_PERSIST:
                            message("Press Ctrl+C to kill the remote session")
                        else:
                            message("Press D<Enter> to detach from remote session, or Ctrl+C to kill it")

    except SystemExit as exc:
        message(ff("SystemExit: {exc.code}"))
        status = exc.code

    except KeyboardInterrupt:
        message("Ctrl+C caught")
        status = 1

    except Exception as exc:
        traceback.print_exc()
        message("Exception caught: {}".format(str(exc)))

    if remote_running and ssh.poll() is None:
        message("Asking remote session to exit, nicely")
        try:
            try:
                ssh.stdin.write("exit\n")
            except TypeError:
                ssh.stdin.write(b"exit\n")  # because fuck you python
        except IOError:
            debug("  looks like it's already exited")


    # if status and not USE_VENV and container_name:
    #     message(ff("killing remote container {container_name}"))
    #     try:
    #         if has_docker:
    #             ssh_remote(ff("{has_docker} kill {container_name}"))
    #         elif has_singularity:
    #             from .backends.singularity import get_singularity_image
    #             singularity_image = get_singularity_image(config.DOCKER_IMAGE)
    #             ssh_remote(ff("{has_singularity} instance.stop {singularity_image} {container_name}"))
    #     except subprocess.CalledProcessError as exc:
    #         message(exc.output.decode())

    for i in range(10, 0, -1):
        if ssh.poll() is not None:
            debug("Remote session has exited")
            ssh.wait()
            break
        message(ff("Waiting for remote session to exit ({i})"))
        time.sleep(1)
    else:
        message(ff("Remote session hasn't exited, killing the ssh process"))
        ssh.kill()

    return status