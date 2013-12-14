# A test suite for pdb; not very comprehensive at the moment.

import imp
from pdb_clone import pdb
import sys
import os
import unittest
import subprocess
import textwrap

from test import test_support as support
# This little helper class is essential for testing pdb under doctest.
from test.test_doctest import _FakeInput

# Some unittest tests spawn a new instance of pdb.
prev_pypath = []
if 'PYTHONPATH' in os.environ:
    prev_pypath = [os.environ['PYTHONPATH']]
os.environ['PYTHONPATH'] = os.pathsep.join(prev_pypath +
                                           [os.path.abspath('pdb_clone')])

MODULE_CO_NAME = sys._getframe().f_code.co_name

def unlink(filename):
    try:
        os.unlink(filename)
    except OSError:
        pass


class PdbTestInput(object):
    """Context manager that makes testing Pdb in doctests easier."""

    def __init__(self, input):
        self.input = input

    def __enter__(self):
        self.real_stdin = sys.stdin
        sys.stdin = _FakeInput(self.input)

    def __exit__(self, *exc):
        sys.stdin = self.real_stdin
        sys.settrace(None)


def test_pdb_displayhook():
    """This tests the custom displayhook for pdb.

    >>> def test_function(foo, bar):
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     x = 1

    >>> pti = PdbTestInput([
    ...     'foo',
    ...     'bar',
    ...     'for i in range(5): print i',
    ...     'continue',
    ... ])
    >>> try:
    ...     pti.__enter__()
    ...     test_function(1, None)
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_pdb_displayhook[0]>(3)test_function()
    -> x = 1
    (Pdb) foo
    1
    (Pdb) bar
    (Pdb) for i in range(5): print i
    0
    1
    2
    3
    4
    (Pdb) continue
    """


def test_pdb_basic_commands():
    """Test the basic commands of pdb.

    >>> def test_function_2(foo, bar='default'):
    ...     print foo
    ...     for i in range(5):
    ...         print i
    ...     print bar
    ...     for i in range(10):
    ...         never_executed
    ...     print 'after for'
    ...     print '...'
    ...     return foo.upper()

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     ret = test_function_2('baz')
    ...     print ret

    >>> pti = PdbTestInput([
    ...     'step',       # entering the function call
    ...     'args',       # display function args
    ...     'list',       # list function source
    ...     'bt',         # display backtrace
    ...     'up',         # step up to test_function()
    ...     'down',       # step down to test_function_2() again
    ...     'next',       # stepping to print foo
    ...     'next',       # stepping to the for loop
    ...     'step',       # stepping into the for loop
    ...     'until',      # continuing until out of the for loop
    ...     'next',       # executing the print bar
    ...     'jump 8',     # jump over second for loop
    ...     'return',     # return out of function
    ...     'retval',     # display return value
    ...     'continue',
    ... ])
    >>> try:   # doctest: +ELLIPSIS, +NORMALIZE_WHITESPACE
    ...     pti.__enter__()
    ...     test_function()
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_pdb_basic_commands[1]>(3)test_function()
    -> ret = test_function_2('baz')
    (Pdb) step
    --Call--
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(1)test_function_2()
    -> def test_function_2(foo, bar='default'):
    (Pdb) args
    foo = 'baz'
    bar = 'default'
    (Pdb) list
      1  ->     def test_function_2(foo, bar='default'):
      2             print foo
      3             for i in range(5):
      4                 print i
      5             print bar
      6             for i in range(10):
      7                 never_executed
      8             print 'after for'
      9             print '...'
     10             return foo.upper()
    [EOF]
    (Pdb) bt
    ...
    -> test_function()
      <doctest test.test_pdb.test_pdb_basic_commands[1]>(3)test_function()
    -> ret = test_function_2('baz')
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(1)test_function_2()
    -> def test_function_2(foo, bar='default'):
    (Pdb) up
    > <doctest test.test_pdb.test_pdb_basic_commands[1]>(3)test_function()
    -> ret = test_function_2('baz')
    (Pdb) down
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(1)test_function_2()
    -> def test_function_2(foo, bar='default'):
    (Pdb) next
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(2)test_function_2()
    -> print foo
    (Pdb) next
    baz
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(3)test_function_2()
    -> for i in range(5):
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(4)test_function_2()
    -> print i
    (Pdb) until
    0
    1
    2
    3
    4
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(5)test_function_2()
    -> print bar
    (Pdb) next
    default
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(6)test_function_2()
    -> for i in range(10):
    (Pdb) jump 8
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(8)test_function_2()
    -> print 'after for'
    (Pdb) return
    after for
    ...
    --Return--
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(10)test_function_2()->'BAZ'
    -> return foo.upper()
    (Pdb) retval
    'BAZ'
    (Pdb) continue
    BAZ
    """


