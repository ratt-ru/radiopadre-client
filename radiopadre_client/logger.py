import sys, os.path, logging

logger = None

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

_default_formatter = logging.Formatter("%(message)s")

_default_console_handler = MultiplexingHandler()
_default_console_handler.setFormatter(_default_formatter)

def init(appname, use_formatter=True):
    global logger
    global _default_formatter
    logging.basicConfig()
    logger = logging.getLogger(appname)
    if use_formatter:
        _default_formatter = logging.Formatter(fmt="{}: %(timestamp)s%(message)s".format(appname))
        _default_console_handler.setFormatter(_default_formatter)
    logger.addHandler(_default_console_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger

def disable_printing():
    logger.removeHandler(_default_console_handler)

def enable_logfile(logtype):
    from .utils import make_dir, ff
    make_dir("~/.radiopadre")
    logname = os.path.expanduser(ff("~/.radiopadre/log-{logtype}.txt"))
    logfile = open(logname, 'wt')
    fh = logging.StreamHandler(logfile)
    fh.setFormatter(_default_formatter)
    logger.addHandler(fh)
    return logfile
