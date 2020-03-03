
radiopadre-client
=================


.. image:: https://travis-ci.org/ratt-ru/radiopadre-client.svg?branch=master
   :target: https://travis-ci.org/ratt-ru/radiopadre-client/
   :alt: Build Status


.. image:: https://img.shields.io/pypi/v/radiopadre-client.svg
   :target: https://pypi.python.org/pypi/radiopadre-client/
   :alt: PyPI version shields.io


.. image:: https://img.shields.io/pypi/pyversions/radiopadre-client.svg
   :target: https://pypi.python.org/pypi/radiopadre-client/
   :alt: PyPI pyversions


.. image:: https://img.shields.io/pypi/status/radiopadre-client.svg
   :target: https://pypi.python.org/pypi/radiopadre-client/
   :alt: PyPI status


Your one-stop client-side script to run `radiopadre <https://github.com/ratt-ru/radiopadre>`_ notebooks 
locally and on remote machines.

Quick start:

.. code-block::

   $ pip install radiopadre-client
   $ run-radiopadre interesting_local_directory --auto-init

Or for a remote session, assuming you have ssh access to the host:

.. code-block::

   $ run-radiopadre remote_host:interesting_remote_directory --auto-init

(With any luck, the --auto-init option will cause an automatic installation on the remote end.)

Overview
--------

`Radiopadre <https://github.com/ratt-ru/radiopadre>`_ is a Jupyter 
notebook framework for quick and easy visualization of [radio astronomy, primarily]
data products and pipelines.

**Radiopadre includes integration with** `JS9 <https://js9.si.edu/>`_ **and** `CARTA <https://cartavis.github.io/>`_
**for  live FITS viewing of [remote] FITS files straight from your browser.** 
(In boldface, because this is a pretty neat capability to have!)

Radiopadre is a custom Jupyter kernel, so in principle you could install it
and create radiopadre notebooks directly from a Jupyter session. Some of the 
tight integration with JS9 and CARTA, however, works smoother if you start your sessions
via ``run-radiopadre``\ , which takes care of starting up and stopping appropriate 
helper processes and such.

``run-radiopadre`` can also take care of 
starting radiopadre inside remote Jupyter 
sessions using virtualenv, Docker or Singularity. 
It will manage port forwarding for you, so that your local browser can talk to the  remote Jupyter server (and CARTA/JS9 backends).

Installation notes
------------------

Radiopadre strives to be admin-free. That is, you should not need to bother 
your friendly local sysadmin for most (or all) of the below.

Radiopadre itself (plus the attendant Jupyter etc. dependencies) must 
be installed inside a Python 3.6+ virtual environment. The Jupyter 
notebook server then runs inside this environment.

``run-radiopadre`` does not have (but can) live in the same virtualenv. Since
it has almost no dependencies (and is backwards-compatible down to 
Python 2.7), you can install it directly with ``pip install --user``\ , 
for example. (Or clone the repository and jury-rig an install via ``PATH`` 
and ``PYTHONPATH`` settings.)

Automatic virtualenv install
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If started outside a virtualenv, ``run-radiopadre -V`` will look for a virtualenv 
called ``~/.radiopadre/venv``\ , activate it, and run the Jupyter 
notebook server within.

If ``~/.radiopadre/venv`` does not exist, specify the ``--auto-init`` 
option so that ``run-radiopadre`` can try to create it for you, and install 
radiopadre inside. This is normally the easiest way to bootstrap a new
installation. (Python 3.6+ required.)

Manual virtualenv install
~~~~~~~~~~~~~~~~~~~~~~~~~

If, for whatever reason, you want to install radiopadre in a custom 
virtualenv, then create [a Python 3.6+] one yourself and install radiopadre inside it
following `the instructions <https://github.com/ratt-ru/radiopadre>`_. 
This follows normal pip practice. You can use ``pip install``\ , or else 
``pip install -e`` for an "editable" install from a local directory. Since ``radiopadre`` depends on 
``radiopadre-client``\ , it will automatically install the latter as well 
(though you may well want to pre-install a local version with ``pip install -e``\ ).

If ``run-radiopadre`` is then run inside that virtual environment, it will
look for radiopadre in the same environment. Alternatively, you can still 
run ``run-radiopadre -V`` outside the environment, but specify its location 
with ``--radiopadre-venv``.

The Docker/Singularity backends
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you don't want to or can't use virtual environments (don't have Python 3.6, 
for example), you can run radiopadre notebooks inside a Docker or Singularity 
container. Images are provided on dockerhub. 

To use containers, invoke ``run-singularity -D`` or ``run-singularity -S``. 
This will automatically download the required image from dockerhub, if not
already available on the system.

Remote installation
~~~~~~~~~~~~~~~~~~~

To run remote radiopadre sessions, the remote end must have either:

(a) have a full radiopadre install inside ``.radiopadre/venv`` (or 
another custom environment);

(b) have radiopadre-client alone installed inside ``.radiopadre/venv``\ , 
and support Docker or Singularity;

(c) or have ``run-radiopadre`` somewhere in the default path (i.e. a 
``pip install -e``\ , or a jury-rigged install), and support Docker 
or Singularity.

