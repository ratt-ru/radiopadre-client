import os.path
import select
import socket
import subprocess
import sys
import time

DEVZERO = open("/dev/zero")
DEVNULL = open("/dev/null", "w")

time0 = time.time()

logfile = None

def enable_logging(logtype, level=1):
    global logfile
    make_dir("~/.radiopadre")
    logname = os.path.expanduser(f"~/.radiopadre/log-{logtype}.txt")
    logfile = open(logname, "wt")


def message(x, prefix='radiopadre_client: ', file=None):
    """Prints message, interpolating globals with .format()"""
    from . import config
    if type(x) is bytes:
        x = x.decode()
    if config.TIMESTAMPS:
        prefix += "{:.2f}: ".format(time.time() - time0)
    print(prefix + x, file=file or sys.stdout)
    if logfile:
        print(time.strftime("%x %X:"), prefix + x, file=logfile)
        logfile.flush()


def bye(x, code=1):
    """Prints message to stderr. Exits with given code"""
    message(x, file=sys.stderr)
    sys.exit(code)


def shell(cmd, ignore_fail=False):
    """Runs shell command. If ignore_fail is set, returns None on failure"""
    try:
       return subprocess.call(cmd, shell=True)
    except subprocess.CalledProcessError as exc:
        if ignore_fail:
            return None
        raise


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


def run_browser(*urls):
    """
    Runs a browser pointed to URL(s), in background if config.BROWSER_BG is True.

    If config.BROWSER_MULTI is set, runs a browser per URL, else feeds all URLs to one browser invocation

    Returns list of processes (in BROWSER_BG mode).
    """
    from . import config
    procs = []
    # open browser if needed
    if config.BROWSER:
        message("Running {} {}\r".format(config.BROWSER, " ".join(urls)))
        message("  if this fails, specify a correct browser invocation command with --browser and rerun,")
        message("  or else browse to the URL given above (\"Browse to URL:\") yourself.")
        if config.BROWSER_MULTI:
            commands = [[config.BROWSER]+list(urls)]
        else:
            commands = [[config.BROWSER, url] for url in urls]

        for command in commands:
            try:
                if config.BROWSER_BG:
                    procs.append(subprocess.Popen(command, stdin=DEVZERO, stdout=sys.stdout, stderr=sys.stderr))
                else:
                    subprocess.call(command, stdout=DEVNULL)
            except OSError as exc:
                if exc.errno == 2:
                    message(f"{config.BROWSER} not found")
                else:
                    raise

    else:
        message("--no-browser given, or browser not set, not opening a browser for you\r")
        message("Please browse to: {}\n".format(" ".join(urls)))

    return procs

def make_git_glone_command(repo):
    if "@" in repo:
        repo, branch = repo.rsplit("@", 1)
    cmd = "git clone -b {config.SERVER_INSTALL_BRANCH} {config.SERVER_INSTALL_REPO} {config.SERVER_INSTALL_PATH}"
