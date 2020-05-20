from setuptools import setup
import os

__version__ = "1.0-pre12"
build_root = os.path.dirname(__file__)

install_requires = ['six', 'psutil']

def readme():
    """Get readme content for package long description"""
    with open(os.path.join(build_root, 'README.rst')) as f:
        return f.read()

scripts = ["bin/run-radiopadre"]

setup(
    name="radiopadre-client",
    version=__version__,
    install_requires=install_requires,
    python_requires='>=2.7',
    author="Oleg Smirnov",
    author_email="osmirnov@gmail.com",
    description=("Radiopadre client-side script"),
    long_description=readme(),
    license="MIT",
    keywords="ipython notebook fits dataset resultset visualisation",
    url="http://github.com/ratt-ru/radiopadre-client",
    packages=['radiopadre_client', 'radiopadre_client.backends', 'iglesia'],
    scripts=scripts,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Topic :: Utilities",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
    ],
)
