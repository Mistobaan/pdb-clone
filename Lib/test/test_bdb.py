import sys
import signal
import unittest
import linecache
import textwrap
import importlib
from test import support
from itertools import islice, chain

from pdb_clone import bdb

# Set 'debug' true to debug the test cases.
debug = 0

# Convenience constants and functions.
STEP = ('step', )
NEXT = ('next', )
UNTIL = ('until', (None, ))
CONTINUE = ('continue', )
RETURN = ('return', )
UP = ('up', )
DOWN = ('down', )
QUIT = ('quit', )
TEST_MODULE = 'bdb_test_module.py'

def until(lineno=None):
    return 'until', (lineno, )

def break_lineno(lineno, fname=__file__):
    return 'break', (fname, lineno)

def break_func(funcname, fname=__file__):
    return 'break', (fname, None, False, None, funcname)

def ignore(bpnum):
    return 'ignore', (bpnum, )

def enable(bpnum):
    return 'enable', (bpnum, )

def disable(bpnum):
    return 'disable', (bpnum, )

def clear(lineno, fname=__file__):
    return 'clear', (fname, lineno)

def _reset_Breakpoint():
    bdb.Breakpoint.next = 1
    bdb.Breakpoint.bpbynumber = [None]

class BdbTest(bdb.Bdb):
    """A subclass of Bdb that processes send_expect sequences."""

    def __init__(self, test_case, skip=None, sigint=False):
        bdb.Bdb.__init__(self, skip=skip)
        self.test_case = test_case
        if sigint:
            self._previous_sigint_handler = \
                signal.signal(signal.SIGINT, self.sigint_handler)
        self.init_test()

    def init_test(self):
        self.se_cnt = 0
        self.send_list = list(islice(self.test_case.send_expect, 0, None, 2))
        self.expct_list = list(islice(
                chain([()], self.test_case.send_expect), 0, None, 2))

    def sigint_handler(self, signum, frame):
        signal.signal(signal.SIGINT, self._previous_sigint_handler)
        self.set_trace(frame)

    def dispatch_call(self, frame, arg):
        if debug and self.botframe is None:
            f = frame.f_back
            while f:
                if f.f_code.co_name.startswith('test_'):
                    break
                f = f.f_back
            print('\nTest {}'.format(f.f_code.co_name if f else '?'))
        return bdb.Bdb.dispatch_call(self, frame, arg)

    def get_stack(self, f, t):
        self.stack, self.index = bdb.Bdb.get_stack(self, f, t)
        self.frame = self.stack[self.index][0]
        return self.stack, self.index

    def assertEqual(self, arg1, arg2, msg):
        self.test_case.assertEqual(arg1, arg2,
            '{} at send_expect item {:d}, got "{}".'
            .format(msg, self.se_cnt, arg2))

    def lno_rel2abs(self, fname, lineno):
        return (self.frame.f_code.co_firstlineno + lineno - 1
            if (lineno and bdb.canonic(fname) == bdb.canonic(__file__))
            else lineno)

    def lno_abs2rel(self):
        fname = bdb.canonic(self.frame.f_code.co_filename)
        lineno = self.frame.f_lineno
        return ((lineno - self.frame.f_code.co_firstlineno + 1)
            if fname == bdb.canonic(__file__) else lineno)

    def send(self, event):
        try:
            send = self.send_list.pop(0)
        except IndexError:
            self.test_case.fail(
                'send_expect list exhausted, cannot pop the next send tuple.')

        self.se_cnt += 1
        set_type = send[0]
        args = send[1] if len(send) == 2 else None
        set_method = getattr(self, 'set_' + set_type)
        if debug:
            lineno = self.lno_abs2rel()
            print('{}({:d}): {} event at line {:d} processing command {}'
            .format(self.frame.f_code.co_name, self.se_cnt, event,
                                                        lineno, set_type))

        if set_type in ('step', 'continue', 'quit'):
            set_method()
        elif set_type in ('next', 'return'):
            set_method(self.frame)
        elif set_type == 'until' and args:
            lineno = self.lno_rel2abs(self.frame.f_code.co_filename, args[0])
            set_method(self.frame, lineno)
        # These methods do not give back control to the debugger.
        elif (args and set_type in ('break', 'clear', 'ignore', 'enable',
                                    'disable')) or set_type in ('up', 'down'):
            if set_type in ('break', 'clear'):
                fname, lineno, *remain = args
                lineno = self.lno_rel2abs(fname, lineno)
                args = [fname, lineno]
                args.extend(remain)
                set_method(*args)
            elif set_type in ('ignore', 'enable', 'disable'):
                set_method(*args)
            elif set_type in ('up', 'down'):
                set_method()
            else:
                assert False

            expect = self.check_lno_name(self.expct_list.pop(0))
            if len(expect) > 3:
                self.test_case.fail('Invalid size of the {} expect tuple: {}'
                    .format(set_type, expect))
            # Process the next send_expect item.
            self.send(None)
        else:
            self.test_case.fail('"{}" is an invalid send tuple.'
                                                        .format(send))

    def check_lno_name(self, expect):
        s = len(expect)
        if s > 1:
            lineno = self.lno_abs2rel()
            self.assertEqual(expect[1], lineno, 'Wrong line number')
        if s > 2:
            self.assertEqual(expect[2], self.frame.f_code.co_name,
                                                'Wrong function name')
        return expect

    def expect(self, event_type):
        expect = self.expct_list.pop(0)
        if expect:
            self.assertEqual(expect[0], event_type, 'Wrong event type')
            self.check_lno_name(expect)
        return expect

    def user_call(self, frame, argument_list):
        if not self.stop_here(frame):
            return
        self.get_stack(frame, None)
        expect = self.expect('call')
        if len(expect) > 3:
            self.test_case.fail('Invalid size of the call expect tuple: {}'
                .format(expect))
        self.send('call')

    def user_line(self, frame, breakpoint_hits=None):
        self.get_stack(frame, None)
        expect = self.expect('line')
        if len(expect) > 3:
            bps, temporaries = expect[3]
            bpnums = sorted(bps.keys())
            self.test_case.assertTrue(breakpoint_hits,
                'No breakpoints hit at send_expect item {:d}.'
                .format(self.se_cnt))
            self.assertEqual(bpnums, breakpoint_hits[0],
                'Breakpoint numbers do not match')
            self.assertEqual([bps[n] for n in bpnums],
                [self.get_bpbynumber(n).hits for n in breakpoint_hits[0]],
                'Wrong breakpoint hit count')
            self.assertEqual(sorted(temporaries), breakpoint_hits[1],
                'Wrong temporary breakpoints')
            # Delete the temporaries.
            for n in breakpoint_hits[1]:
                self.clear_bpbynumber(n)
        self.send('line')

    def user_return(self, frame, return_value):
        self.get_stack(frame, None)
        expect = self.expect('return')
        if len(expect) > 3:
            self.test_case.fail('Invalid size of the return expect tuple: {}'
                .format(expect))
        self.send('return')

    def user_exception(self, frame, exc_info):
        self.get_stack(frame, exc_info[2])
        expect = self.expect('exception')
        if len(expect) > 3:
            self.test_case.assertIsInstance(exc_info[1], expect[3],
                'Wrong exception at send_expect item {:d}, got "{}".'
                .format(self.se_cnt, exc_info))
        self.send('exception')

    def set_ignore(self, bpnum):
        """Increment the ignore count of Breakpoint number 'bpnum'."""
        bp = self.get_bpbynumber(bpnum)
        bp.ignore += 1

    def set_enable(self, bpnum):
        bp = self.get_bpbynumber(bpnum)
        bp.enabled = True

    def set_disable(self, bpnum):
        bp = self.get_bpbynumber(bpnum)
        bp.enabled = False

    def set_clear(self, fname, lineno):
        err = self.clear_break(fname, lineno)
        if err:
            raise bdb.BdbError(err)

    def set_up(self):
        """Move up in the frame stack."""
        if not self.index:
            raise bdb.BdbError('Oldest frame')
        self.index -= 1
        self.frame = self.stack[self.index][0]

    def set_down(self):
        """Move down in the frame stack."""
        if self.index + 1 == len(self.stack):
            raise bdb.BdbError('Newest frame')
        self.index += 1
        self.frame = self.stack[self.index][0]

