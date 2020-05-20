import os, pickle, re, traceback, readline, shlex
from collections import OrderedDict
import iglesia


from radiopadre_client import config
from iglesia.utils import message, warning, error, bye, ff, INPUT, make_radiopadre_dir
from iglesia import logger

_recent_sessions = None
_last_input = None

RECENTS_FILE = os.path.join(iglesia.RADIOPADRE_DIR, "radiopadre-client.sessions.recent")
HISTORY_FILE = os.path.join(iglesia.RADIOPADRE_DIR, "radiopadre-client.sessions.history")

def _load_recent_sessions(must_exist=True):
    """
    Load recent sessions from RECENTS_FILE.

    :param must_exist:  if True and session file does not exist, exit with error
    :return:            dict of latest sessions
    """
    global _recent_sessions
    if _recent_sessions is not None:
        return _recent_sessions

    if os.path.exists(RECENTS_FILE):
        _recent_sessions = OrderedDict()
        try:
            for line in open(RECENTS_FILE, "rt"):
                key, args = line.strip().split(":::", 1)
                _recent_sessions[key] = args
        except Exception as exc:
            message(ff("Error reading {RECENTS_FILE}: {exc}"))
            _recent_sessions = None

    if _recent_sessions is None and must_exist:
        bye("no recent radiopadre sessions and no arguments given. Run with -h for help.")

    return _recent_sessions


def check_recent_sessions(options, argv, parser=None):
    """
    Loads a recent session if requested

    :param options: Options object from ArgumentParser
    :param argv:    Argument list (from sys.argv[1:] initially)
    :param parser:  ArgumentParser object used to (re)parse the options

    :return: options, argv
                    Where options and argv may have been loaded from the recent
                    options file
    """
    make_radiopadre_dir()
    # load history
    try:
        readline.read_history_file(HISTORY_FILE)
    except IOError:
        pass

    resume_session = None
    # a single-digit argument resumes session #N
    if len(options.arguments) == 1 and re.match("^\d$", options.arguments[0]):
        resume_session = int(options.arguments[0])
    # no arguments is resume session #0
    elif not options.arguments:
        resume_session = 0

    if resume_session is not None:

        last = _load_recent_sessions()
        num_recent = len(last)
        if resume_session >= num_recent:
            bye(ff("no recent session #{resume_session}"))

        message("Your most recent radiopadre sessions are:")
        message("")
        for i, (_, opts) in enumerate(list(last.items())[::-1]):
            message("    [#{0}] {1}".format(i, opts), color="GREEN")
        message("")
        print("\nInteractive startup mode. Edit arguments and press Enter to run, or Ctrl+C to bail out. ")
        print("    (Ctrl+U + <NUM> + Enter will paste other recent session arguments from the list above)\n")

        inp = None
        cmdline = ''
        readline.set_startup_hook(lambda: readline.insert_text(cmdline))

        while inp is None:
            # form up list of fake args to be re-parsed for the last session
            cmdline = list(last.items())[-(resume_session + 1)][1]
            # non-persisting options raised in command line shall be appended to the fake args
            for opt in config.NON_PERSISTING_OPTIONS:
                if opt.startswith("--") and getattr(options, opt[2:].replace("-", "_"), None):
                    cmdline += " " + opt
            cmdline += " "

            ## colors confuse Ctrl+U and such
            # prompt = ff("{logger.Colors.GREEN}[#{resume_session}]:{logger.Colors.ENDC} ")
            prompt = ff("[#{resume_session}] ")
            inp = INPUT(prompt)
            inp = inp.strip()
            if not inp:
                resume_session = 0
                inp = None
            elif re.match("^\d+$", inp):
                res = int(inp)
                if res >= num_recent:
                    warning(ff("no recent session #{res}"))
                else:
                    resume_session = res
                readline.remove_history_item(1)
                inp = None

        readline.set_startup_hook(None)

        global _last_input
        _last_input = inp

        argv = shlex.split(inp, posix=False)

        options = parser.parse_args(argv)

    return options, argv


def save_recent_session(session_key, argv):
    """
    Saves session arguments into recents file.

    :param session_key: key to save under (only one session per key is saved)
    :param argv:        argument list to save
    :return:            None
    """
    # add current line to history, if not already there
    cmdline =  " ".join([x if x and not ' ' in x else "'{}'".format(x) for x in argv])
    if not _last_input:
        if cmdline != readline.get_history_item(readline.get_current_history_length()):
            readline.add_history(cmdline)

    make_radiopadre_dir()
    try:
        readline.write_history_file(HISTORY_FILE)
    except IOError:
        traceback.print_exc()
        warning("Error writing history file (see above). Proceeding anyway.")

    readline.clear_history()

    # reform command-line without persisting options
    cmdline =  " ".join([x if x and not ' ' in x else "'{}'".format(x) for x in argv
                         if x not in config.NON_PERSISTING_OPTIONS])

    recents = _load_recent_sessions(False) or OrderedDict()
    session_key = ":".join(map(str, session_key))
    if session_key in recents:
        del recents[session_key]
    if len(recents) >= 5:
        del recents[list(recents.keys())[0]]
    recents[session_key] = cmdline

    make_radiopadre_dir()
    with open(RECENTS_FILE, 'wt') as rf:
        for key, cmdline in recents.items():
            rf.write("{}:::{}\n".format(key, cmdline))

    global _recent_sessions
    _recent_sessions = recents

