from collections import OrderedDict

# This defines default values for the config settings, which will also be propagated into the
# ArgumentParser, and saved to/loaded from {config.CONFIG_FILE}

# Settings of type "None" will be treated as boolean switches with are NOT saved to the config file
# (i.e. can only be specified from the command line). --update is an example.
#
# Settings of type bool will receive "--option"/"--no-option" arguments automatically if the
# registered default is None, or a "--no-option" argument is the registered default is 0

DefaultConfig = OrderedDict(
    AUTO_INIT=None,
    AUTO_LOAD="radiopadre-auto.ipynb",
    AUTOINSTALL_PIP="radiopadre-client",
    AUTOINSTALL_REPO="git@github.com:ratt-ru/radiopadre-client.git",
    AUTOINSTALL_BRANCH="py3",
    BACKEND="",
    BROWSER="default",
    CONTAINER_DEV=False,
    DEFAULT_NOTEBOOK="radiopadre-default.ipynb",
    DOCKER_IMAGE="osmirnov/radiopadre:exp",
    DOCKER_DEBUG=False,
    DOCKER_DETACH=False,
    CLIENT_INSTALL_PATH="~/radiopadre-client",
    SERVER_INSTALL_PATH="~/radiopadre",
    SERVER_INSTALL_REPO="git@github.com:ratt-ru/radiopadre.git",
    SERVER_INSTALL_BRANCH="py3",
    UPDATE=None,
    VERBOSE=0,
    RADIOPADRE_VENV="~/.radiopadre/venv",
    VENV_REINSTALL=None,
    VENV_IGNORE_JS9=False,
    VENV_IGNORE_CASACORE=False,
)

