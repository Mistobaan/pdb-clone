# A test suite for pdb; not very comprehensive at the moment.

import sys
import os
import io
import time
import imp
import unittest
import subprocess
import textwrap
import importlib
from pdb_clone import pdb
from pdb_clone import attach as pdb_attach
from test.script_helper import assert_python_ok
try:
    import threading
except ImportError:
    threading = None

from test import support
# This little helper class is essential for testing pdb under doctest.
from test.test_doctest import _FakeInput

# Some unittest tests spawn a new instance of pdb.
prev_pypath = [os.environ['PYTHONPATH']] if 'PYTHONPATH' in os.environ else []
os.environ['PYTHONPATH'] = os.pathsep.join(prev_pypath +
                                           [os.path.abspath('pdb_clone')])

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
    ...     pass

    >>> with PdbTestInput([
    ...     'foo',
    ...     'bar',
    ...     'for i in range(5): print(i)',
    ...     'continue',
    ... ]):
    ...     test_function(1, None)
    > <doctest test.test_pdb.test_pdb_displayhook[0]>(3)test_function()
    -> pass
    (Pdb) foo
    1
    (Pdb) bar
    (Pdb) for i in range(5): print(i)
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
    ...     print(foo)
    ...     for i in range(5):
    ...         print(i)
    ...     print(bar)
    ...     for i in range(10):
    ...         never_executed
    ...     print('after for')
    ...     print('...')
    ...     return foo.upper()

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     ret = test_function_2('baz')
    ...     print(ret)

    >>> with PdbTestInput([  # doctest: +ELLIPSIS, +NORMALIZE_WHITESPACE
    ...     'step',       # entering the function call
    ...     'args',       # display function args
    ...     'list',       # list function source
    ...     'bt',         # display backtrace
    ...     'up',         # step up to test_function()
    ...     'down',       # step down to test_function_2() again
    ...     'next',       # stepping to print(foo)
    ...     'next',       # stepping to the for loop
    ...     'step',       # stepping into the for loop
    ...     'until',      # continuing until out of the for loop
    ...     'next',       # executing the print(bar)
    ...     'jump 8',     # jump over second for loop
    ...     'return',     # return out of function
    ...     'retval',     # display return value
    ...     'continue',
    ... ]):
    ...    test_function()
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
      2             print(foo)
      3             for i in range(5):
      4                 print(i)
      5             print(bar)
      6             for i in range(10):
      7                 never_executed
      8             print('after for')
      9             print('...')
     10             return foo.upper()
    [EOF]
    (Pdb) bt
    ...
      <doctest test.test_pdb.test_pdb_basic_commands[2]>(18)<module>()
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
    -> print(foo)
    (Pdb) next
    baz
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(3)test_function_2()
    -> for i in range(5):
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(4)test_function_2()
    -> print(i)
    (Pdb) until
    0
    1
    2
    3
    4
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(5)test_function_2()
    -> print(bar)
    (Pdb) next
    default
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(6)test_function_2()
    -> for i in range(10):
    (Pdb) jump 8
    > <doctest test.test_pdb.test_pdb_basic_commands[0]>(8)test_function_2()
    -> print('after for')
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
    ...     print(1)
    ...     print(2)
    ...     print(3)
    ...     print(4)

    First, need to clear bdb state that might be left over from previous tests.
    Otherwise, the new breakpoints might get assigned different numbers.

    >>> from pdb_clone.bdb import Breakpoint
    >>> Breakpoint.next = 1
    >>> Breakpoint.bplist = {}
    >>> Breakpoint.bpbynumber = [None]

    Now test the breakpoint commands.  NORMALIZE_WHITESPACE is needed because
    the breakpoint list outputs a tab for the "stop only" and "ignore next"
    lines, which we don't want to put in here.

    >>> with PdbTestInput([  # doctest: +NORMALIZE_WHITESPACE
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
    ...     'p "42"',
    ...     'print("42", 7*6)',     # Issue 18764 (not about breakpoints)
    ...     'end',
    ...     'continue',  # will stop at breakpoint 2 (line 4)
    ...     'clear',     # clear all!
    ...     'y',
    ...     'tbreak 5',
    ...     'continue',  # will stop at temporary breakpoint
    ...     'break',     # make sure breakpoint is gone
    ...     'continue',
    ... ]):
    ...    test_function()
    > <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>(3)test_function()
    -> print(1)
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
    (com) p "42"
    (com) print("42", 7*6)
    (com) end
    (Pdb) continue
    1
    '42'
    42 42
    > <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>(4)test_function()
    -> print(2)
    (Pdb) clear
    Clear all breaks? y
    Deleted breakpoint 2 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:4
    (Pdb) tbreak 5
    Breakpoint 4 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:5
    (Pdb) continue
    2
    Deleted breakpoint 4 at <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>:5
    > <doctest test.test_pdb.test_pdb_breakpoint_commands[0]>(5)test_function()
    -> print(3)
    (Pdb) break
    (Pdb) continue
    3
    4
    """


def do_nothing():
    pass

def do_something():
    print(42)

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

    >>> with PdbTestInput([  # doctest: +ELLIPSIS, +NORMALIZE_WHITESPACE
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
    ... ]):
    ...    test_function()
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
    ...             print(42)
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
    ...         print('Exception!')

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     test_function_2()
    ...     print('Not reached.')

    >>> with PdbTestInput([  # doctest: +ELLIPSIS, +NORMALIZE_WHITESPACE
    ...     'next',      # step over exception-raising call
    ...     'bt',        # get a backtrace
    ...     'list',      # list code of test_function()
    ...     'down',      # step into test_function_2()
    ...     'list',      # list code of test_function_2()
    ...     'continue',
    ... ]):
    ...    try:
    ...        test_function()
    ...    except ZeroDivisionError:
    ...        print('Correctly reraised.')
    > <doctest test.test_pdb.test_post_mortem[1]>(3)test_function()
    -> test_function_2()
    (Pdb) next
    Exception!
    --Exception--
    ZeroDivisionError: division by zero
    > <doctest test.test_pdb.test_post_mortem[1]>(3)test_function()
    -> test_function_2()
    (Pdb) bt
    ...
      <doctest test.test_pdb.test_post_mortem[2]>(10)<module>()
    -> test_function()
    > <doctest test.test_pdb.test_post_mortem[1]>(3)test_function()
    -> test_function_2()
      <doctest test.test_pdb.test_post_mortem[0]>(3)test_function_2()
    -> 1/0
    (Pdb) list
      1         def test_function():
      2             from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
      3  ->         test_function_2()
      4             print('Not reached.')
    [EOF]
    (Pdb) down
    > <doctest test.test_pdb.test_post_mortem[0]>(3)test_function_2()
    -> 1/0
    (Pdb) list
      1         def test_function_2():
      2             try:
      3  >>             1/0
      4             finally:
      5  ->             print('Exception!')
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

    >>> with PdbTestInput([
    ...     'step',
    ...     'continue',
    ... ]):
    ...     skip_module()
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

    >>> with PdbTestInput([
    ...     'step',
    ...     'step',
    ...     'step',
    ...     'step',
    ...     'step',
    ...     'continue',
    ... ]):
    ...     skip_module()
    ...     pass  # provides something to "step" to
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
    > <doctest test.test_pdb.test_pdb_skip_modules_with_callback[1]>(10)<module>()
    -> pass  # provides something to "step" to
    (Pdb) continue
    """


