import os, os.path, stat, subprocess

from  . import message


def ensure_certificate(certfile: str):
    """Ensures radiopadre certifixate exists, creates if it doesn't"""
    if not os.path.exists(certfile):
        message(f"Generating local SSL certificate in {certfile}")
        try:
            subprocess.check_call(f"openssl req -x509 -newkey rsa:2048 -keyout {certfile} -out {certfile} -days 30000 -nodes -subj '/CN=127.0.0.1'", shell=True)
        except subprocess.CalledProcessError as exc:
            message(f"openssl: failed with exit code {exc.returncode}")
            return None
    os.chmod(certfile, stat.S_IREAD)
    return certfile

