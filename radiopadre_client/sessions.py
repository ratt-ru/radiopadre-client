import os, pickle, re, traceback
import readline
from collections import OrderedDict


from radiopadre_client import config
from iglesia.utils import message, warning, error, bye, ff, INPUT, make_radiopadre_dir
from iglesia import logger

_recent_sessions = None
_last_input = None

RECENTS_FILE = os.path.expanduser("~/.radiopadre/radiopadre-client.sessions.recent")
HISTORY_FILE = os.path.expanduser("~/.radiopadre/radiopadre-client.sessions.history")


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
        try:
            _recent_sessions = pickle.load(open(RECENTS_FILE, "rb"))
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
            message("    [#{0}] {1}".format(i, " ".join(opts)), color="GREEN")
        message("")
        print("\nInteractive startup mode. Edit arguments and press Enter to run, or Ctrl+C to bail out. ")
        print("    (Ctrl+U + <NUM> + Enter will paste other recent session arguments from the list above)\n")

        inp = None
        cmdline = ''
        readline.set_startup_hook(lambda: readline.insert_text(cmdline))

        while inp is None:
            # form up list of fake args to be re-parsed for the last session
            argv = list(last.items())[-(resume_session + 1)][1]
            # non-persisting options raised in command line shall be appended to the fake args
            for opt in config.NON_PERSISTING_OPTIONS:
                if opt.startswith("--") and getattr(options, opt[2:].replace("-", "_"), None):
                    argv.append(opt)

            # make the recent session into a string
            cmdline = " ".join([x or "''" for x in argv])

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

        argv = ["" if x == "''" or x == '""' else x for x  in inp.split()]

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
    if not _last_input:
        cmd = " ".join([x if x else "''" for x in argv])
        if cmd != readline.get_history_item(readline.get_current_history_length()):
            readline.add_history(cmd)

    make_radiopadre_dir()
    try:
        readline.write_history_file(HISTORY_FILE)
    except IOError:
        traceback.print_exc()
        warning("Error writing history file (see above). Proceeding anyway.")

    readline.clear_history()

    recents = _load_recent_sessions(False) or OrderedDict()
    if session_key in recents:
        del recents[session_key]
    if len(recents) >= 5:
        del recents[recents.keys()[0]]
    recents[session_key] = [a for a in argv if a not in config.NON_PERSISTING_OPTIONS]
    make_radiopadre_dir()
    pickle.dump(recents, open(RECENTS_FILE, 'wb'))

    global _recent_sessions
    _recent_sessions = recents