def test_pdb_breakpoint_commands():
    """Test basic commands related to breakpoints.

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     print 1
    ...     print 2
    ...     print 3
    ...     print 4

    First, need to clear bdb state that might be left over from previous tests.
    Otherwise, the new breakpoints might get assigned different numbers.

    >>> from pdb_clone.bdb import Breakpoint
    >>> Breakpoint.next = 1
    >>> Breakpoint.bplist = {}
    >>> Breakpoint.bpbynumber = [None]

    Now test the breakpoint commands.  NORMALIZE_WHITESPACE is needed because
    the breakpoint list outputs a tab for the "stop only" and "ignore next"
    lines, which we don't want to put in here.

    >>> pti = PdbTestInput([
    ...     'break 3',
    ...     'disable 1',
    ...     'ignore 1 10',
    ...     'condition 1 1 < 2',
    ...     'break 4',
    ...     'break 4',
    ...     'break',
    ...     'clear 3',
    ...     'break',
    ...     'condition 1',
    ...     'enable 1',
    ...     'clear 1',
    ...     'commands 2',
    ...     'print 42',
    ...     'end',
    ...     'continue',  # will stop at breakpoint 2 (line 4)
    ...     'clear',     # clear all!
    ...     'y',
    ...     'tbreak 5',
    ...     'continue',  # will stop at temporary breakpoint
    ...     'break',     # make sure breakpoint is gone
    ...     'continue',
    ... ])
    >>> try:  # doctest: +NORMALIZE_WHITESPACE
    ...     pti.__enter__()
    ...     test_function()
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>(3)test_function()
    -> print 1
    (Pdb) break 3
    Breakpoint 1 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:3
    (Pdb) disable 1
    Disabled breakpoint 1 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:3
    (Pdb) ignore 1 10
    Will ignore next 10 crossings of breakpoint 1.
    (Pdb) condition 1 1 < 2
    New condition set for breakpoint 1.
    (Pdb) break 4
    Breakpoint 2 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:4
    (Pdb) break 4
    Breakpoint 3 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:4
    (Pdb) break
    Num Type         Disp Enb   Where
    1   breakpoint   keep no    at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:3
            stop only if 1 < 2
            ignore next 10 hits
    2   breakpoint   keep yes   at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:4
    3   breakpoint   keep yes   at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:4
    (Pdb) clear 3
    Deleted breakpoint 3 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:4
    (Pdb) break
    Num Type         Disp Enb   Where
    1   breakpoint   keep no    at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:3
            stop only if 1 < 2
            ignore next 10 hits
    2   breakpoint   keep yes   at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:4
    (Pdb) condition 1
    Breakpoint 1 is now unconditional.
    (Pdb) enable 1
    Enabled breakpoint 1 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:3
    (Pdb) clear 1
    Deleted breakpoint 1 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:3
    (Pdb) commands 2
    (com) print 42
    (com) end
    (Pdb) continue
    1
    42
    > <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>(4)test_function()
    -> print 2
    (Pdb) clear
    Clear all breaks? y
    Deleted breakpoint 2 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:4
    (Pdb) tbreak 5
    Breakpoint 4 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:5
    (Pdb) continue
    2
    Deleted breakpoint 4 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:5
    > <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>(5)test_function()
    -> print 3
    (Pdb) break
    (Pdb) continue
    3
    4
    """


def do_nothing():
    pass

