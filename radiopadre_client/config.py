import os, os.path, subprocess, configparser, re

from .utils import make_dir, message
from .default_config import DefaultConfig

# const object to use as default value in ArgumentParser. Will be replaced by contents
# of config file.
DEFAULT_VALUE = object()

AUTO_INIT = False
CONTAINER_PORTS = 11001, 11002, 11003, 11004, 11005
AUTO_LOAD = "radiopadre-auto*.ipynb"
DEFAULT_NOTEBOOK = "radiopadre-default.ipynb"
DOCKER_IMAGE = "osmirnov/radiopadre:latest"
DOCKER_DEBUG = False
DOCKER_DETACH = False
CONTAINER_DEV = False
BACKEND = []
UNAME = subprocess.check_output("uname").strip()
USER = os.environ['USER']
BROWSER = os.environ.get("RADIOPADRE_BROWSER", "open" if UNAME == "Darwin" else "xdg-open")
BROWSER_BG = False
BROWSER_MULTI = False
RADIOPADRE_VENV = "~/.radiopadre/venv"

SERVER_INSTALL_PATH = "~/radiopadre"
SERVER_INSTALL_REPO = "git@github.com:ratt-ru/radiopadre.git"
SERVER_INSTALL_BRANCH = "py3"

CLIENT_INSTALL_PATH = "~/radiopadre-client"
CLIENT_INSTALL_PIP = "radiopadre-client"
CLIENT_INSTALL_REPO = "git@github.com:ratt-ru/radiopadre-client.git"
CLIENT_INSTALL_BRANCH = "master"

UPDATE = False
VERBOSE = 0
VENV_REINSTALL = False
VENV_IGNORE_JS9 = False
VENV_IGNORE_CASACORE = False


# set to remote host, if running remote session
REMOTE_HOST = None
REMOTE_MODE_PORTS = False
INSIDE_CONTAINER_PORTS = False

CONFIG_FILE = os.path.expanduser("~/.config/radiopadre-client")

COMPLETE_INSTALL_COOKIE = ".radiopadre.install.complete"

_DEFAULT_KEYS = None
_CMDLINE_DEFAULTS = {}

def _get_config_value(section, key):
    globalval = globals().get(key.upper())
    if globalval is None or type(globalval) is str:
        return section[key]
    elif type(globalval) is bool:
        return section.getboolean(key)
    elif type(globalval) is int:
        return section.getint(key)
    else:
        raise TypeError(f"unsupported type for {key}")

def _set_config_value(key):
    value = globals()[key]
    if type(value) is list:
        return ",".join(value)
    return str(value)

def init_defaults():
    """Initializes global defaults (global vars in this module) from default_config.py"""
    global _DEFAULT_KEYS
    _DEFAULT_KEYS = list(DefaultConfig.keys())

    for key, value in DefaultConfig.items():
        if value != "default":
            globals()[key] = value if value is not None else False

def get_config_dict():
    """
    Forms up dict of config settings that can be turned into command-line arguments.

    :return: dictionary of config settings
    """
    global _DEFAULT_KEYS
    return {key: globals()[key] for key in _DEFAULT_KEYS}

def add_to_parser(parser):
    """Adds parser options corresponding to global defaults (that have not been added to the parser already)"""
    global _DEFAULT_KEYS, _CMDLINE_DEFAULTS
    for key in _DEFAULT_KEYS:
        defvalue = DefaultConfig[key]
        lkey = key.lower()
        optname = lkey.replace("_", "-")
        default = parser.get_default(lkey)
        if default is None:
            parser.add_argument("--" + optname, type=type(defvalue), metavar=key,
                                help=f"overrides the {key} config setting.")
        else:
            if type(DefaultConfig[key]) is bool:
                if default is 0:
                    parser.add_argument("--no-" + optname, action="store_false", dest=lkey,
                                        help=f"opposite of --{optname}.")
                elif default is 1:
                    parser.add_argument(optname, action="store_true", dest=lkey,
                                        help=f"opposite of --no-{optname}.")
            _CMDLINE_DEFAULTS[key] = default

def init_specific_options(remote_host, notebook_path, options):
    global _DEFAULT_KEYS
    global _CMDLINE_DEFAULTS
    parser = configparser.ConfigParser()
    hostname = f"{remote_host}" if remote_host else "local sesssion"
    session = f"{hostname}:{notebook_path}"
    config_exists = os.path.exists(CONFIG_FILE)
    use_config_files = not options.remote and not options.inside_container

    # try to read config file for host and host:path (not in --remote mode though)
    if use_config_files and config_exists:
        parser.read(CONFIG_FILE)
        for sect_key in "global defaults", hostname, session:
            if sect_key in parser:
                section = parser[sect_key]
                if section:
                    message(f"  loading settings from {CONFIG_FILE} [{sect_key}]")
                    for key in _DEFAULT_KEYS:
                        lkey = key.lower()
                        if lkey in section:
                            value = _get_config_value(section, lkey)
                            if value != globals()[key]:
                                message(f"    {key} = {value}")
                                globals()[key] = value

    # update using command-line options
    command_line_updated = []
    for key in globals().keys():
        if re.match("^[A-Z]", key):
            optname = key.lower()
            value = getattr(options, optname, None)
            # skip DEFAULT_VALUE placeholders, trust in config
            if value is DEFAULT_VALUE or value is None:
                continue
            if type(value) is list:
                value = ",".join(value)
            if value != _CMDLINE_DEFAULTS[key]:
                if use_config_files:
                    # do not mark options such as --update for saving
                    if value is not _CMDLINE_DEFAULTS.get(key) and DefaultConfig.get(key) is not None:
                        command_line_updated.append(key)
                    message(f"  command line specifies {key} = {value}")
                globals()[key] = value

    # save new config
    if use_config_files and command_line_updated:
        if options.save_config_host:
            message(f"  saving command-line settings to {CONFIG_FILE} [{hostname}]")
            parser.setdefault(hostname, {})
            for key in command_line_updated:
                parser[hostname][key] = _set_config_value(key)
        if options.save_config_session:
            parser.setdefault(session, {})
            message(f"  saving command-line settings to {CONFIG_FILE} [{session}]")
            for key in command_line_updated:
                parser[session][key] = _set_config_value(key)

        if options.save_config_host or options.save_config_session:
            make_dir("~/.radiopadre")
            with open(CONFIG_FILE + ".new", "w") as configfile:
                if not config_exists:
                    message(f"  creating new config file {CONFIG_FILE}")
                if 'global defaults' not in parser:
                    configfile.write("[global defaults]\n# defaults that apply to all sessions go here\n\n")

                parser.write(configfile)

                configfile.write("\n\n## default settings follow\n")
                for key, value in DefaultConfig.items():
                    configfile.write("# {} = {}\n".format(key.lower(), value))

            # if successful, rename files
            if config_exists:
                if os.path.exists(CONFIG_FILE + ".old"):
                    os.unlink(CONFIG_FILE + ".old")
                os.rename(CONFIG_FILE, CONFIG_FILE + ".old")
            os.rename(CONFIG_FILE + ".new", CONFIG_FILE)

            message(f"saved updated config to {CONFIG_FILE}")


if _DEFAULT_KEYS is None:
    init_defaults()