import os.path
import select
import socket
import subprocess
import sys

def message(x, prefix='radiopadre_client: ', file=None, raw=False):
    """Prints message, interpolating globals with .format()"""
    if not raw:
        x = x.format(**globals())
    print(prefix + x, file=file or sys.stdout)


def bye(x, code=1):
    """Prints message, interpolating globals with .format(). Exits with given code"""
    message(x, file=sys.stderr)
    sys.exit(code)


def shell(cmd):
    """Runs shell command, interpolating globals with .format()"""
    return subprocess.call(cmd.format(**globals()), shell=True)


def make_dir(name):
    """Makes directory, if one does not exist. Interpolates '~' in names."""
    name = os.path.expanduser(name)
    if not os.path.exists(name):
        os.mkdir(name)
    return name


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
    try:
        binary = subprocess.check_output("which {}".format(command), shell=True).strip()
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 1:
            return None
        raise
    return binary.decode()


def find_unused_port (base, maxtries=10000):
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


class Poller(object):
    """Poller class. Poor man's select.poll(). Damn you OS/X and your select.poll will-you-won'y-you bollocks"""
    def __init__ (self):
        self.fdlabels = {}

    def register_file(self, fobj, label):
        self.fdlabels[fobj.fileno()] = label, fobj

    def register_process(self, po, label_stdout='', label_stderr=''):
        self.fdlabels[po.stdout.fileno()] = label_stdout, po.stdout
        self.fdlabels[po.stderr.fileno()] = label_stderr, po.stderr

    def poll(self, timeout=5):
        to_read, _, _ = select.select(self.fdlabels.keys(), [], [], timeout)
        return [self.fdlabels[fd] for fd in to_read]

    def unregister_file(self, fobj):
        if fobj.fileno() in self.fdlabels:
            del self.fdlabels[fobj.fileno()]

    def __contains__(self, fobj):
        return fobj.fileno() in self.fdlabels


DEVZERO = open("/dev/zero")
DEVNULL = open("/dev/null", "w")