dbg_var = 1

def dbg_module():
    import bdb_test_module
    lno = 3

def dbg_foobar():
    lno = 2
    dbg_foo()
    dbg_bar()
    lno = 5
    lno = 6
    lno = 7

def dbg_foo():
    lno = 2
    global dbg_var
    try:
        if not dbg_var:
            lno = 6
        else:
            dbg_var = 1
    finally:
        lno = 10

def dbg_bar():
    lno = 2

class SetMethodTestCase(unittest.TestCase):
    """Base class for all the tests.

    A send_expect item is defined as the two tuples:

        (set_type, [sargs]), ([debug_evt, [lineno[, co_name[, eargs]]]])

    where:
        set_type:
            The type of the Bdb or BdbTest set method to be invoked:
                Bdb set methods: step, next, until, return, continue, break,
                quit.
                BdbTest set methods: ignore, enable, disable, clear, up, down.
        sargs:
            The arguments, packed in a tuple, of the Bdb 'until' or 'break'
            methods and of the BdbTest set methods 'ignore', 'enable',
            'disable', 'clear'.
        debug_evt:
            The name of a dispatched debug event.
        eargs:
            A tuple whose value is checked on a 'line' or 'exception' debug
            event. On an 'exception' event it holds a class object, the
            exception must be an instance of this class. On a 'line' event, the
            tuple holds a dictionary and a list. The dictionary maps the
            breakpoint numbers to their hits count. The list holds the list of
            breakpoint number temporaries that are being deleted.

    Line numbers of functions defined in the 'test_bdb' module are relative
    line numbers.
    """

    def __init__(self, methodName='runTest'):
        unittest.TestCase.__init__(self, methodName)
        self.set_skip(None)
        self.set_sigint(False)
        self.set_restart(False)

    def set_skip(self, skip):
        self.skip = skip

    def set_sigint(self, sigint):
        self.sigint = sigint

    def set_restart(self, restart):
        self.restart = restart

    def setUp(self):
        # test_pdb does not reset Breakpoint class attributes on exit :-(
        _reset_Breakpoint()

        self.addCleanup(_reset_Breakpoint)
        self.addCleanup(sys.settrace, None)
        self.addCleanup(bdb._module_finder.close)

    def create_module(self, statements, module_name=TEST_MODULE[:-3]):
        """Create a module holding 'statements' to be debugged."""
        fname = module_name + '.py'
        with open(fname, 'w') as f:
            f.write(textwrap.dedent(statements))
        self.addCleanup(support.unlink, fname)
        self.addCleanup(support.forget, module_name)
        if hasattr(importlib, 'invalidate_caches'):
            importlib.invalidate_caches()
        # Update linecache cache and clear bdb cache.
        linecache.checkcache()
        bdb._modules = {}

    def runcall(self, func, *args, **kwds):
        bdb_inst = BdbTest(self, skip=self.skip, sigint=self.sigint)
        try:
            if self.restart:
                bdb_inst.restart()
            bdb_inst.runcall(func, *args, **kwds)
        except self.failureException as err:
            # Do not show the BdbTest traceback when the test fails.
            raise self.failureException() from err
        self.assertFalse(bdb_inst.send_list,
                'All send_expect sequences have not been processed.')
        return bdb_inst

    def bdb_run(self, statements):
        self.create_module(statements)
        bdb_inst = BdbTest(self, skip=self.skip, sigint=self.sigint)
        try:
            bdb_inst.run(compile(textwrap.dedent(statements),
                                            TEST_MODULE, 'exec'))
        except self.failureException as err:
            # Do not show the BdbTest traceback when the test fails.
            raise self.failureException() from err
        self.assertFalse(bdb_inst.send_list,
                'All send_expect sequences have not been processed.')

        # This is needed to have the search for reference leaks successfull,
        # why is it needed ?
        import gc; gc.collect()

    def bdb_runeval(self, expr, globals=None, locals=None):
        bdb_inst = BdbTest(self, skip=self.skip, sigint=self.sigint)
        try:
            bdb_inst.runeval(expr, globals, locals)
        except self.failureException as err:
            # Do not show the BdbTest traceback when the test fails.
            raise self.failureException() from err
        self.assertFalse(bdb_inst.send_list,
                'All send_expect sequences have not been processed.')

    def restart_runcall(self, bdb_inst, new_statements, func, *args, **kwds):
        with open(TEST_MODULE, 'w') as f:
            f.write(textwrap.dedent(new_statements))
        if hasattr(importlib, 'invalidate_caches'):
            importlib.invalidate_caches()

        # Initialize the test again.
        bdb_inst.init_test()

        bdb_inst.restart()
        self.assertFalse('bdb_test_module' in sys.modules,
                'bdb_test_module has not been removed from sys.modules.')

        # We need to remove the compiled file because the timestamp
        # of the latest bdb_test_module.py may be the same as the one
        # from the previous run, due to the test being this fast.
        support.forget('bdb_test_module')

        try:
            bdb_inst.runcall(dbg_module)
        except self.failureException as err:
            # Do not show the BdbTest traceback when the test fails.
            raise self.failureException() from err
        self.assertFalse(bdb_inst.send_list,
                'All send_expect sequences have not been processed.')