def test_pdb_continue_in_bottomframe():
    """Test that "continue" and "next" work properly in bottom frame (issue #5294).

    >>> def test_function():
    ...     import sys; from pdb_clone import pdb; inst = pdb.Pdb(nosigint=True)
    ...     inst.set_trace()
    ...     inst.botframe = sys._getframe()  # hackery to get the right botframe
    ...     print(1)
    ...     print(2)
    ...     print(3)
    ...     print(4)

    >>> with PdbTestInput([  # doctest: +ELLIPSIS
    ...     'next',
    ...     'break 7',
    ...     'continue',
    ...     'next',
    ...     'continue',
    ...     'continue',
    ... ]):
    ...    test_function()
    > <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>(4)test_function()
    -> inst.botframe = sys._getframe()  # hackery to get the right botframe
    (Pdb) next
    > <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>(5)test_function()
    -> print(1)
    (Pdb) break 7
    Breakpoint ... at <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>:7
    (Pdb) continue
    1
    2
    > <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>(7)test_function()
    -> print(3)
    (Pdb) next
    3
    > <doctest test.test_pdb.test_pdb_continue_in_bottomframe[0]>(8)test_function()
    -> print(4)
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
    >>> with pti:
    ...     pdb_invoke('run', lambda x: x)
    Traceback (most recent call last):
    TypeError: exec() arg 1 must be a string, bytes or code object

    >>> pti = PdbTestInput(['continue',])
    >>> with pti:
    ...     pdb_invoke('runeval', lambda x: x)
    Traceback (most recent call last):
    TypeError: eval() arg 1 must be a string, bytes or code object
    """


