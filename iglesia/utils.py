from __future__ import print_function
import os.path, select, socket, subprocess, sys, logging, errno, traceback

import iglesia
from iglesia import logger

DEVZERO = open("/dev/zero")
DEVNULL = open("/dev/null", "w")

try:
    INPUT = raw_input   # py2
except NameError:
    INPUT = input       # py3

def message(x, level=logging.INFO, color=None):
    """Prints message"""
    if type(x) is bytes:
        x = x.decode()
    extra = dict(color=color) if color else {}
    if logger.logger is not None:
        logger.logger.log(level, x, extra=extra)

def warning(x):
    message(x, logging.WARNING)

def error(x):
    message(x, logging.ERROR)

def debug(x):
    message(x, logging.DEBUG)

def bye(x, code=1):
    """Prints error message, exits with given code"""
    message(x, level=logging.ERROR)
    sys.exit(code)

def ff(fstring):
    """Emulates Python 3.6+ f-strings"""
    fr = sys._getframe(1)
    kw = fr.f_globals.copy()
    kw.update(fr.f_locals)
    return fstring.format(**kw)

def shell(cmd, ignore_fail=False):
    """Runs shell command. If ignore_fail is set, returns None on failure"""
    try:
       return subprocess.check_call(cmd, shell=True)
    except subprocess.CalledProcessError as exc:
        if ignore_fail:
            return None
        raise

def check_output(command, fail_retcode=1):
    """
    Equivalent to subprocess.check_output(command, shell=True), but will return None
    if the subprocess exits with the given failure retcode
    """
    try:
        return subprocess.check_output(command, shell=True).strip().decode()
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 1:
            return None
        raise

def make_dir(name):
    """Makes directory, if one does not exist. Interpolates '~' in names."""
    name = os.path.expanduser(name)
    if not os.path.exists(name):
        os.mkdir(name)
    return name

def make_radiopadre_dir():
    """Makes ~/.radiopadre directory"""
    return make_dir(iglesia.RADIOPADRE_DIR)

def make_link(src, dest, rm_fr=False):
    """Makes links."""
    if os.path.exists(dest):
        if rm_fr:
            subprocess.call(["rm","-fr",dest])
        else:
            os.unlink(dest)
    os.symlink(os.path.abspath(src), dest)


def find_which(command):
    """
    Returns the equivalent of `which command`, or None is command is not found
    """
    return check_output("which " + command, fail_retcode=1)


def find_unused_port(base=1025, maxtries=10000):
    """Helper function. Finds an unused server port"""
    if base > 65535:
        base = 1025
    for _ in range(maxtries):
        serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            serversocket.bind(("localhost", base))
            serversocket.close()
            return base
        except:
            base += 1
            continue
    raise RuntimeError("unable to find free socket port")

def find_unused_ports(num=1, base=1025):
    """Helper function. Finds N unused ports, returns list"""
    ports = []
    for _ in range(num):
        ports.append(find_unused_port(ports[-1]+1 if ports else base))
    return ports


class Poller(object):
    """Poller class. Poor man's select.poll(). Damn you OS/X and your select.poll will-you-won'y-you bollocks"""
    def __init__ (self):
        self.fdlabels = {}

    def register_file(self, fobj, label):
        self.fdlabels[fobj.fileno()] = label, fobj

    def register_process(self, po, label_stdout='stdout', label_stderr='stderr'):
        self.fdlabels[po.stdout.fileno()] = label_stdout, po.stdout
        self.fdlabels[po.stderr.fileno()] = label_stderr, po.stderr

    def poll(self, timeout=5, verbose=False):
        from .utils import debug
        while True:
            try:
                to_read, _, _ = select.select(self.fdlabels.keys(), [], [], timeout)
                # return on success or timeout
                return [self.fdlabels[fd] for fd in to_read]
            except (select.error, IOError) as ioerr:
                if verbose:
                    debug("poll() exception: {}".format(traceback.format_exc()))
                if hasattr(ioerr, 'args'):
                    err = ioerr.args[0]  # py2
                else:
                    err = ioerr.errno    # py3
                # catch interrupted system call -- return if we have a timeout, else
                # loop again
                if err == errno.EINTR:
                    if timeout is not None:
                        if verbose:
                            debug("poll(): returning")
                        return []
                    if verbose:
                        debug("poll(): retrying")
                else:
                    raise

    def unregister_file(self, fobj):
        if fobj.fileno() in self.fdlabels:
            del self.fdlabels[fobj.fileno()]

    def __contains__(self, fobj):
        return fobj.fileno() in self.fdlabels


class chdir(object):
    """Context manager for changing the current working directory"""
    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)