Case (a) requires Python 3.6+, and allows ``run-radiopadre -V``\ , while (b) or 
(c) can make do with Python as low as 2.7, but require using 
``run-radiopadre -D`` or ``run-radiopadre -S``.

If you've got nothing at all installed on the remote, you can try ``--auto-init`` 
to bootstrap an installation. At present, this will try to set up case (a), so 
Python 3.6+ and virtualenv is required. For funky/older systems without, 
you'll have to set up (b) or (c) by hand. 

Examples
--------

.. code-block::

   $ run-radiopadre -V .

Uses the virtualenv backend (-V). Activates the virtual environment, 
runs the Jupyter notebook server inside with "." as the working directory,
and drives a browser to it (see ``--browser`` option). 
If no notebooks are present, creates a minimalistic starter notebook 
called ``radiopadre-default.ipynb``. If a notebook called 
``radiopadre-auto.ipynb`` is present, opens it automatically (see 
``--auto-load`` option.) Also opens the CARTA browser in a separate tab.

.. code-block::

   $ run-radiopadre -V remote_box:project

Uses SSH to connect to ``remote_box``. Uses the virtualenv backend 
(-V). Activates the virtual environment, runs the Jupyter notebook 
server inside with ``~/project`` as the working directory. Sets up port
forwarding so that a local browser can talk to Jupyter on the remote end.
Drives a local browser to the appropriate URL. If no notebooks are 
present in ``project``\ , creates a minimalistic starter notebook 
called ``radiopadre-default.ipynb``. Opens ``radiopadre-auto.ipynb`` 
automatically.

.. code-block::

   $ run-radiopadre -D remote_box:project --auto-init -u

Uses SSH to connect to ``remote_box``. If ``run-radiopadre`` is not 
found on the remote, tries to bootstrap an installation.
If successful, uses the Docker backend (-D). Checks for an updated 
version of the Docker image (-u) and downloads it if needed.
Runs the container with a Jupyter notebook 
server inside, with ``~/project`` as the working directory. Sets up port
forwarding so that a local browser can talk to Jupyter inside
the remote container. Drives a local browser to the appropriate URL. If no notebooks are 
present in ``project``\ , creates a minimalistic starter notebook 
called ``radiopadre-default.ipynb``. Opens ``radiopadre-auto.ipynb`` 
automatically.

Persistent configuration
------------------------

Combinations of command-line settings can be made into 
persistent defaults by saving them to a config file called 
``~/.config/radiopadre-client``. This is useful when you
work with different remote hosts with different setups. The 
``-s`` option saves the current combination of command-line
options to a config section called ``[host]``. The ``-e`` option
saves them to a section called ``[host:path]``. For 
example, the result of the following 
three runs of ``run-radiopadre``\ :

.. code-block::

   $ run-radiopadre -D box1:project1 -s
   $ run-radiopadre -V box1:project2 -e
   $ run-radiopadre -S box2:project2 -s

is the following config file:

.. code-block::

   [box1]
   backend = docker

   [box1:project1]
   backend = venv

   [box2:project2]
   backend = singularity

The contents of the config file **modify** the relevant default 
settings. If ``run-radiopadre`` is then run without an explicit 
-V, -D, or -S option for a matching host (and possibly path), 
the default backend setting is taken from the config file.

In case of confusion, look at messages at the start of 
``run-radiopadre``. These tell you which settings come from
the config file, and which from the command line.

Note also that some options (e.g. ``--update`` and 
``--auto-init``\ ) are considered one-off settings, and are 
not saved to the config file.

Recent sessions
---------------

Invoking ``run-radiopadre`` without arguments gives you a list 
of the five most recent sessions, and lets you invoke one
of them again by entering its number.

Updates and bleeding-edge installs
----------------------------------

The ``--client-install-pip`` and ``--server-install-pip`` determine 
what package names are passed to pip install when 
``--auto-init`` is invoked. The default values are simply
``radiopadre-client`` and ``radiopadre``. Whenever ``--update`` 
is given, ``pip --upgrade`` is invoked to upgrade 
these packages. You can pin a particular release by including
a pip version specifier, e.g. ``--radiopadre-client radiopadre-client==1.0``.

~Maso~ advanced users may want to track the git repository versions
rather than pip releases. This can be done by setting
the following options, adjusting their values as appropriate: 

.. code-block::

   --client-install-path ~/radiopadre-client
   --client-install-repo https://github.com/ratt-ru/radiopadre-client.git
   --client-install-branch master
   --server-install-path ~/radiopadre
   --server-install-repo https://github.com/ratt-ru/radiopadre.git
   --server-install-branch master

These options override the pip settings. Rather than installing from 
PyPI, the packages are then cloned from the specified repositories 
into the specified directories, and installed into the virtual environment
with ``pip install -e``. When ``--update`` is given, ``git pull``
is invoked to update the sources.

If using Docker or Singularity, you will probably want to combine this 
with the ``--container-dev`` option. If set, this will mount the 
client/server install paths inside the container, thus overriding 
the potentially older versions installed inside the image. 