class RunCallTestCase(SetMethodTestCase):
    """Test step, next, return, until and quit set methods."""

    def test_step(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            STEP, ('line', 2, 'dbg_foo'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_step_on_last_statement(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            break_lineno(10), ('line', 1, 'dbg_foo'),
            CONTINUE, ('line', 10, 'dbg_foo', ({1:1}, [])),
            STEP, ('return', 10, 'dbg_foo'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_step_at_return_with_no_trace_in_caller(self):
        self.create_module("""
            def foo():
                lno = 3
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            foo()
            lno = 4
        """)
        self.send_expect = [
            break_func('foo', 'test_module_2.py'), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            STEP, ('return', 3, 'foo'),
            STEP, ('line', 4, '<module>'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_step_at_exception_with_no_trace_in_caller(self):
        self.create_module("""
            def foo():
                x = 1 / 0
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            try:
                foo()
            except Exception:
                lno = 6
            lno = 7
        """)
        self.send_expect = [
            break_func('foo', 'test_module_2.py'), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            STEP, ('exception', 3, 'foo'),
            STEP, ('return', 3, 'foo'),
            STEP, ('exception', 4, '<module>'),
            STEP, ('line', 5, '<module>'),
            STEP, ('line', 6, '<module>'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_next(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            NEXT, ('line', 4, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_bar'),
            STEP, ('line', 2, 'dbg_bar'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_next_on_plain_statement(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            NEXT, ('line', 2, 'dbg_foo'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_next_on_last_statement(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            break_lineno(10), ('line', 1, 'dbg_foo'),
            CONTINUE, ('line', 10, 'dbg_foo', ({1:1}, [])),
            NEXT, ('return', 10, 'dbg_foo'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_next_in_calling_frame(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            UP, ('line', 3, 'dbg_foobar'),
            NEXT, ('line', 4, 'dbg_foobar'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_next_at_return_with_no_trace_in_caller(self):
        self.create_module("""
            def foo():
                lno = 3
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            foo()
            lno = 4
            lno = 5
        """)
        self.send_expect = [
            break_func('foo', 'test_module_2.py'), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            NEXT, ('return', 3, 'foo'),
            NEXT, ('line', 4, '<module>'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_next_at_frame_with_no_trace_function(self):
        self.create_module("""
            def foo_3():
                lno = 3
        """, 'test_module_3')
        self.create_module("""
            from test_module_3 import foo_3
            def foo():
                foo_3()
                lno = 5
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            foo()
            lno = 4
        """)
        self.send_expect = [
            break_func('foo_3', 'test_module_3.py'), (),
            CONTINUE, ('line', 3, 'foo_3', ({1:1}, [])),
            UP, (),
            NEXT, ('line', 5, 'foo'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_return(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            STEP, ('line', 2, 'dbg_foo'),
            RETURN, ('return', 10, 'dbg_foo'),
            STEP, ('line', 4, 'dbg_foobar'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_return_in_calling_frame(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            UP, ('line', 3, 'dbg_foobar'),
            RETURN, ('return', 7, 'dbg_foobar'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_return_at_return_with_no_trace_in_caller(self):
        self.create_module("""
            def foo():
                lno = 3
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            foo()
            lno = 4
        """)
        self.send_expect = [
            break_func('foo', 'test_module_2.py'), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            STEP, ('return', 3, 'foo'),
            RETURN, ('line', 4, '<module>'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_return_at_frame_with_no_trace_function(self):
        self.create_module("""
            def foo_3():
                lno = 3
        """, 'test_module_3')
        self.create_module("""
            from test_module_3 import foo_3
            def foo():
                foo_3()
                lno = 5
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            foo()
            lno = 4
        """)
        self.send_expect = [
            break_func('foo_3', 'test_module_3.py'), (),
            CONTINUE, ('line', 3, 'foo_3', ({1:1}, [])),
            UP, (),
            RETURN, ('return', 5, 'foo'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_until(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            STEP, ('line', 2, 'dbg_foo'),
            until(9), ('line', 10, 'dbg_foo'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_until_stop_when_frame_returns(self):
        self.send_expect = [
            break_func('dbg_foo'), (),
            CONTINUE, ('line', 2, 'dbg_foo', ({1:1}, [])),
            until(9999), ('return', 10, 'dbg_foo'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_until_in_calling_frame(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            UP, ('line', 3, 'dbg_foobar'),
            until(6), ('line', 6, 'dbg_foobar'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_until_at_return_with_no_trace_in_caller(self):
        self.create_module("""
            def foo():
                lno = 3
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            foo()
            lno = 4
        """)
        self.send_expect = [
            break_func('foo', 'test_module_2.py'), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            STEP, ('return', 3, 'foo'),
            UNTIL, ('line', 4, '<module>'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_until_at_frame_with_no_trace_function(self):
        self.create_module("""
            def foo_3():
                lno = 3
        """, 'test_module_3')
        self.create_module("""
            from test_module_3 import foo_3
            def foo():
                foo_3()
                lno = 5
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            foo()
            lno = 4
        """)
        self.send_expect = [
            break_func('foo_3', 'test_module_3.py'), (),
            CONTINUE, ('line', 3, 'foo_3', ({1:1}, [])),
            UP, (),
            UNTIL, ('line', 5, 'foo'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_skip(self):
        self.set_skip(('importlib*', '_abcoll', 'os', 'bdb_test_module'))
        self.addCleanup(self.set_skip, None)
        self.create_module("""
            lno = 2
        """)
        self.send_expect = [
            STEP, ('line', 2, 'dbg_module'),
            STEP, ('line', 3, 'dbg_module'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_down(self):
        self.send_expect = [
            DOWN, (),
        ]
        self.assertRaises(bdb.BdbError, self.runcall, dbg_foobar)

    def test_up(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            STEP, ('line', 3, 'dbg_foobar'),
            STEP, ('call', 1, 'dbg_foo'),
            UP, ('line', 3, 'dbg_foobar'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_frame_is_oldest_frame(self):
        # Check that the first frame is the oldest frame.
        self.send_expect = [
            UP, (),
        ]
        self.assertRaises(bdb.BdbError, self.runcall, dbg_foobar)

    def test_quit(self):
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_trace_and_profile(self):
        # Test that the tracer is restored in the caller when the local trace
        # is set.
        self.set_skip(('importlib*', '_abcoll', 'os', 'bdb_test_module'))
        self.addCleanup(self.set_skip, None)
        self.create_module("""
            def foo():
                lno = 3
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo
            foo()
        """)
        self.send_expect = [
            STEP, ('line', 2, 'dbg_module'),
            # The next lines execute the test_module_2 module.
            STEP, ('call', 2, '<module>'),
            STEP, ('line', 2, '<module>'),
            STEP, ('return', 2, '<module>'),
            # Now entering function foo.
            STEP, ('call', 2, 'foo'),
            STEP, ('line', 3, 'foo'),
            STEP, ('return', 3, 'foo'),
            STEP, ('line', 3, 'dbg_module'),
            STEP, ('return', 3, 'dbg_module'),
            STEP, (),
        ]
        self.runcall(dbg_module)

    def test_next_command_in_generator(self):
        self.create_module("""
            def test_gen():
                yield 0
                lno = 4
                return 123

            it = test_gen()
            next(it)
            next(it)
        """)
        self.send_expect = [
            break_func('test_gen', TEST_MODULE), (),
            CONTINUE, ('line', 3, 'test_gen', ({1:1}, [])),
            NEXT, ('line', 4, 'test_gen'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_return_command_in_generator(self):
        self.create_module("""
            def test_gen():
                yield 0
                lno = 4
                return 123

            it = test_gen()
            next(it)
            next(it)
            lno = 10
        """)
        self.send_expect = [
            break_func('test_gen', TEST_MODULE), (),
            CONTINUE, ('line', 3, 'test_gen', ({1:1}, [])),
            RETURN, ('exception', 9, '<module>', (StopIteration, )),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_until_command_in_generator(self):
        self.create_module("""
            def test_gen():
                yield 0
                lno = 4
                return 123

            def foobar():
                it = test_gen()
                next(it)
                next(it)

            def foo():
                lno = 13
                foobar()

            foo()
        """)
        self.send_expect = [
            break_func('foo', TEST_MODULE), (),
            CONTINUE, ('line', 13, 'foo', ({1:1}, [])),
            STEP, ('line', 14, 'foo'),
            STEP, ('call', 7, 'foobar'),
            STEP, ('line', 8, 'foobar'),
            STEP, ('line', 9, 'foobar'),
            STEP, ('call', 2, 'test_gen'),
            ('until', (4, )), ('line', 4, 'test_gen'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_next_command_in_generator_for_loop(self):
        self.create_module("""
            def test_gen():
                yield 0
                lno = 4
                yield 1
                return 123

            for i in test_gen():
                lno = 9
            lno = 10
        """)
        self.send_expect = [
            break_func('test_gen', TEST_MODULE), (),
            CONTINUE, ('line', 3, 'test_gen', ({1:1}, [])),
            NEXT, ('line', 4, 'test_gen'),
            NEXT, ('line', 5, 'test_gen'),
            NEXT, ('line', 6, 'test_gen'),
            NEXT, ('exception', 8, '<module>', (StopIteration, )),
            STEP, ('line', 10, '<module>'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_next_command_in_generator_with_subiterator(self):
        self.create_module("""
            def test_subgen():
                yield 0
                return 123

            def test_gen():
                x = yield from test_subgen()
                return 456

            for i in test_gen():
                lno = 11
            lno = 12
        """)
        self.send_expect = [
            break_func('test_gen', TEST_MODULE), (),
            CONTINUE, ('line', 7, 'test_gen', ({1:1}, [])),
            NEXT, ('line', 8, 'test_gen'),
            NEXT, ('exception', 10, '<module>', (StopIteration, )),
            STEP, ('line', 12, '<module>'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_return_command_in_generator_with_subiterator(self):
        self.create_module("""
            def test_subgen():
                yield 0
                return 123

            def test_gen():
                x = yield from test_subgen()
                return 456

            for i in test_gen():
                lno = 11
            lno = 12
        """)
        self.send_expect = [
            break_func('test_subgen', TEST_MODULE), (),
            CONTINUE, ('line', 3, 'test_subgen', ({1:1}, [])),
            RETURN, ('exception', 7, 'test_gen', (StopIteration, )),
            RETURN, ('exception', 10, '<module>', (StopIteration, )),
            STEP, ('line', 12, '<module>'),
            QUIT, (),
        ]
        self.runcall(dbg_module)

class BreakpointTestCase(SetMethodTestCase):
    """Test the breakpoint set method."""

    def test_comment(self):
        # Stop when a breakpoint is set on a comment.
        self.create_module("""
            # Comment.
            lno = 3
        """)
        self.send_expect = [
            break_lineno(2, TEST_MODULE), (None, 1, 'dbg_module'),
            CONTINUE, ('line', 3, '<module>', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_empty_line(self):
        # Stop when a breakpoint is set on an empty line.
        self.create_module("""
            lno = 2
        """)
        self.send_expect = [
            break_lineno(1, TEST_MODULE), (),
            CONTINUE, ('line', 2, '<module>', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_non_existent_module(self):
        self.send_expect = [
            break_lineno(2, 'non_existent_module.py'), (),
        ]
        self.assertRaises(bdb.BdbError, self.runcall, dbg_module)

    def test_after_last_statement(self):
        self.create_module("""
            lno = 2
        """)
        self.send_expect = [
            break_lineno(4, TEST_MODULE), (),
        ]
        self.assertRaises(bdb.BdbError, self.runcall, dbg_module)

    def test_nested_function(self):
        # Stop at breakpoint set on a nested function definition.
        self.create_module("""
            def foo():
                def bar():
                    lno = 4
                bar()

            foo()
        """)
        self.send_expect = [
            break_lineno(3, TEST_MODULE), (),
            CONTINUE, ('line', 4, 'bar', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_nested_method(self):
        # Stop at breakpoint set on a nested method definition.
        self.create_module("""
            def foo():
                class C:
                    def c_method(self):
                        lno = 5
                C().c_method()

            foo()
        """)
        self.send_expect = [
            break_lineno(4, TEST_MODULE), (),
            CONTINUE, ('line', 5, 'c_method', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_next_function(self):
        # Stop at first statement of next function when breakpoint set between
        # function definitions.
        self.create_module("""
            def foo():
                lno = 3

            def bar():

                lno = 7

            bar()
        """)
        self.send_expect = [
            break_lineno(4, TEST_MODULE), (),
            CONTINUE, ('line', 7, 'bar', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_next_method(self):
        # Stop at first statement of next method when breakpoint set between
        # method definitions.
        self.create_module("""
            class C:
                def c_foo(self):
                    lno = 4

                def c_bar(self):

                    lno = 8

            C().c_bar()
        """)
        self.send_expect = [
            break_lineno(5, TEST_MODULE), (),
            CONTINUE, ('line', 8, 'c_bar', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_two_code_objects_with_same_firstlineno(self):
        self.create_module("""
            def foo(a, f=lambda x: x + 1):
                lno = 3

            foo(1)
        """)
        self.send_expect = [
            break_lineno(2, TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_temporary_breakpoint(self):
        self.create_module("""
            def foo():
                lno = 3

            for i in range(2):
                foo()
        """)
        self.send_expect = [
            break_lineno(2, TEST_MODULE), (),
            ('break', (TEST_MODULE, 2, True)), (),
            CONTINUE, ('line', 3, 'foo', ({1:1, 2:1}, [2])),
            CONTINUE, ('line', 3, 'foo', ({1:2}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_disabled_temporary_breakpoint(self):
        self.create_module("""
            def foo():
                lno = 3

            for i in range(3):
                foo()
        """)
        self.send_expect = [
            break_lineno(2, TEST_MODULE), (),
            ('break', (TEST_MODULE, 2, True)), (),
            disable(2), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            enable(2), (),
            CONTINUE, ('line', 3, 'foo', ({1:2, 2:1}, [2])),
            CONTINUE, ('line', 3, 'foo', ({1:3}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_breakpoint_condition(self):
        self.create_module("""
            def foo(a):
                lno = 3

            for i in range(3):
                foo(i)
        """)
        self.send_expect = [
            ('break', (TEST_MODULE, 2, False, 'a == 2')), (),
            CONTINUE, ('line', 3, 'foo', ({1:3}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_breakpoint_exception_on_condition_evaluation(self):
        self.create_module("""
            def foo(a):
                lno = 3

            foo(0)
        """)
        self.send_expect = [
            ('break', (TEST_MODULE, 2, True, '1 / a')), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_ignore_count(self):
        self.create_module("""
            def foo(a):
                lno = 3

            for i in range(2):
                foo(i)
        """)
        self.send_expect = [
            break_lineno(2, TEST_MODULE), (),
            ignore(1), ('line', 1, 'dbg_module'),
            CONTINUE, ('line', 3, 'foo', ({1:2}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_ignore_count_on_disabled_breakpoint(self):
        self.create_module("""
            def foo(a):
                lno = 3

            for i in range(3):
                foo(i)
        """)
        self.send_expect = [
            break_lineno(2, TEST_MODULE), (),
            break_lineno(2, TEST_MODULE), (),
            ignore(1), ('line', 1, 'dbg_module'),
            disable(1), (),
            CONTINUE, ('line', 3, 'foo', ({2:1}, [])),
            enable(1), (),
            CONTINUE, ('line', 3, 'foo', ({2:2}, [])),
            CONTINUE, ('line', 3, 'foo', ({1:2, 2:3}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_ignore_count_on_out_of_range_breakpoint(self):
        self.send_expect = [
            ignore(1), (),
        ]
        self.assertRaises(ValueError, self.runcall, dbg_foobar)

    def test_enable_disable(self):
        self.create_module("""
            def foo():
                lno = 3

            for i in range(3):
                foo()
        """)
        self.send_expect = [
            break_lineno(2, TEST_MODULE), (),
            break_lineno(2, TEST_MODULE), (),
            disable(1), (),
            CONTINUE, ('line', 3, 'foo', ({2:1}, [])),
            enable(1), (),
            disable(2), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            enable(2), (),
            CONTINUE, ('line', 3, 'foo', ({1:2, 2:2}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_ignore_count_on_deleted_breakpoint(self):
        self.create_module("""
            def foo():
                lno = 3

            foo()
        """)
        self.send_expect = [
            ('break', (TEST_MODULE, 2, True)), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [1])),
            ignore(1), (),
            QUIT, (),
        ]
        self.assertRaises(ValueError, self.runcall, dbg_module)

    def test_breakpoint_on_function(self):
        self.create_module("""
            def foo():
                lno = 3

            foo()
        """)
        self.send_expect = [
            break_func('foo', TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_breakpoint_on_non_existent_function(self):
        self.create_module("""
            def foo():
                lno = 3
        """)
        self.send_expect = [
            break_func('bar', TEST_MODULE), (),
        ]
        self.assertRaises(bdb.BdbError, self.runcall, dbg_module)

    def test_clear(self):
        self.create_module("""
            def foo():

                lno = 3

            for i in range(2):
                foo()
        """)
        self.send_expect = [
            break_lineno(3, TEST_MODULE), (),
            break_lineno(4, TEST_MODULE), (),
            CONTINUE, ('line', 4, 'foo', ({1:1, 2:1}, [])),
            clear(3, TEST_MODULE), (),
            CONTINUE, ('line', 4, 'foo', ({2:2}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_clear_two_breakpoints(self):
        self.create_module("""
            def foo():

                lno = 3

            for i in range(2):
                foo()
        """)
        self.send_expect = [
            break_lineno(3, TEST_MODULE), (),
            break_lineno(3, TEST_MODULE), (),
            break_lineno(4, TEST_MODULE), (),
            CONTINUE, ('line', 4, 'foo', ({1:1, 2:1, 3:1}, [])),
            clear(3, TEST_MODULE), (),
            CONTINUE, ('line', 4, 'foo', ({3:2}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_clear_at_no_breakpoint(self):
        self.send_expect = [
            clear(2), (),
        ]
        self.assertRaises(bdb.BdbError, self.runcall, dbg_foobar)

    def test_clear_bp_set_bp_in_same_function(self):
        # Check that the reference to the code_bps dictionary has not changed
        # after the dictionary has been emptied.
        self.create_module("""
            def foo():
                lno = 3

            for i in range(2):
                foo()
        """)
        self.send_expect = [
            break_lineno(3, TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            clear(3, TEST_MODULE), (),
            break_lineno(3, TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({2:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_restart_new_breakpoint(self):
        # Set a breakpoint on a function, after source code changes and a
        # restart.
        self.create_module("""
            def foo():
                lno = 3

            foo()
        """)
        self.send_expect = [
            break_lineno(3, TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            QUIT, (),
        ]
        self.set_restart(True)
        self.addCleanup(self.set_restart, False)
        bdb_inst = self.runcall(dbg_module)

        # Restart the debugger with a changed bdb_test_module.
        new_statements = """
            def foo():
                lno = 3
                bar()

            def bar():
                lno = 7

            foo()
        """
        self.send_expect = [
            break_func('bar', TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:2}, [])),
            CONTINUE, ('line', 7, 'bar', ({2:1}, [])),
            QUIT, (),
        ]
        self.restart_runcall(bdb_inst, new_statements, dbg_module)

    def test_restart_bp_after_last_line(self):
        # A breakpoint is deleted on restart when its line number is greater
        # than the new module line size.
        self.create_module("""
            def foo():
                lno = 3

            foo()
        """)
        self.send_expect = [
            break_lineno(5, TEST_MODULE), (),
            CONTINUE, ('line', 5, '<module>', ({1:1}, [])),
            QUIT, (),
        ]
        self.set_restart(True)
        self.addCleanup(self.set_restart, False)
        bdb_inst = self.runcall(dbg_module)

        # Restart the debugger with a changed bdb_test_module.
        new_statements = """
            def foo():
                lno = 3
            foo()
        """
        self.send_expect = [
            CONTINUE, (),
        ]
        self.restart_runcall(bdb_inst, new_statements, dbg_module)

    def test_restart_no_lines(self):
        # Test the corner case where all lines are removed.
        self.create_module("""
            def foo():
                lno = 3

            foo()
        """)
        self.send_expect = [
            break_lineno(3, TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            QUIT, (),
        ]
        self.set_restart(True)
        self.addCleanup(self.set_restart, False)
        bdb_inst = self.runcall(dbg_module)

        # Restart the debugger with a changed bdb_test_module.
        new_statements = ""
        self.send_expect = [
            CONTINUE, (),
        ]
        self.restart_runcall(bdb_inst, new_statements, dbg_module)

    def test_restart_syntax_error(self):
        # Test the corner case where a syntax error in the changed code.
        self.create_module("""
            def foo():
                lno = 3

            foo()
        """)
        self.send_expect = [
            break_lineno(3, TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            QUIT, (),
        ]
        self.set_restart(True)
        self.addCleanup(self.set_restart, False)
        bdb_inst = self.runcall(dbg_module)

        # Restart the debugger with a changed bdb_test_module.
        new_statements = """
            def foo()
                lno = 3

            foo()
        """
        self.send_expect = [
            CONTINUE, (),
        ]
        self.assertRaises(bdb.BdbSyntaxError, self.restart_runcall,
                                bdb_inst, new_statements, dbg_module)

class RunTestCase(SetMethodTestCase):
    """Test run, runeval and set_trace."""

    def test_run_step(self):
        # Check that bdb run method stops at the first line event and that bdb
        # does not step into its own code on returning from the last frame.
        statements = """
            lno = 2
        """
        self.send_expect = [
            STEP, ('return', 2, '<module>'),
            STEP, (),
        ]
        self.bdb_run(statements)

    def test_run_step_into_a_function_and_get_call_event(self):
        statements = """
            def foo():
                lno = 3

            foo()
        """
        self.send_expect = [
            STEP, ('line', 5, '<module>'),
            STEP, ('call', 2, 'foo'),
            QUIT, (),
        ]
        self.bdb_run(statements)

    def test_runeval_step(self):
        # Check that bdb does not step into its own code on returning from the
        # expression evaluated by runeval.
        self.create_module("""
            def foo():
                lno = 3
        """)
        self.send_expect = [
            STEP, ('call', 2, 'foo'),
            STEP, ('line', 3, 'foo'),
            STEP, ('return', 3, 'foo'),
            STEP, ('return', 1, '<module>'),
            STEP, (),
        ]
        import bdb_test_module
        self.bdb_runeval('bdb_test_module.foo()', globals(), locals())

    @unittest.skipIf(sys.platform == 'win32', 'a posix test')
    def test_set_trace_step(self):
        # Check that bdb does not step into its own code when handling SIGINT.
        self.create_module("""
            import os
            import signal

            pid = os.getpid()
            os.kill(pid, signal.SIGINT)
            lno = 7
        """)
        self.send_expect = [
            break_lineno(3), (),
            CONTINUE, ('line', 7, '<module>'),
            STEP, ('return', 7, '<module>'),
            CONTINUE, ('line', 3, 'dbg_module', ({1:1}, [])),
            STEP, ('return', 3, 'dbg_module'),
            STEP, (),
        ]
        self.set_sigint(True)
        self.addCleanup(self.set_sigint, False)
        self.runcall(dbg_module)

    def test_run_frame_is_oldest_frame(self):
        # Check that the first frame is the oldest frame.
        statements = """
            lno = 2
        """
        self.send_expect = [
            UP, (),
        ]
        self.assertRaises(bdb.BdbError, self.bdb_run, statements)

    def test_runeval_frame_is_oldest_frame(self):
        # Check that the first frame is the oldest frame.
        self.create_module("""
            def foo():
                lno = 3
        """)
        self.send_expect = [
            STEP, ('call', 2, 'foo'),
            UP, (),
            UP, (),
        ]
        import bdb_test_module
        self.assertRaises(bdb.BdbError, self.bdb_runeval,
                            'bdb_test_module.foo()', globals(), locals())

    @unittest.skipIf(sys.platform == 'win32', 'a posix test')
    def test_set_trace_frame_is_oldest_frame(self):
        # Check that the first frame is the oldest frame.
        self.create_module("""
            import os
            import signal

            pid = os.getpid()
            os.kill(pid, signal.SIGINT)
            lno = 7
        """)
        self.send_expect = [
            break_lineno(3), (),
            CONTINUE, ('line', 7, '<module>'),
            STEP, ('return', 7, '<module>'),
            CONTINUE, ('line', 3, 'dbg_module', ({1:1}, [])),
            UP, (),
        ]
        self.set_sigint(True)
        self.addCleanup(self.set_sigint, False)
        self.assertRaises(bdb.BdbError, self.runcall, dbg_module)

    def test_run_quit(self):
        statements = """
            lno = 2
            lno = 3
        """
        self.send_expect = [
            STEP, ('line', 3, '<module>'),
            QUIT, (),
        ]
        self.bdb_run(statements)

    def test_runeval_quit(self):
        self.create_module("""
            def foo():
                lno = 3
        """)
        self.send_expect = [
            STEP, ('call', 2, 'foo'),
            STEP, ('line', 3, 'foo'),
            QUIT, (),
        ]
        import bdb_test_module
        self.bdb_runeval('bdb_test_module.foo()', globals(), locals())

    @unittest.skipIf(sys.platform == 'win32', 'a posix test')
    def test_set_trace_breakpoint(self):
        # Check that bdb stops at a breakpoint set in a caller after interrupt.
        self.create_module("""
            import os
            import signal

            def foo():
                pid = os.getpid()
                os.kill(pid, signal.SIGINT)
                lno = 8

            def main():
                foo()
                lno = 12

            main()
        """)
        self.send_expect = [
            CONTINUE, ('line', 8, 'foo'),
            break_lineno(12, TEST_MODULE), (),
            CONTINUE, ('line', 12, 'main', ({1:1}, [])),
            QUIT, (),
        ]
        self.set_sigint(True)
        self.addCleanup(self.set_sigint, False)
        self.runcall(dbg_module)

class IssueTestCase(SetMethodTestCase):
    """Test fixed issues."""

    def test_python_issue_6322(self):
        # Set breakpoints on statement lines without bytecode, for example:
        # global, else, finally.
        self.send_expect = [
            break_lineno(3), (),
            break_lineno(7), (),
            break_lineno(9), (),
            CONTINUE, ('line', 4, 'dbg_foo', ({1:1}, [])),
            CONTINUE, ('line', 8, 'dbg_foo', ({2:1}, [])),
            CONTINUE, ('line', 10, 'dbg_foo', ({3:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_foo)

    def test_python_issue_14789(self):
        # Set two breakpoints on the same function.
        self.send_expect = [
            break_func('dbg_foo'), (),
            break_func('dbg_foo'), (),
            CONTINUE, ('line', 2, 'dbg_foo', ({1:1, 2:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_foobar)

    def test_python_issue_14792(self):
        # Set a breakpoint on a function from within that function and check
        # that the debugger does not stop in the function.
        self.send_expect = [
            STEP, ('line', 2, 'dbg_foobar'),
            break_func('dbg_foobar'), (),
            CONTINUE, (),
        ]
        self.runcall(dbg_foobar)

    def test_python_issue_14808(self):
        # Set a breakpoint on the first line of a function definition.
        self.create_module("""
            def foo():
                lno = 3

            def bar():
                lno = 6

            foo()
            bar()
        """)
        self.send_expect = [
            break_lineno(2, TEST_MODULE), (),
            break_func('bar', TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            CONTINUE, ('line', 6, 'bar', ({2:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_python_issue_14795(self):
        # Set a breakpoint on a method whose class definition has not yet been
        # executed.
        self.create_module("""
            class C:
                def c_method(self):
                    lno = 4

            C().c_method()
        """)
        self.send_expect = [
            break_func('C.c_method', TEST_MODULE), (),
            CONTINUE, ('line', 4, 'c_method', ({1:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_python_issue_14751(self):
        # Set a breakpoint in the call stack.
        self.create_module("""
            def foo_2():
                lno = 3
        """, 'test_module_2')
        self.create_module("""
            from test_module_2 import foo_2
            def foo():
                foo_2()
                lno = 5

            foo()
        """)
        self.send_expect = [
            break_func('foo_2', 'test_module_2.py'), (),
            CONTINUE, ('line', 3, 'foo_2', ({1:1}, [])),
            break_lineno(5, TEST_MODULE), (),
            CONTINUE, ('line', 5, 'foo', ({2:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

    def test_python_issue_14743(self):
        # Check that runcall stops at the call event and that bdb does not step
        # into its own code on returning from the last frame.
        self.send_expect = [
            STEP, ('line', 2, 'dbg_bar'),
            STEP, ('return', 2, 'dbg_bar'),
            STEP, (),
        ]
        self.runcall(dbg_bar)

    def test_python_issue_16446(self):
        # The quit command ends the debugging session and the program continues
        # its normal execution when the debugging session is started with
        # set_trace.
        self.send_expect = [
            QUIT, (),
        ]
        bdb_inst = BdbTest(self)
        bdb_inst.set_trace()
        self.assertFalse(bdb_inst.send_list,
                'All send_expect sequences have not been processed.')

    def test_python_issue_14912(self):
        # Stop at a breakpoint after source code changes and a restart.
        self.create_module("""
            def foo():
                lno = 3
                lno = 4

            foo()
        """)
        self.send_expect = [
            break_func('foo', TEST_MODULE), (),
            break_lineno(4, TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({1:1}, [])),
            CONTINUE, ('line', 4, 'foo', ({2:1}, [])),
            # Make sure bdb_test_module is imported so that we may test
            # later that it is removed by _module_finder on restart.
            CONTINUE, (),
        ]
        self.set_restart(True)
        self.addCleanup(self.set_restart, False)
        bdb_inst = self.runcall(dbg_module)

        # Restart the debugger with a changed bdb_test_module.
        new_statements = """
            def bar():
                lno = 3

            def foo():
                lno = 6
                bar()

            foo()
        """
        self.send_expect = [
            CONTINUE, ('line', 6, 'foo', ({2:2}, [])),
            CONTINUE, ('line', 3, 'bar', ({1:2}, [])),
            QUIT, (),
        ]
        self.restart_runcall(bdb_inst, new_statements, dbg_module)

    def test_python_issue_16482(self):
        # Check the frame line number after a 'continue' command while no
        # breakpoints are set.
        self.create_module("""
            import sys

            f = sys._getframe()
            # The test is pass when we raise ValueError.
            if f.f_lineno == 6:
                raise ValueError
        """)
        self.send_expect = [
            STEP, ('line', 2, 'dbg_module'),
            STEP, ('call', 2, '<module>'),
            CONTINUE, (),
        ]
        self.set_skip(('importlib*', '_abcoll', 'os'))
        self.addCleanup(self.set_skip, None)
        self.assertRaises(ValueError, self.runcall, dbg_module)

    def test_pdb_clone_issue_6(self):
        # Stop at breakpoint set in function after all breakpoints in the
        # function have been cleared.
        self.create_module("""
            def foo():
                lno = 3

            foo()
        """)
        self.send_expect = [
            break_lineno(3, TEST_MODULE), (),
            clear(3, TEST_MODULE), (),
            break_lineno(3, TEST_MODULE), (),
            CONTINUE, ('line', 3, 'foo', ({2:1}, [])),
            QUIT, (),
        ]
        self.runcall(dbg_module)