def do_something():
    print 42

def test_list_commands():
    """Test the list and source commands of pdb.

    >>> def test_function_2(foo):
    ...     import testsuite.test_pdb
    ...     testsuite.test_pdb.do_nothing()
    ...     'some...'
    ...     'more...'
    ...     'code...'
    ...     'to...'
    ...     'make...'
    ...     'a...'
    ...     'long...'
    ...     'listing...'
    ...     'useful...'
    ...     '...'
    ...     '...'
    ...     return foo

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     ret = test_function_2('baz')

    >>> pti = PdbTestInput([
    ...     'list',      # list first function
    ...     'step',      # step into second function
    ...     'list',      # list second function
    ...     'list',      # continue listing to EOF
    ...     'list 1,3',  # list specific lines
    ...     'list x',    # invalid argument
    ...     'next',      # step to import
    ...     'next',      # step over import
    ...     'step',      # step into do_nothing
    ...     'longlist',  # list all lines
    ...     'source do_something',  # list all lines of function
    ...     'source fooxxx',        # something that doesn't exit
    ...     'continue',
    ... ])
    >>> try:   # doctest: +ELLIPSIS, +NORMALIZE_WHITESPACE
    ...     pti.__enter__()
    ...     test_function()
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_list_commands[1]>(3)test_function()
    -> ret = test_function_2('baz')
    (Pdb) list
      1         def test_function():
      2             from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
      3  ->         ret = test_function_2('baz')
    [EOF]
    (Pdb) step
    --Call--
    > <doctest test.test_pdb.test_list_commands[0]>(1)test_function_2()
    -> def test_function_2(foo):
    (Pdb) list
      1  ->     def test_function_2(foo):
      2             import testsuite.test_pdb
      3             testsuite.test_pdb.do_nothing()
      4             'some...'
      5             'more...'
      6             'code...'
      7             'to...'
      8             'make...'
      9             'a...'
     10             'long...'
     11             'listing...'
    (Pdb) list
     12             'useful...'
     13             '...'
     14             '...'
     15             return foo
    [EOF]
    (Pdb) list 1,3
      1  ->     def test_function_2(foo):
      2             import testsuite.test_pdb
      3             testsuite.test_pdb.do_nothing()
    (Pdb) list x
    *** ...
    (Pdb) next
    > <doctest test.test_pdb.test_list_commands[0]>(2)test_function_2()
    -> import testsuite.test_pdb
    (Pdb) next
    > <doctest test.test_pdb.test_list_commands[0]>(3)test_function_2()
    -> testsuite.test_pdb.do_nothing()
    (Pdb) step
    --Call--
    > ...test_pdb.py(...)do_nothing()
    -> def do_nothing():
    (Pdb) longlist
    ...  ->     def do_nothing():
    ...             pass
    (Pdb) source do_something
    ...         def do_something():
    ...             print 42
    (Pdb) source fooxxx
    *** ...
    (Pdb) continue
    """


def test_post_mortem():
    """Test post mortem traceback debugging.

    >>> def test_function_2():
    ...     try:
    ...         1/0
    ...     finally:
    ...         print 'Exception!'

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     test_function_2()
    ...     print 'Not reached.'

    >>> pti = PdbTestInput([
    ...     'next',      # step over exception-raising call
    ...     'bt',        # get a backtrace
    ...     'list',      # list code of test_function()
    ...     'down',      # step into test_function_2()
    ...     'list',      # list code of test_function_2()
    ...     'continue',
    ... ])
    >>> try:  # doctest: +ELLIPSIS, +NORMALIZE_WHITESPACE
    ...     pti.__enter__()
    ...     try:
    ...         test_function()
    ...     except ZeroDivisionError:
    ...         print 'Correctly reraised.'
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_post_mortem[1]>(3)test_function()
    -> test_function_2()
    (Pdb) next
    Exception!
    --Exception--
    ZeroDivisionError: integer division or modulo by zero
    > <doctest test.test_pdb.test_post_mortem[1]>(3)test_function()
    -> test_function_2()
    (Pdb) bt
    ...
    -> test_function()
    > <doctest test.test_pdb.test_post_mortem[1]>(3)test_function()
    -> test_function_2()
      <doctest test.test_pdb.test_post_mortem[0]>(3)test_function_2()
    -> 1/0
    (Pdb) list
      1         def test_function():
      2             from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
      3  ->         test_function_2()
      4             print 'Not reached.'
    [EOF]
    (Pdb) down
    > <doctest test.test_pdb.test_post_mortem[0]>(3)test_function_2()
    -> 1/0
    (Pdb) list
      1         def test_function_2():
      2             try:
      3  >>             1/0
      4             finally:
      5  ->             print 'Exception!'
    [EOF]
    (Pdb) continue
    Correctly reraised.
    """


