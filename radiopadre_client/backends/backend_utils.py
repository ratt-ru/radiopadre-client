import socket, time, os, os.path

import iglesia
from iglesia.utils import message, bye, ff, shell
from radiopadre_client import config

def update_server_from_repository():
    """
    Updates the radiopadre git working directory, if necessary
    :return:
    """
    if config.UPDATE and config.SERVER_INSTALL_PATH and os.path.isdir(config.SERVER_INSTALL_PATH + "/.git"):
        if config.SERVER_INSTALL_BRANCH:
            cmd = ff("cd {config.SERVER_INSTALL_PATH} && git fetch origin && git checkout {config.SERVER_INSTALL_BRANCH} && git pull")
        else:
            cmd = ff("cd {config.SERVER_INSTALL_PATH} && git pull")
        message(ff(
            "--update specified, --server-install-path at {config.SERVER_INSTALL_PATH} will be updated via"))
        message(ff("    {cmd}"))
        if shell(cmd):
            bye("update failed")


def await_server_startup(port, process=None, server_name="jupyter notebook server", init_wait=2, wait=60):
    """
    Waits for a server process to start up, tries to connect to the specified port,
    returns when successful

    :param port:        port number
    :param process:     if not None, waits on the process and checks its return code
    :param init_wait:   number of second to wait before trying to connect
    :param wait:        total number of seconds to wait before giving up
    :return:            number of seconds elapsed before connection, or None if failed
    """
    # pause to let the Jupyter server spin up
    t0 = time.time()
    time.sleep(init_wait)
    # then try to connect to it
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for retry in range(int(wait/.1)):
        # try to connect
        try:
            sock.connect(("localhost", port))
            del sock
            return time.time() - t0
        except socket.error:
            pass
        if not retry:
            message(ff("Waiting for up to {wait} secs for the {server_name} to come up"))
        # sleep, check process
        if process is not None:
            process.poll()
            if process.returncode is not None:
                return None
        time.sleep(.1)
    return None

