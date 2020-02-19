from setuptools import setup
import os

__version__ = "1.0-pre3"

with open("requirements.txt") as stdr:
    install_requires = stdr.readlines()

scripts = ["bin/" + i for i in os.listdir("bin")]

setup(
    name="radiopadre-client",
    version=__version__,
    install_requires=install_requires,
    python_requires='>=2.7',
    author="Oleg Smirnov",
    author_email="osmirnov@gmail.com",
    description=("Radiopadre client-side script"),
    license="MIT",
    keywords="ipython notebook fits dataset resultset visualisation",
    url="http://github.com/ratt-ru/radiopadre-client",
    packages=['radiopadre_client', 'iglesia'],
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