def test_pdb_skip_modules():
    """This illustrates the simple case of module skipping.

    >>> def skip_module():
    ...     import string
    ...     from pdb_clone import pdb
    ...     pdb.Pdb(skip=['stri*'], nosigint=True).set_trace()
    ...     string.capwords('FOO')

    >>> pti = PdbTestInput([
    ...     'step',
    ...     'continue',
    ... ])
    >>> try:
    ...     pti.__enter__()
    ...     skip_module()
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_pdb_skip_modules[0]>(5)skip_module()
    -> string.capwords('FOO')
    (Pdb) step
    --Return--
    > <doctest test.test_pdb.test_pdb_skip_modules[0]>(5)skip_module()->None
    -> string.capwords('FOO')
    (Pdb) continue
    """


# Module for testing skipping of module that makes a callback
mod = imp.new_module('module_to_skip')
exec('def foo_pony(callback): x = 1; callback(); return None', mod.__dict__)


def test_pdb_skip_modules_with_callback():
    """This illustrates skipping of modules that call into other code.

    >>> def skip_module():
    ...     def callback():
    ...         return None
    ...     from pdb_clone import pdb
    ...     pdb.Pdb(skip=['module_to_skip*'], nosigint=True).set_trace()
    ...     mod.foo_pony(callback)

    >>> pti = PdbTestInput([
    ...     'step',
    ...     'step',
    ...     'step',
    ...     'step',
    ...     'step',
    ...     'continue',
    ... ])
    >>> try:  # doctest: +ELLIPSIS
    ...     pti.__enter__()
    ...     skip_module()
    ...     pass  # provides something to "step" to
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_pdb_skip_modules_with_callback[0]>(6)skip_module()
    -> mod.foo_pony(callback)
    (Pdb) step
    --Call--
    > <doctest test.test_pdb.test_pdb_skip_modules_with_callback[0]>(2)callback()
    -> def callback():
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_skip_modules_with_callback[0]>(3)callback()
    -> return None
    (Pdb) step
    --Return--
    > <doctest test.test_pdb.test_pdb_skip_modules_with_callback[0]>(3)callback()->None
    -> return None
    (Pdb) step
    --Return--
    > <doctest test.test_pdb.test_pdb_skip_modules_with_callback[0]>(6)skip_module()->None
    -> mod.foo_pony(callback)
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_skip_modules_with_callback[2]>(4)...()
    -> pass  # provides something to "step" to
    (Pdb) continue
    """


def test_pdb_continue_in_bottomframe():
    """Test that "continue" and "next" work properly in bottom frame (issue #5294).

    >>> def test_function():
    ...     import sys; from pdb_clone import pdb; inst = pdb.Pdb(nosigint=True)
    ...     inst.set_trace()
    ...     inst.botframe = sys._getframe()  # hackery to get the right botframe
    ...     print 1
    ...     print 2
    ...     print 3
    ...     print 4

    >>> pti = PdbTestInput([
    ...     'next',
    ...     'break 7',
    ...     'continue',
    ...     'next',
    ...     'continue',
    ...     'continue',
    ... ])
    >>> try:  # doctest: +ELLIPSIS
    ...     pti.__enter__()
    ...     test_function()
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>(4)test_function()
    -> inst.botframe = sys._getframe()  # hackery to get the right botframe
    (Pdb) next
    > <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>(5)test_function()
    -> print 1
    (Pdb) break 7
    Breakpoint ... at <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>:7
    (Pdb) continue
    1
    2
    > <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>(7)test_function()
    -> print 3
    (Pdb) next
    3
    > <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>(8)test_function()
    -> print 4
    (Pdb) continue
    4
    """


