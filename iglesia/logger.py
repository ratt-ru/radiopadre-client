import sys, os.path, logging, time, atexit, glob

logger = None
logfile = sys.stderr
logfile_handler = None

NUM_RECENT_LOGS = 5

try:
    PipeError = BrokenPipeError
except NameError:  # for py2
    PipeError = IOError

class TimestampFilter(logging.Filter):
    """Adds a timestamp attribute to the LogRecord, if enabled"""
    time0 = time.time()
    enable = False
    def filter(self, record):
        if self.enable:
            record.timestamp = " [{:.2f}s]".format(time.time() - self.time0)
        else:
            record.timestamp = ""
        if record.levelno != logging.INFO:
            record.severity = "{}: ".format(logging.getLevelName(record.levelno))
        else:
            record.severity = ""
        return True

class MultiplexingHandler(logging.Handler):
    def __init__(self, info_stream=sys.stdout, err_stream=sys.stderr):
        super(MultiplexingHandler, self).__init__()
        self.info_handler = logging.StreamHandler(info_stream)
        self.err_handler = logging.StreamHandler(err_stream)
        self.multiplex = True

    def emit(self, record):
        handler = self.err_handler if record.levelno > logging.INFO and self.multiplex else self.info_handler
        handler.emit(record)
        # ignore broken pipes, this often happens when cleaning up and exiting
        try:
            handler.flush()
        except PipeError:
            pass

    def flush(self):
        try:
            self.err_handler.flush()
            self.info_handler.flush()
        except PipeError:
            pass

    def close(self):
        self.err_handler.close()
        self.info_handler.close()

    def setFormatter(self, fmt):
        self.err_handler.setFormatter(fmt)
        self.info_handler.setFormatter(fmt)

class Colors():
    WARNING = '\033[93m' if sys.stdin.isatty() else ''
    ERROR   = '\033[91m' if sys.stdin.isatty() else ''
    BOLD    = '\033[1m'  if sys.stdin.isatty() else ''
    GREEN   = '\033[92m' if sys.stdin.isatty() else ''
    ENDC    = '\033[0m'  if sys.stdin.isatty() else ''


class ColorizingFormatter(logging.Formatter):
    """This Formatter inserts color codes into the string according to severity"""

    def format(self, record):
        style = ""
        if hasattr(record, 'color'):
            style = getattr(Colors, record.color, "")
        elif record.levelno >= logging.ERROR:
            style = Colors.ERROR
        elif record.levelno >= logging.WARNING:
            style = Colors.WARNING
        endstyle = Colors.ENDC if style else ""
        msg = super(ColorizingFormatter, self).format(record)
        return msg.replace("{<{<", style).replace(">}>}", endstyle)

_default_format = "%(name)s%(timestamp)s: {<{<%(severity)s%(message)s>}>}"
_default_format_boring = "%(name)s%(timestamp)s: %(severity)s%(message)s"
_boring_formatter = logging.Formatter(_default_format_boring)
_colorful_formatter = ColorizingFormatter(_default_format)
_default_console_handler = MultiplexingHandler()

def init(appname, timestamps=True, boring=False):
    global logger
    global _default_formatter
    logging.basicConfig()
    logger = logging.getLogger(appname)
    TimestampFilter.enable = timestamps
    logger.addFilter(TimestampFilter())
    _default_console_handler.setFormatter(_boring_formatter if boring else _colorful_formatter)
    logger.addHandler(_default_console_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger

def errors_to_stdout(enable=True):
    _default_console_handler.multiplex = not enable

def enable_timestamps(enable=True):
    TimestampFilter.enable = enable

def disable_printing():
    logger.removeHandler(_default_console_handler)

def enable_logfile(logtype, verbose=False):
    from .utils import make_dir, make_radiopadre_dir, ff
    global logfile, logfile_handler

    radiopadre_dir = make_radiopadre_dir()
    make_dir(ff("{radiopadre_dir}/logs"))
    datetime = time.strftime("%Y%m%d%H%M%S")
    logname = os.path.expanduser(ff("{radiopadre_dir}/logs/log-{logtype}-{datetime}.txt"))
    logfile = open(logname, 'wt')
    logfile_handler = logging.StreamHandler(logfile)
    logfile_handler.setFormatter(logging.Formatter(
                "%(asctime)s: " + _default_format_boring,
                "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(logfile_handler)
    atexit.register(flush)

    if verbose:
        logger.info(ff("writing session log to {logname}"))

    # clear most recent log files
    recent_logs = sorted(glob.glob(ff("{radiopadre_dir}/logs/log-{logtype}-*.txt")))
    if len(recent_logs) > NUM_RECENT_LOGS:
        delete_logs = recent_logs[:-NUM_RECENT_LOGS]
        if verbose:
            logger.info("  (also deleting {} old log file(s) matching log-{}-*.txt)".format(len(delete_logs), logtype))
        for oldlog in delete_logs:
            try:
                os.unlink(oldlog)
            except Exception as exc:
                if verbose:
                    logger.warning(ff("  failed to delete {oldlog}: {exc}"))

    return logfile, logname

def flush():
    if logfile_handler:
        logfile_handler.flush()
