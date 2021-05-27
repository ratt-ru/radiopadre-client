from collections import OrderedDict


# This defines default values for the config settings, which will also be propagated into the
# ArgumentParser, and saved to/loaded from {config.CONFIG_FILE}

# Settings of type "None" will be treated as boolean switches with are NOT saved to the config file
# (i.e. can only be specified from the command line). --update is an example.
#
# Settings of type bool will receive "--option"/"--no-option" arguments automatically if the
# registered default is None, or a "--no-option" argument is the registered default is 0

import os.path
import re

# change this to a proper patch release number for a real release
__version__ = "1.2.pre1"

# set this to True to have auto-installs use git rather than pip, suitable dor dev branches etc.
# default convention is to use b1.2.x branch for version 1.2.preN
__install_from_branch__ = "b" + re.sub("pre.*", "x", __version__) if "pre" in __version__ else None

__tag_prefix__ = "b" if __install_from_branch__ else ""

# if True, this is a stable release e.g. 1.1.0. If False, this is an dev version e.g. 1.1.x 
__release__ = re.match("^(\d+)\.(\d+)\.(\d+)$", __version__)

# release x.y.z pulls x.y.latest image
if __release__:
    __image_version__ = ".".join([__release__.group(1), __release__.group(2), "latest"])
else:
    __image_version__ = __version__

DefaultConfig = OrderedDict(
    AUTO_LOAD="radiopadre-auto.ipynb",
    SKIP_CHECKS=False,
    BACKEND="",
    BORING=False,
    BROWSER="default",
    NEW_WINDOW=True,
    CARTA_BROWSER=True,
    CONTAINER_DEV=False,
    DEFAULT_NOTEBOOK="radiopadre-default.ipynb",
    DOCKER_IMAGE="quay.io/osmirnov/radiopadre:" + __image_version__,         # change for each release
    CONTAINER_DEBUG=False,
    GRIM_REAPER=True,
    REMOTE_RADIOPADRE_DIR="~/.radiopadre",
    CLIENT_INSTALL_PATH="~/radiopadre-client",
    CLIENT_INSTALL_REPO="https://github.com/ratt-ru/radiopadre-client.git" if __install_from_branch__ else "",
    CLIENT_INSTALL_BRANCH=__install_from_branch__,
    CLIENT_INSTALL_PIP="radiopadre-client",
    SERVER_INSTALL_PATH="~/radiopadre",
    SERVER_INSTALL_REPO="https://github.com/ratt-ru/radiopadre.git" if __install_from_branch__ else "",
    SERVER_INSTALL_BRANCH=__install_from_branch__,                  
    SERVER_INSTALL_PIP="radiopadre",
    SINGULARITY_IMAGE_DIR="",
    SINGULARITY_AUTO_BUILD=True,
    IGNORE_UPDATE_ERRORS=False,
    VERBOSE=0,
    LOG=False,
#    SSL=None,
    TIMESTAMPS=False,
    RADIOPADRE_VENV="{RADIOPADRE_DIR}/venv",
    VENV_IGNORE_JS9=False,
    VENV_IGNORE_CASACORE=False,
    VENV_EXTRAS="None",

    # All of the options above can be persisted in the config file via --save-config-host or --save-config-session.
    # The options below are "one-shot" and non-persisting, they are not saved to the config. This is indicated by a
    # default value of None. They also don't get an "opposite" (--no-option-name) switch added to the parser.
    AUTO_INIT=None,
    NON_INTERACTIVE=None,
    UPDATE=None,
    SINGULARITY_REBUILD=None,
    NBCONVERT=None,
    FULL_CONSENT=None,
    VENV_REINSTALL=None,
    VENV_DRY_RUN=None,
    PULL_DOCKER=None,
    PULL_SINGULARITY=None
)