def pdb_invoke(method, arg):
    """Run pdb.method(arg)."""
    from pdb_clone import pdb
    getattr(pdb.Pdb(nosigint=True), method)(arg)


def test_pdb_run_with_incorrect_argument():
    """Testing run and runeval with incorrect first argument.

    >>> pti = PdbTestInput(['continue',])
    >>> try:
    ...     pti.__enter__()
    ...     pdb_invoke('run', lambda x: x)
    ... finally:
    ...     pti.__exit__()
    Traceback (most recent call last):
    TypeError: exec: arg 1 must be a string, file, or code object

    >>> pti = PdbTestInput(['continue',])
    >>> try:
    ...     pti.__enter__()
    ...     pdb_invoke('runeval', lambda x: x)
    ... finally:
    ...     pti.__exit__()
    Traceback (most recent call last):
    TypeError: eval() arg 1 must be a string or code object
    """


def test_pdb_run_with_code_object():
    """Testing run and runeval with code object as a first argument.

    >>> pti = PdbTestInput(['step','x', 'continue'])
    >>> try:  # doctest: +ELLIPSIS
    ...     pti.__enter__()
    ...     pdb_invoke('run', compile('x=1', '<string>', 'exec'))
    ... finally:
    ...     pti.__exit__()
    > <string>(1)...()...
    (Pdb) step
    --Return--
    > <string>(1)...()->None
    (Pdb) x
    1
    (Pdb) continue

    >>> pti = PdbTestInput(['x', 'continue'])
    >>> try:  # doctest: +ELLIPSIS
    ...     pti.__enter__()
    ...     x=0
    ...     pdb_invoke('runeval', compile('x+1', '<string>', 'eval'))
    ... finally:
    ...     pti.__exit__()
    > <string>...()->None
    (Pdb) x
    1
    (Pdb) continue
    """


def test_pdb_set_frame_locals():
    """This tests setting local variables.

    >>> def foo(n):
    ...     x = n
    ...     bar(x)
    >>> def bar(n):
    ...     y = n + 1
    ...     from pdb_clone import pdb; pdb.Pdb().set_trace()
    ...     z = y

    >>> pti = PdbTestInput([
    ...     'y',
    ...     '!y = 42',
    ...     'y',
    ...     'up',
    ...     'x',
    ...     '!x = 55',
    ...     'x',
    ...     'down',
    ...     'y',
    ...     'step',
    ...     'y',
    ...     'continue'
    ... ])
    >>> try:
    ...     pti.__enter__()
    ...     foo(1)
    ... finally:
    ...     pti.__exit__()
    > <doctest test.test_pdb.test_pdb_set_frame_locals[1]>(4)bar()
    -> z = y
    (Pdb) y
    2
    (Pdb) !y = 42
    (Pdb) y
    42
    (Pdb) up
    > <doctest test.test_pdb.test_pdb_set_frame_locals[0]>(3)foo()
    -> bar(x)
    (Pdb) x
    1
    (Pdb) !x = 55
    (Pdb) x
    1
    (Pdb) down
    > <doctest test.test_pdb.test_pdb_set_frame_locals[1]>(4)bar()
    -> z = y
    (Pdb) y
    42
    (Pdb) step
    --Return--
    > <doctest test.test_pdb.test_pdb_set_frame_locals[1]>(4)bar()->None
    -> z = y
    (Pdb) y
    42
    (Pdb) continue
    """


def normalize(result, filename='', strip_bp_lnum=False):
    """Normalize a test result."""
    lines = []
    for line in result.splitlines():
        while line.startswith('(Pdb) ') or line.startswith('(com) '):
            line = line[6:]
        words = line.split()
        line = []
        # Replace tabs with spaces
        for word in words:
            if filename:
                idx = word.find(filename)
                # Remove the filename prefix
                if idx > 0:
                    word = word[idx:]
                if idx >=0 and strip_bp_lnum:
                    idx = word.find(':')
                    # Remove the ':' separator and breakpoint line number
                    if idx > 0:
                        word = word[:idx]
            line.append(word)
        line = ' '.join(line)
        lines.append(line.strip())
    return '\n'.join(lines)