def test_pdb_run_with_code_object():
    """Testing run and runeval with code object as a first argument.

    >>> with PdbTestInput(['step','x', 'continue']):  # doctest: +ELLIPSIS
    ...     pdb_invoke('run', compile('x=1', '<string>', 'exec'))
    > <string>(1)<module>()...
    (Pdb) step
    --Return--
    > <string>(1)<module>()->None
    (Pdb) x
    1
    (Pdb) continue

    >>> with PdbTestInput(['x', 'continue']):
    ...     x=0
    ...     pdb_invoke('runeval', compile('x+1', '<string>', 'eval'))
    > <string>(1)<module>()->None
    (Pdb) x
    1
    (Pdb) continue
    """

def test_next_until_return_at_return_event():
    """Test that pdb stops after a next/until/return issued at a return debug event.

    >>> def test_function_2():
    ...     x = 1
    ...     x = 2

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     test_function_2()
    ...     test_function_2()
    ...     test_function_2()
    ...     end = 1

    >>> with PdbTestInput(['break test_function_2',
    ...                    'continue',
    ...                    'return',
    ...                    'next',
    ...                    'continue',
    ...                    'return',
    ...                    'until',
    ...                    'continue',
    ...                    'return',
    ...                    'return',
    ...                    'continue']):
    ...     test_function()
    > <doctest test.test_pdb.test_next_until_return_at_return_event[1]>(3)test_function()
    -> test_function_2()
    (Pdb) break test_function_2
    Breakpoint 1 at <doctest test.test_pdb.test_next_until_return_at_return_event[0]>:1
    (Pdb) continue
    > <doctest test.test_pdb.test_next_until_return_at_return_event[0]>(2)test_function_2()
    -> x = 1
    (Pdb) return
    --Return--
    > <doctest test.test_pdb.test_next_until_return_at_return_event[0]>(3)test_function_2()->None
    -> x = 2
    (Pdb) next
    > <doctest test.test_pdb.test_next_until_return_at_return_event[1]>(4)test_function()
    -> test_function_2()
    (Pdb) continue
    > <doctest test.test_pdb.test_next_until_return_at_return_event[0]>(2)test_function_2()
    -> x = 1
    (Pdb) return
    --Return--
    > <doctest test.test_pdb.test_next_until_return_at_return_event[0]>(3)test_function_2()->None
    -> x = 2
    (Pdb) until
    > <doctest test.test_pdb.test_next_until_return_at_return_event[1]>(5)test_function()
    -> test_function_2()
    (Pdb) continue
    > <doctest test.test_pdb.test_next_until_return_at_return_event[0]>(2)test_function_2()
    -> x = 1
    (Pdb) return
    --Return--
    > <doctest test.test_pdb.test_next_until_return_at_return_event[0]>(3)test_function_2()->None
    -> x = 2
    (Pdb) return
    > <doctest test.test_pdb.test_next_until_return_at_return_event[1]>(6)test_function()
    -> end = 1
    (Pdb) continue
    """

def test_pdb_next_command_for_generator():
    """Testing skip unwindng stack on yield for generators for "next" command

    >>> def test_gen():
    ...     yield 0
    ...     return 1
    ...     yield 2

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     it = test_gen()
    ...     try:
    ...         assert next(it) == 0
    ...         next(it)
    ...     except StopIteration as ex:
    ...         assert ex.value == 1
    ...     print("finished")

    >>> with PdbTestInput(['step',
    ...                    'step',
    ...                    'step',
    ...                    'next',
    ...                    'next',
    ...                    'step',
    ...                    'step',
    ...                    'continue']):
    ...     test_function()
    > <doctest test.test_pdb.test_pdb_next_command_for_generator[1]>(3)test_function()
    -> it = test_gen()
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_next_command_for_generator[1]>(4)test_function()
    -> try:
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_next_command_for_generator[1]>(5)test_function()
    -> assert next(it) == 0
    (Pdb) step
    --Call--
    > <doctest test.test_pdb.test_pdb_next_command_for_generator[0]>(1)test_gen()
    -> def test_gen():
    (Pdb) next
    > <doctest test.test_pdb.test_pdb_next_command_for_generator[0]>(2)test_gen()
    -> yield 0
    (Pdb) next
    > <doctest test.test_pdb.test_pdb_next_command_for_generator[0]>(3)test_gen()
    -> return 1
    (Pdb) step
    --Return--
    > <doctest test.test_pdb.test_pdb_next_command_for_generator[0]>(3)test_gen()->1
    -> return 1
    (Pdb) step
    --Exception--
    StopIteration: 1
    > <doctest test.test_pdb.test_pdb_next_command_for_generator[1]>(6)test_function()
    -> next(it)
    (Pdb) continue
    finished
    """

