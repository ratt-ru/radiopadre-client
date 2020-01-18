import os
import subprocess

AUTOINSTALL_CLIENT_VENV = "~/.radiopadre/venv-client"

AUTOINSTALL_VERSION = "radiopadre-client"

AUTOINSTALL_REPO = "git@github.com:ratt-ru/radiopadre-client.git"

AUTOINSTALL_BRANCH = "master"

AUTOINSTALL_PATH = "~/radiopadre-client"

CONTAINER_PORTS = 11001, 11002, 11003, 11004, 11005

DEFAULT_DOCKER_IMAGE = "osmirnov/radiopadre:latest"

UNAME = subprocess.check_output("uname").strip()

USER = os.environ['USER']

DEFAULT_BROWSER = os.environ.get("RADIOPADRE_BROWSER", "open" if UNAME == "Darwin" else "xdg-open")

SERVER_VENV = "~/.radiopadre/venv"

SERVER_INSTALL_PATH = "~/radiopadre"
CLIENT_INSTALL_PATH = "~/radiopadre-client"

# set to remote host, if running remote session
REMOTE_HOST = None

REMOTE_PATH = None