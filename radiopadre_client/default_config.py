from collections import OrderedDict

DefaultConfig = OrderedDict(
    AUTO_INIT = False,
    AUTO_LOAD = "radiopadre-auto.ipynb",
    AUTOINSTALL_PIP = "radiopadre-client",
    AUTOINSTALL_REPO = "git@github.com:ratt-ru/radiopadre-client.git",
    AUTOINSTALL_BRANCH = "master",
    BACKEND = "",
    BROWSER = "default",
    CONTAINER_DEV = False,
    DEFAULT_NOTEBOOK = "radiopadre-default.ipynb",
    DOCKER_IMAGE = "osmirnov/radiopadre:exp",
    SERVER_INSTALL_PATH = "~/radiopadre",
    CLIENT_INSTALL_PATH = "~/radiopadre-client",
    UPDATE = False,
    VERBOSE = 0,
    RADIOPADRE_VENV = "~/.radiopadre/venv",
    VENV_REINSTALL = False,
    VENV_NO_JS9 = False,
    VENV_NO_CASACORE = False,
)
