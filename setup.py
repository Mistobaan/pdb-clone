#!/usr/bin/env python

import sys
import os
import doctest
import shutil
import test.test_support as support
import distutils.core
from distutils.errors import *
from distutils.command.install import install as _install
from distutils.command.sdist import sdist as _sdist
from distutils.command.build_scripts import build_scripts as _build_scripts
from distutils.command.build_ext import build_ext as _build_ext
from unittest import defaultTestLoader

from pdb_clone import __version__

DESCRIPTION = 'A clone of pdb, the standard library python debugger.'
SCRIPTS = ['pdb-clone']

# Installation path of pdb-clone lib.
pythonpath = None

class install(_install):
    def run(self):
        global pythonpath
        pythonpath = self.install_purelib
        _install.run(self)

class build_scripts(_build_scripts):
    def run(self):
        """Add pythonpath to pdb-clone in a 'home scheme' installation."""
        if pythonpath is not None and pythonpath not in sys.path:
            self.executable += '\n\nimport sys\n'
            self.executable += "sys.path.append('" + pythonpath + "')\n"
        _build_scripts.run(self)

class sdist(_sdist):
    """Subclass sdist to force copying symlinked files."""
    def copy_file(self, infile, outfile, preserve_mode=1, preserve_times=1,
            link=None, level=1):
        return distutils.core.Command.copy_file(self, infile, outfile,
                preserve_mode=preserve_mode, preserve_times=preserve_times,
                link=None, level=level)

class build_ext(_build_ext):
    def run(self):
        try:
            _build_ext.run(self)
        except (CCompilerError, DistutilsError, CompileError):
            self.warn('\n\n*** Building the _bdb extension failed. ***')

class Test(distutils.core.Command):
    description = 'run the test suite'

    user_options = [
        ('tests=', 't',
            'run a comma separated list of tests, for example             '
            '"--tests=pdb,bdb"; all the tests are run when this option'
            ' is not present'),
        ('prefix=', 'p', 'run only unittest methods whose name starts'
            ' with this prefix'),
        ('stop', 's', 'stop at the first test failure or error'),
        ('detail', 'd', 'detailed test output, each test case is printed'),
    ]

    def initialize_options(self):
        self.testdir = 'testsuite'
        self.tests = ''
        self.prefix = 'test'
        self.stop = False
        self.detail = False

    def finalize_options(self):
        self.tests = (['test_' + t for t in self.tests.split(',') if t] or
            [t[:-3] for t in os.listdir(self.testdir) if
                t.startswith('test_') and t.endswith('.py')])
        defaultTestLoader.testMethodPrefix = self.prefix
        support.verbose = self.detail

    def run (self):
        """Run the test suite."""
        import testsuite.test_pdb
        import testsuite.test_bdb
        result_tmplt = '%s ... %d tests with zero failures'
        optionflags = 0
        if self.stop:
            optionflags = doctest.REPORT_ONLY_FIRST_FAILURE
        saved_dir = os.getcwd()
        tmp_path = os.path.join(saved_dir, 'tempcwd')
        cnt = ok = 0
        for test in self.tests:
            cnt += 1
            try:
                os.mkdir(tmp_path)
                os.chdir(tmp_path)
                sys.path.insert(0, os.getcwd())
                # Some unittest tests spawn a new instance of pdb.
                shutil.copytree(os.path.join(saved_dir, 'pdb_clone'),
                                        os.path.join(tmp_path, 'pdb_clone'))
                shutil.copyfile(os.path.join(saved_dir, 'pdb-clone'),
                                        os.path.join(tmp_path, 'pdb-clone'))
                abstest = self.testdir + '.' + test
                module = sys.modules[abstest]
                suite = defaultTestLoader.loadTestsFromModule(module)
                # Change the module name to allow correct doctest checks.
                module.__name__ = 'test.' + test
                print '%s:' % abstest
                f, t = doctest.testmod(module, verbose=self.detail,
                                                        optionflags=optionflags)
                if f:
                    print '%d of %d doctests failed' % (f, t)
                elif t:
                    print result_tmplt % ('doctest', t)

                try:
                    tests = [t for t in suite]
                    support.run_unittest(*tests)
                except support.TestFailed, msg:
                    print 'test', test, 'failed --', msg
                else:
                    print result_tmplt % ('unittest',
                                                    suite.countTestCases())
                    if not f:
                        ok += 1
            finally:
                os.chdir(saved_dir)
                if os.path.exists(tmp_path):
                    shutil.rmtree(tmp_path)

        failed = cnt - ok
        cnt = ok
        if failed:
            cnt = failed
        plural = ''
        if cnt > 1:
            plural = 's'
        result = 'ok'
        if failed:
            result = 'failed'
        print '%d test%s %s.' % (cnt, plural, result)

_bdb = distutils.core.Extension('_bdb', sources=['pdb_clone/_bdbmodule.c'])

distutils.core.setup(
    cmdclass={'sdist': sdist,
              'build_scripts': build_scripts,
              'install': install,
              'build_ext': build_ext,
              'test': Test},
    scripts=SCRIPTS,
    ext_modules = [_bdb],
    packages=['pdb_clone'],

    # meta-data
    name='pdb-clone',
    version=__version__,
    description=DESCRIPTION,
    long_description=DESCRIPTION,
    platforms='all',
    license='GNU GENERAL PUBLIC LICENSE Version 2',
    author='Xavier de Gaye',
    author_email='xdegaye at users dot sourceforge dot net',
    url='http://code.google.com/p/pdb-clone/',
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3'
    ],
)