class PdbTestCase(unittest.TestCase):
    pass

class IssueTestCase(PdbTestCase):

    def __init__(self, methodName='runTest'):
        unittest.TestCase.__init__(self, methodName)
        self._cleanups = []

    def tearDown(self):
        while self._cleanups:
            function, args, kwargs = self._cleanups.pop(-1)
            try:
                function(*args, **kwargs)
            except:
                pass

    def addCleanup(self, function, *args, **kwargs):
        self._cleanups.append((function, args, kwargs))

    def run_pdb(self, script, commands, filename):
        """Run 'script' lines with pdb and the pdb 'commands'."""
        f = None
        try:
            f = open(filename, 'w')
            f.write(textwrap.dedent(script))
        finally:
            if f:
                f.close()
        self.addCleanup(unlink, filename)
        cmd = [sys.executable, 'pdb-clone', filename]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                   stdin=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate(commands)
        return stdout, stderr

    def test_issue13183(self):
        script = """
            from bar import bar

            def foo():
                bar()

            def nope():
                pass

            def foobar():
                foo()
                nope()

            foobar()
        """
        commands = """
            from bar import bar
            break bar
            continue
            step
            step
            quit
        """
        bar = """
            def bar():
                pass
        """
        f = None
        try:
            f = open('bar.py', 'w')
            f.write(textwrap.dedent(bar))
        finally:
            if f:
                f.close()
        self.addCleanup(unlink, 'bar.py')
        stdout, stderr = self.run_pdb(script, commands, 'main.py')
        self.assertTrue(
            'main.py(5)foo()->None' in stdout,
            'Fail to step into the caller after a return')

    def test_issue14789(self):
        script = """
            def bar(a):
                x = 1

            bar(10)
            bar(20)
        """
        commands = """
            break bar
            commands 1
            print a
            end
            ignore 1 1
            break bar
            commands 2
            print a + 1
            end
            ignore 2 1
            continue
            break
            quit
        """
        expected = """
            > main.py(2)%s()
            -> def bar(a):
            Breakpoint 1 at main.py:2
            Will ignore next 1 crossing of breakpoint 1.
            Breakpoint 2 at main.py:2
            Will ignore next 1 crossing of breakpoint 2.
            20
            21
            > main.py(3)bar()
            -> x = 1
            Num Type         Disp Enb   Where
            1 breakpoint keep yes at main.py:2
                    breakpoint already hit 2 times
            2 breakpoint keep yes at main.py:2
                    breakpoint already hit 2 times
        """ % MODULE_CO_NAME
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(stdout, filename)
        expected = normalize(expected)
        expected = expected.strip()
        self.assertTrue(expected in stdout,
            '\n\nExpected:\n%s\nGot:\n%s\n'
            'Fail to handle two breakpoints set on the same line.' % (
                expected, stdout))

    def test_set_breakpoint_by_function_name(self):
        script = """
            class C:
                c_foo = 1

            class D:
                def d_foo(self):
                    pass

            def foo():
                pass

            not_a_function = 1
            foo()
        """
        commands = """
            break C
            break C.c_foo
            break D.d_foo
            break foo
            break not_a_function
            break len
            break logging.handlers.SocketHandler.close
            continue
            break C
            break C.c_foo
            break D.d_foo
            break foo
            break not_a_function
            quit
        """
        expected = ('''
            > main.py(2)%s()
            -> class C:
            *** Bad name: "C".
            *** Bad name: "C.c_foo".
            Breakpoint 1 at main.py:6
            Breakpoint 2 at main.py:9
            *** Bad name: "not_a_function".
            *** Not a function or a built-in: "len"
            Breakpoint 3 at handlers.py:<LINE_NUMBER>
            > main.py(10)foo()
            -> pass
            *** Bad name: "C".
            *** Not a function or a built-in: "C.c_foo"
            Breakpoint 4 at main.py:6
            Breakpoint 5 at main.py:9
            *** Not a function or a built-in: "not_a_function"
            ''' % MODULE_CO_NAME)
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(normalize(
                    stdout, 'handlers.py', strip_bp_lnum=True), filename)
        expected = normalize(expected, 'handlers.py', strip_bp_lnum=True)
        expected = expected.strip()
        self.assertTrue(expected in stdout,
            '\n\nExpected:\n%s\nGot:\n%s\n'
            'Fail to handle a breakpoint set by function name.'
             % (expected, stdout))

    def test_issue_16180(self):
        # A syntax error in the debuggee.
        script = """
            def foo:
                pass

            foo()
        """
        commands = ''
        expected = """
            File main.py", line 2
            def foo:
                   ^
            SyntaxError: invalid syntax"""
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stderr = normalize(stderr, filename)
        expected = normalize(expected)
        self.assertTrue(expected in stderr,
            '\n\nExpected:\n%s\nGot:\n%s\n'
            'Fail to handle a syntax error in the debuggee.'
             % (expected, stderr))

    def test_issue_13044(self):
        script = """
            import pdb

            pdb.set_trace()
            a = 1
            b = 2
            sum = a + b
        """
        commands = """
            step
            step
            step
            step
        """
        # The error is not always the same:
        # Python 2.7.2: Exception ImportError: 'No module named repr' in
        # <function _remove at 0x7f7f51224938> ignored
        # Python 2.7.1: Exception AttributeError: "'NoneType' object has no
        # attribute 'path'" in <function _remove at 0xb73b6df4> ignored
        error = 'Exception'
        filename = 'main.py'
        f = None
        try:
            f = open(filename, 'w')
            f.write(textwrap.dedent(script))
        finally:
            if f:
                f.close()
        self.addCleanup(unlink, filename)
        cmd = [sys.executable, filename]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                   stdin=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate(commands)
        stderr = stderr and normalize(stderr)
        error = normalize(error)
        self.assertTrue(error not in stderr,
            '\n\nError not expected:\n%s\nGot:\n%s\n'
            'The debugger is still active while the interpreter shuts down.'
             % (error, stderr))

    def test_issue13120(self):
        # invoking "continue" on a non-main thread triggered an exception
        # inside signal.signal
        f = None
        try:
            f = open(support.TESTFN, 'wb')
            f.write(textwrap.dedent("""
                import threading
                import pdb

                def start_pdb():
                    pdb.Pdb().set_trace()
                    x = 1
                    y = 1

                t = threading.Thread(target=start_pdb)
                t.start()"""))
        finally:
            if f:
                f.close()
        cmd = [sys.executable, '-u', support.TESTFN]
        proc = subprocess.Popen(cmd,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            )
        self.addCleanup(proc.stdout.close)
        stdout, stderr = proc.communicate('cont\n')
        self.assertTrue('Error' not in stdout,
                         "Got an error running test script under PDB")

    def test_set_bp_by_function_name_after_import(self):
        # Set breakpoint at function in module after module has been imported.
        script = """
            pass
        """
        commands = """
            import asyncore
            break asyncore.dispatcher.connect
            import asyncore as core
            break core.dispatcher.connect
            quit
        """
        expected = ("""
            > main.py(2)%s()
            -> pass
            Breakpoint 1 at asyncore.py
            Breakpoint 2 at asyncore.py
            """ % MODULE_CO_NAME)
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(normalize(
                    stdout, 'asyncore.py', strip_bp_lnum=True), filename)
        expected = normalize(expected).strip()
        self.assertTrue(expected in stdout,
            '\n\nExpected:\n%s\nGot:\n%s\n'
            'Fail to set a breakpoint by function name after import.' %
            (expected, stdout))


    def tearDown(self):
        unlink(support.TESTFN)


def test_main():
    from test import test_pdb
    support.run_doctest(test_pdb, verbosity=True)
    support.run_unittest(PdbTestCase)


if __name__ == '__main__':
    test_main()
