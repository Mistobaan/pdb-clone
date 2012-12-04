#!/usr/bin/env python3

import sys
import os
import doctest
import importlib
import shutil
import test.support as support
import distutils.core
from distutils.command.install import install as _install
from distutils.command.sdist import sdist as _sdist
from distutils.command.build_scripts import build_scripts as _build_scripts
from unittest import defaultTestLoader

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
        support.failfast = self.stop
        support.verbose = self.detail

    def run (self):
        """Run the test suite."""
        result_tmplt = '{} ... {:d} tests with zero failures'
        optionflags = doctest.REPORT_ONLY_FIRST_FAILURE if self.stop else 0
        cnt = ok = 0
        for test in self.tests:
            cnt += 1
            with support.temp_cwd() as cwd:
                sys.path.insert(0, os.getcwd())
                # Some unittest tests spawn a new instance of pdb.
                shutil.copytree(os.path.join(support.SAVEDCWD, 'pdb_clone'),
                                                os.path.join(cwd, 'pdb_clone'))
                shutil.copyfile(os.path.join(support.SAVEDCWD, 'pdb-clone'),
                                        os.path.join(cwd, 'pdb-clone'))
                abstest = self.testdir + '.' + test
                module = importlib.import_module(abstest)
                suite = defaultTestLoader.loadTestsFromModule(module)
                # Change the module name to allow correct doctest checks.
                module.__name__ = 'test.' + test
                print('{}:'.format(abstest))
                f, t = doctest.testmod(module, verbose=self.detail,
                                                        optionflags=optionflags)
                if f:
                    print('{:d} of {:d} doctests failed'.format(f, t))
                elif t:
                    print(result_tmplt.format('doctest', t))

                try:
                    support.run_unittest(suite)
                except support.TestFailed as msg:
                    print('test', test, 'failed --', msg)
                else:
                    print(result_tmplt.format('unittest',
                                                    suite.countTestCases()))
                    if not f:
                        ok += 1
        failed = cnt - ok
        cnt = failed if failed else ok
        plural = 's' if cnt > 1 else ''
        result = 'failed' if failed else 'ok'
        print('{:d} test{} {}.'.format(cnt, plural, result))

distutils.core.setup(
    cmdclass={'sdist': sdist,
              'build_scripts': build_scripts,
              'install': install,
              'test': Test},
    scripts=SCRIPTS,
    packages=['pdb_clone'],

    # meta-data
    name='pdb-clone',
    version='1.1.py3',
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

