**Features**

  * Improve significantly pdb performance. With breakpoints, pdb-clone runs just above the speed of the interpreter while pdb runs at 10 to 100 times the speed of the interpreter, see `Performances <http://code.google.com/p/pdb-clone/wiki/Performances>`_.

  * Fix pdb long standing bugs entered in the python issue tracker, see the `News <http://code.google.com/p/pdb-clone/wiki/News>`_.

  * Add a bdb comprehensive test suite (more than 70 tests) and run both pdb and bdb test suites.

  * Three versions of pdb-clone are supported:

    * The *py3* version of pdb-clone runs on python3 from python 3.2 onward.

    * The *py2.7* vesion runs on python 2.7.

    * The *py2.4* version runs on all python versions from 2.4 to 2.7 included. In this version, the *restart* command only handles source code changes made to the main module.

The pdb command line interface remains unchanged. All the versions of pdb-clone implement the most recent python3 features of pdb, as defined in the python3 `pdb documentation`_.

See also the `README <http://code.google.com/p/pdb-clone/wiki/ReadMe>`_.

**Install**

For example, to install the Python 3 version of pdb-clone version 1.5 with pip::

    sudo pip install pdb-clone==1.5.py3 --egg

This requires *pip 1.2* or above. *pip 1.2* fixes `pip issue 3 <https://github.com/pypa/pip/issues/3>`_ by adding the *--egg* option so as not to use *single-version-externally-managed*. Unfortunately *single-version-externally-managed* seems to break all the Python packages based on the standard library *distutils*.


**Usage**

Invoke pdb-clone as a script to debug other scripts. For example::

    $ pdb-clone myscript.py

Or use one of the different ways of running pdb described in the `pdb documentation`_ and replace::

    import pdb

with::

    from pdb_clone import pdb

.. _pdb documentation: http://docs.python.org/3/library/pdb.html

