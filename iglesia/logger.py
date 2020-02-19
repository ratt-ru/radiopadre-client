import sys, os.path, logging, time, atexit

logger = None
logfile = sys.stderr
logfile_handler = None

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

    def emit(self, record):
        handler = self.err_handler if record.levelno > logging.INFO else self.info_handler
        handler.emit(record)
        # ignore broken pipes, this often happens when cleaning up and exiting
        try:
            handler.flush()
        except BrokenPipeError:
            pass

    def flush(self):
        try:
            self.err_handler.flush()
            self.info_handler.flush()
        except BrokenPipeError:
            pass

    def close(self):
        self.err_handler.close()
        self.info_handler.close()

    def setFormatter(self, fmt):
        self.err_handler.setFormatter(fmt)
        self.info_handler.setFormatter(fmt)

class ColorizingFormatter(logging.Formatter):
    """This Formatter inserts color codes into the string according to severity"""
    Colors = dict(WARNING = '\033[93m',
                    ERROR = '\033[91m',
                    BOLD = '\033[1m',
                    GREEN = '\033[92m',
                    ENDC = '\033[0m')

    def format(self, record):
        style = ""
        if hasattr(record, 'color'):
            style = self.Colors[record.color]
        elif record.levelno >= logging.ERROR:
            style = self.Colors['ERROR']
        elif record.levelno >= logging.WARNING:
            style = self.Colors['WARNING']
        endstyle = self.Colors['ENDC'] if style else ""
        return super(ColorizingFormatter, self).format(record).format(style, endstyle)

_default_format = "%(name)s%(timestamp)s: {0}%(severity)s%(message)s{1}"
_default_formatter = ColorizingFormatter(_default_format)

_default_console_handler = MultiplexingHandler()
_default_console_handler.setFormatter(_default_formatter)

def init(appname, timestamps=True):
    global logger
    global _default_formatter
    logging.basicConfig()
    logger = logging.getLogger(appname)
    TimestampFilter.enable = timestamps
    logger.addFilter(TimestampFilter())
    logger.addHandler(_default_console_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger

def enable_timestamps(enable=True):
    TimestampFilter.enable = enable

def disable_printing():
    logger.removeHandler(_default_console_handler)

def enable_logfile(logtype):
    from .utils import make_dir, ff
    global logfile, logfile_handler

    make_dir("~/.radiopadre")
    make_dir("~/.radiopadre/logs")
    datetime = time.strftime("%Y%m%d%H%M%S")
    logname = os.path.expanduser(ff("~/.radiopadre/logs/log-{logtype}-{datetime}.txt"))
    logfile = open(logname, 'wt')
    logfile_handler = logging.StreamHandler(logfile)
    logfile_handler.setFormatter(logging.Formatter(
        "%(asctime)s: " + _default_format.format("", ""), "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(logfile_handler)
    atexit.register(flush)
    return logfile

def flush():
    if logfile_handler:
        logfile_handler.flush()
