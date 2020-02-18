import sys, os.path, logging, time

logger = None
logfile = sys.stderr

class TimestampFilter(logging.Filter):
    """Adds a timestamp attribute to the LogRecord, if enabled"""
    time0 = time.time()
    enable = False
    def filter(self, record):
        if self.enable:
            record.timestamp = "[{:.2f}s] ".format(time.time() - self.time0)
        else:
            record.timestamp = ""
        return True

class MultiplexingHandler(logging.Handler):
    def __init__(self, info_stream=sys.stdout, err_stream=sys.stderr):
        super(MultiplexingHandler, self).__init__()
        self.info_handler = logging.StreamHandler(info_stream)
        self.err_handler = logging.StreamHandler(err_stream)

    def emit(self, record):
        handler = self.err_handler if record.levelno > logging.INFO else self.info_handler
        handler.emit(record)
        handler.flush()

    def flush(self):
        self.err_handler.flush()
        self.info_handler.flush()

    def close(self):
        self.err_handler.close()
        self.info_handler.close()

    def setFormatter(self, fmt):
        self.err_handler.setFormatter(fmt)
        self.info_handler.setFormatter(fmt)

_default_format = "%(name)s: %(timestamp)s%(message)s"
_default_formatter = logging.Formatter(_default_format)

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
    global logfile

    make_dir("~/.radiopadre")
    make_dir("~/.radiopadre/logs")
    datetime = time.strftime("%Y%m%d%H%M%S")
    logname = os.path.expanduser(ff("~/.radiopadre/logs/log-{logtype}-{datetime}.txt"))
    logfile = open(logname, 'wt')
    fh = logging.StreamHandler(logfile)
    fh.setFormatter(logging.Formatter("%(asctime)s: " + _default_format, "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    return logfile