def test_pdb_return_command_for_generator():
    """Testing no unwindng stack on yield for generators
       for "return" command

    >>> def test_gen():
    ...     yield 0
    ...     return 1
    ...     yield 2

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     it = test_gen()
    ...     try:
    ...         assert next(it) == 0
    ...         next(it)
    ...     except StopIteration as ex:
    ...         assert ex.value == 1
    ...     print("finished")

    >>> with PdbTestInput(['step',
    ...                    'step',
    ...                    'step',
    ...                    'return',
    ...                    'step',
    ...                    'step',
    ...                    'continue']):
    ...     test_function()
    > <doctest test.test_pdb.test_pdb_return_command_for_generator[1]>(3)test_function()
    -> it = test_gen()
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_return_command_for_generator[1]>(4)test_function()
    -> try:
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_return_command_for_generator[1]>(5)test_function()
    -> assert next(it) == 0
    (Pdb) step
    --Call--
    > <doctest test.test_pdb.test_pdb_return_command_for_generator[0]>(1)test_gen()
    -> def test_gen():
    (Pdb) return
    --Exception--
    StopIteration: 1
    > <doctest test.test_pdb.test_pdb_return_command_for_generator[1]>(6)test_function()
    -> next(it)
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_return_command_for_generator[1]>(7)test_function()
    -> except StopIteration as ex:
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_return_command_for_generator[1]>(8)test_function()
    -> assert ex.value == 1
    (Pdb) continue
    finished
    """

def test_pdb_until_command_for_generator():
    """Testing no unwindng stack on yield for generators
       for "until" command if target breakpoing is not reached

    >>> def test_gen():
    ...     yield 0
    ...     yield 1
    ...     yield 2

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     for i in test_gen():
    ...         print(i)
    ...     print("finished")

    >>> with PdbTestInput(['step',
    ...                    'until 4',
    ...                    'step',
    ...                    'step',
    ...                    'continue']):
    ...     test_function()
    > <doctest test.test_pdb.test_pdb_until_command_for_generator[1]>(3)test_function()
    -> for i in test_gen():
    (Pdb) step
    --Call--
    > <doctest test.test_pdb.test_pdb_until_command_for_generator[0]>(1)test_gen()
    -> def test_gen():
    (Pdb) until 4
    0
    1
    > <doctest test.test_pdb.test_pdb_until_command_for_generator[0]>(4)test_gen()
    -> yield 2
    (Pdb) step
    --Return--
    > <doctest test.test_pdb.test_pdb_until_command_for_generator[0]>(4)test_gen()->2
    -> yield 2
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_until_command_for_generator[1]>(4)test_function()
    -> print(i)
    (Pdb) continue
    2
    finished
    """

def test_pdb_next_command_in_generator_for_loop():
    """The next command on returning from a generator controled by a for loop.

    >>> def test_gen():
    ...     yield 0
    ...     return 1

    >>> def test_function():
    ...     from pdb_clone import pdb, bdb; bdb.Breakpoint.next = 1; pdb.Pdb(nosigint=True).set_trace()
    ...     for i in test_gen():
    ...         print('value', i)
    ...     x = 123

    >>> with PdbTestInput(['break test_gen',
    ...                    'continue',
    ...                    'next',
    ...                    'next',
    ...                    'next',
    ...                    'continue']):
    ...     test_function()
    > <doctest test.test_pdb.test_pdb_next_command_in_generator_for_loop[1]>(3)test_function()
    -> for i in test_gen():
    (Pdb) break test_gen
    Breakpoint 1 at <doctest test.test_pdb.test_pdb_next_command_in_generator_for_loop[0]>:1
    (Pdb) continue
    > <doctest test.test_pdb.test_pdb_next_command_in_generator_for_loop[0]>(2)test_gen()
    -> yield 0
    (Pdb) next
    value 0
    > <doctest test.test_pdb.test_pdb_next_command_in_generator_for_loop[0]>(3)test_gen()
    -> return 1
    (Pdb) next
    --Exception--
    Internal StopIteration: 1
    > <doctest test.test_pdb.test_pdb_next_command_in_generator_for_loop[1]>(3)test_function()
    -> for i in test_gen():
    (Pdb) next
    > <doctest test.test_pdb.test_pdb_next_command_in_generator_for_loop[1]>(5)test_function()
    -> x = 123
    (Pdb) continue
    """

def test_pdb_next_command_subiterator():
    """The next command in a generator with a subiterator.

    >>> def test_subgenerator():
    ...     yield 0
    ...     return 1

    >>> def test_gen():
    ...     x = yield from test_subgenerator()
    ...     return x

    >>> def test_function():
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     for i in test_gen():
    ...         print('value', i)
    ...     x = 123

    >>> with PdbTestInput(['step',
    ...                    'step',
    ...                    'next',
    ...                    'next',
    ...                    'next',
    ...                    'continue']):
    ...     test_function()
    > <doctest test.test_pdb.test_pdb_next_command_subiterator[2]>(3)test_function()
    -> for i in test_gen():
    (Pdb) step
    --Call--
    > <doctest test.test_pdb.test_pdb_next_command_subiterator[1]>(1)test_gen()
    -> def test_gen():
    (Pdb) step
    > <doctest test.test_pdb.test_pdb_next_command_subiterator[1]>(2)test_gen()
    -> x = yield from test_subgenerator()
    (Pdb) next
    value 0
    > <doctest test.test_pdb.test_pdb_next_command_subiterator[1]>(3)test_gen()
    -> return x
    (Pdb) next
    --Exception--
    Internal StopIteration: 1
    > <doctest test.test_pdb.test_pdb_next_command_subiterator[2]>(3)test_function()
    -> for i in test_gen():
    (Pdb) next
    > <doctest test.test_pdb.test_pdb_next_command_subiterator[2]>(5)test_function()
    -> x = 123
    (Pdb) continue
    """

def test_thread_command():
    """Testing the thread command.

    >>> class State():
    ...     def __init__(self): self.running = True
    ...     def stop(self): self.running = False
    ...     def __bool__(self): return self.running

    >>> def deadlock(lock1, lock2, state):
    ...     cnt = 0
    ...     while state:
    ...         with lock1:
    ...             while state:
    ...                 if lock2.acquire(timeout=.020):
    ...                     deadlocked = False
    ...                     cnt += 1
    ...                     lock2.release()
    ...                     break
    ...                 else:
    ...                     deadlocked = True

    >>> def test_function():
    ...     locks = (threading.Lock(), threading.Lock())
    ...     t1 = threading.Thread(name='Thread_1', target=deadlock,
    ...                                 args=(locks[0], locks[1], State()))
    ...     t1.start()
    ...     state2 = State()
    ...     t2 = threading.Thread(name='Thread_2', target=deadlock,
    ...                                 args=(locks[1], locks[0], state2))
    ...     t2.start()
    ...     tlist = [t1, t2]
    ...
    ...     from pdb_clone import pdb; pdb.Pdb(nosigint=True).set_trace()
    ...     while tlist:
    ...         for (i, t) in enumerate(tlist):
    ...             t.join(.020)
    ...             if not t.is_alive():
    ...                 del tlist[i]

    >>> with PdbTestInput([  # doctest: +ELLIPSIS
    ...                    'time.sleep(.100)',
    ...                    'thread',
    ...                    'thread 2',
    ...                    'thread',
    ...                    'state.stop()',
    ...                    'time.sleep(.100)',
    ...                    'thread 1',
    ...                    'state2.stop()',
    ...                    'time.sleep(.100)',
    ...                    'thread',
    ...                    'continue']):
    ...     test_function()
    > <doctest test.test_pdb.test_thread_command[2]>(13)test_function()
    -> while tlist:
    (Pdb) time.sleep(.100)
    (Pdb) thread
       Nb  Name               Identifier       Stack entry
    +*   1 MainThread          ... <doctest test.test_pdb.test_thread_command[2]>(13)test_function()
                                               -> while tlist:
         2 Thread_1            ... <doctest test.test_pdb.test_thread_command[1]>(6)deadlock()
                                               -> if lock2.acquire(timeout=.020):
         3 Thread_2            ... <doctest test.test_pdb.test_thread_command[1]>(6)deadlock()
                                               -> if lock2.acquire(timeout=.020):
    (Pdb) thread 2
    > <doctest test.test_pdb.test_thread_command[1]>(6)deadlock()
    -> if lock2.acquire(timeout=.020):
    (Pdb) thread
       Nb  Name               Identifier       Stack entry
    +    1 MainThread          ... <doctest test.test_pdb.test_thread_command[2]>(13)test_function()
                                               -> while tlist:
     *   2 Thread_1            ... <doctest test.test_pdb.test_thread_command[1]>(6)deadlock()
                                               -> if lock2.acquire(timeout=.020):
         3 Thread_2            ... <doctest test.test_pdb.test_thread_command[1]>(6)deadlock()
                                               -> if lock2.acquire(timeout=.020):
    (Pdb) state.stop()
    (Pdb) time.sleep(.100)
    (Pdb) thread 1
    > <doctest test.test_pdb.test_thread_command[2]>(13)test_function()
    -> while tlist:
    (Pdb) state2.stop()
    (Pdb) time.sleep(.100)
    (Pdb) thread
       Nb  Name               Identifier       Stack entry
    +*   1 MainThread          ... <doctest test.test_pdb.test_thread_command[2]>(13)test_function()
                                               -> while tlist:
    (Pdb) continue
    """

if not threading:
    def test_thread_command(): pass

def test_pdb_set_frame_locals():
    """This tests setting local variables.

    >>> def foo(n):
    ...     x = n
    ...     bar(x)
    >>> def bar(n):
    ...     y = n + 1
    ...     from pdb_clone import pdb; pdb.Pdb().set_trace()
    ...     z = y

    >>> with PdbTestInput([
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
    ... ]):
    ...      foo(1)
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

def test_pdb_issue_20766():
    """Testing for reference leaks when setting SIGINT handler.

    >>> def set_trace():
    ...     import sys; from pdb_clone import pdb
    ...     pdbinst = pdb.Pdb()
    ...     pdbinst.set_trace(sys._getframe().f_back)
    ...     return pdbinst

    >>> def foo(prev_pdbinst):
    ...     import gc
    ...     pdbinst = set_trace();
    ...     gc.collect()
    ...     references = gc.get_referents(pdbinst._previous_sigint_handler)
    ...     print(references)
    ...     if prev_pdbinst and prev_pdbinst not in references:
    ...         print('self._previous_sigint_handler does not refer to the'
    ...               ' previous Pdb instance.')
    ...     return pdbinst

    >>> def test_function():
    ...     i = 2
    ...     pdbinst = None
    ...     while i:
    ...         i -= 1
    ...         pdbinst = foo(pdbinst)

    >>> with PdbTestInput(['continue',
    ...                    'continue']):
    ...     test_function()
    > <doctest test.test_pdb.test_pdb_issue_20766[1]>(4)foo()
    -> gc.collect()
    (Pdb) continue
    [<module '_signal' (built-in)>, '_signal']
    > <doctest test.test_pdb.test_pdb_issue_20766[1]>(4)foo()
    -> gc.collect()
    (Pdb) continue
    [<module '_signal' (built-in)>, '_signal']
    self._previous_sigint_handler does not refer to the previous Pdb instance.
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

    def run_pdb(self, script, commands, filename):
        """Run 'script' lines with pdb and the pdb 'commands'."""
        with open(filename, 'w') as f:
            f.write(textwrap.dedent(script))
        self.addCleanup(support.unlink, filename)
        cmd = [sys.executable, 'pdb-clone', filename]
        with subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                   stdin=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   ) as proc:
            stdout, stderr = proc.communicate(str.encode(commands))
        stdout = stdout and bytes.decode(stdout)
        stderr = stderr and bytes.decode(stderr)
        return stdout, stderr

    def _assert_find_function(self, file_content, func_name, expected):
        file_content = textwrap.dedent(file_content)

        with open(support.TESTFN, 'w') as f:
            f.write(file_content)

        expected = None if not expected else (
            expected[0], support.TESTFN, expected[1])
        self.assertEqual(
            expected, pdb.find_function(func_name, support.TESTFN))

    def test_find_function_empty_file(self):
        self._assert_find_function('', 'foo', None)

    def test_find_function_found(self):
        self._assert_find_function(
            """\
            def foo():
                pass

            def bar():
                pass

            def quux():
                pass
            """,
            'bar',
            ('bar', 4),
        )

    def test_issue7964(self):
        # open the file as binary so we can force \r\n newline
        with open(support.TESTFN, 'wb') as f:
            f.write(b'print("testing my pdb")\r\n')
        cmd = [sys.executable, '-m', 'pdb', support.TESTFN]
        proc = subprocess.Popen(cmd,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            )
        self.addCleanup(proc.stdout.close)
        stdout, stderr = proc.communicate(b'quit\n')
        self.assertNotIn(b'SyntaxError', stdout,
                         "Got a syntax error running test script under PDB")

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
        with open('bar.py', 'w') as f:
            f.write(textwrap.dedent(bar))
        if hasattr(importlib, 'invalidate_caches'):
            importlib.invalidate_caches()
        self.addCleanup(support.unlink, 'bar.py')
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
            p a
            end
            ignore 1 1
            break bar
            commands 2
            p a + 1
            end
            ignore 2 1
            continue
            break
            quit
        """
        expected = """
            > main.py(2)<module>()
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
        """
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(stdout, filename)
        expected = normalize(expected)
        self.assertTrue(expected in stdout,
            '\n\nExpected:\n{}\nGot:\n{}\n'
            'Fail to handle two breakpoints set on the same line.'.format(
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
        expected = '''
            > main.py(2)<module>()
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
            '''
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(normalize(
                    stdout, 'handlers.py', strip_bp_lnum=True), filename)
        expected = normalize(expected, 'handlers.py', strip_bp_lnum=True)
        expected = expected.strip()
        self.assertTrue(expected in stdout,
            '\n\nExpected:\n{}\nGot:\n{}\n'
            'Fail to handle a breakpoint set by function name.'
            .format(expected, stdout))

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
            '\n\nExpected:\n{}\nGot:\n{}\n'
            'Fail to handle a syntax error in the debuggee.'
            .format(expected, stderr))

    def test_issue13120(self):
        # invoking "continue" on a non-main thread triggered an exception
        # inside signal.signal

        # raises SkipTest if python was built without threads
        support.import_module('threading')

        with open(support.TESTFN, 'wb') as f:
            f.write(textwrap.dedent("""
                import threading
                from pdb_clone import pdb

                def start_pdb():
                    pdb.Pdb().set_trace()
                    x = 1
                    y = 1

                t = threading.Thread(target=start_pdb)
                t.start()""").encode('ascii'))
        cmd = [sys.executable, '-u', support.TESTFN]
        proc = subprocess.Popen(cmd,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            )
        self.addCleanup(proc.stdout.close)
        stdout, stderr = proc.communicate(b'cont\n')
        self.assertNotIn('Error', stdout.decode(),
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
        expected = """
            > main.py(2)<module>()
            -> pass
            Breakpoint 1 at asyncore.py
            Breakpoint 2 at asyncore.py
            """
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(normalize(
                    stdout, 'asyncore.py', strip_bp_lnum=True), filename)
        expected = normalize(expected).strip()
        self.assertTrue(expected in stdout,
            '\n\nExpected:\n{}\nGot:\n{}\n'
            'Fail to set a breakpoint by function name after import.'
            .format(expected, stdout))

    def test_issue_20853_1(self):
        # pdb "args" crashes when an arg is not printable.
        script = """
            class foo:
                def __init__(self):
                    foo.bar = "hello"
                def __repr__(self):
                    return foo.bar

            foo()
        """
        commands = """
            step
            step
            step
            step
            step
            step
            step
            step
            args
            p self
            pp self
            display self
            quit
        """
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(stdout, filename)
        self.assertTrue(
            len(list(filter(lambda x: '__main__.foo object' in x,
                                            stdout.split('\n')))) == 4,
            '\n\nGot:\n{}\n'
            'Fail to print a safe representation of self.'
            .format(stdout))

    def test_issue_20853_2(self):
        # pdb "retval" crashes when the return value is not printable.
        script = """
            class C(object):
                def __new__(cls, *args, **kwds):
                    return object.__new__(cls)

                def __init__(self, value):
                    self.value = value

                def __repr__(self):
                    return str(self.value)

            C(123)
        """
        commands = """
            step
            step
            step
            step
            step
            step
            step
            step
            step
            step
            retval
            quit
        """
        expected = '<__main__.C object at'
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(stdout, filename)
        self.assertTrue(expected in stdout,
            '\n\nExpected:\n{}\nGot:\n{}\n'
            'Fail to print a safe representation of the return value.'
            .format(expected, stdout))

    @unittest.skipIf(sys.platform == 'win32', 'a posix test')
    def test_issue_20269(self):
        # Inconsistent behavior in pdb when pressing Ctrl-C.
        script = """
            def foo():
                i = 1
                while i:
                    i += 1

            foo()
        """
        commands = """
            next
            !import signal, os
            !def kill(sig, frame): os.kill(os.getpid(), signal.SIGINT)
            !signal.signal(signal.SIGALRM, kill)
            !signal.alarm(1)
            next
            i = 0
            quit
        """
        expected = "Program interrupted. (Use 'cont' to resume).\n"
        filename = 'main.py'
        stdout, stderr = self.run_pdb(script, commands, filename)
        stdout = normalize(stdout, filename)
        self.assertTrue(expected in stdout,
            '\n\nExpected:\n{}\nGot:\n{}\n'
            'Fail to interrupt the debugger with <Ctl-C>.'
            .format(expected, stdout))

    def tearDown(self):
        support.unlink(support.TESTFN)

class RemoteDebugging(unittest.TestCase):
    """Remote debugging support."""

    def run_pdb_remotely(self, source, commands):
        """Run 'source' in a spawned process."""

        class Process(threading.Thread):
            def run(self):
                rc, self.stdout, self.stderr = assert_python_ok("-c", source,
                                                            __isolated=False)

        stdin = io.StringIO('\n'.join(commands))
        proc = Process()
        proc.start()
        count = 0
        while True:
            try:
                stdout = io.StringIO()
                pdb_attach.attach(stdin=stdin, stdout=stdout)
                break
            except (ConnectionRefusedError, SystemExit):
                count += 1
                if count >= 40:
                    raise
                time.sleep(0.200)
        proc.join()
        self.assertFalse(proc.stdout)
        self.assertFalse(proc.stderr)
        return stdout.getvalue()

@unittest.skipIf(threading is None, 'threading module is required')
class RemoteDebuggingTestCase(RemoteDebugging):
    """Remote debugging test cases."""

    def test_command_redirection(self):
        # Check the redirection of pdb commands.
        stdout = self.run_pdb_remotely("""if 1:
            from pdb_clone import pdb
            pdb.set_trace_remote()
            """,
            [
                'help detach',
                'detach',
             ]
        )
        self.assertIn('Release the process from pdb control.', stdout)

    def test_statement_output_redirection(self):
        # Check the redirection of python statements at the pdb prompt.
        stdout = self.run_pdb_remotely("""if 1:
            from pdb_clone import pdb
            a = 1
            pdb.set_trace_remote()
            """,
            [
                'print("a + 2 = %d" % (a + 2))',
                'detach',
             ]
        )
        self.assertIn('a + 2 = 3', stdout)

    def test_debug_command(self):
        stdout = self.run_pdb_remotely("""if 1:
            from pdb_clone import pdb
            def foo():
                a = 'in foo'
            pdb.set_trace_remote()
            fin = 'fin'
            """,
            [
                'debug foo()',
                'step',
                'step',
                'step',
                'print(a)',
                'quit',
                'step',
                'print(fin)',
                'detach',
             ]
        )
        self.assertIn('in foo', stdout)
        self.assertIn('fin', stdout)

    def test_interact_command(self):
        some_text = 'testing the interact command'
        stdout = self.run_pdb_remotely("""if 1:
            from pdb_clone import pdb
            text = '%s'
            pdb.set_trace_remote()
            """ % some_text,
            [
                'interact',
                'text',
                'quit()',
             ]
        )
        self.assertIn(some_text, stdout)

@unittest.skipIf(threading is None, 'threading module is required')
class PdbTestCaseUsingRemoteDebugging(RemoteDebugging):
    """Test cases using remote debugging."""

    def test_issue_21161(self):
        # List comprehensions don't see local variables.
        stdout = self.run_pdb_remotely("""if 1:
            from pdb_clone import pdb

            def foo():
              items = [1, 2, 3]
              limit = 5
              pdb.set_trace_remote()

            foo()
            """,
            [
                "print('The result is', all(x < limit for x in items))",
                'detach',
             ]
        )
        self.assertIn('The result is True\n', stdout)

def test_main():
    from test import test_pdb
    support.run_doctest(test_pdb, verbosity=True)
    support.run_unittest(PdbTestCase, RemoteDebuggingTestCase,
                         PdbTestCaseUsingRemoteDebugging)


if __name__ == '__main__':
    test_main()
