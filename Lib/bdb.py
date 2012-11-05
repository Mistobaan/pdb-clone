"""Debugger basics"""

import fnmatch
import sys
import os
import linecache
import token
import tokenize
import itertools
import types
from bisect import bisect
from operator import attrgetter

__all__ = ["BdbQuit", "Bdb", "Breakpoint"]

# A dictionary mapping a filename to a BdbModule instance.
_modules = {}
_fncache = {}

def canonic(filename):
    if filename == "<" + filename[1:-1] + ">":
        return filename
    canonic = _fncache.get(filename)
    if not canonic:
        canonic = os.path.abspath(filename)
        canonic = os.path.normcase(canonic)
        _fncache[filename] = canonic
    return canonic

def code_line_numbers(code):
    # Source code line numbers generator (see Objects/lnotab_notes.txt).
    valid_lno = lno = code.co_firstlineno
    yield valid_lno
    # The iterator yields (line_incr[i], byte_incr[i+1]) from lnotab.
    for line_incr, byte_incr in itertools.islice(zip(code.co_lnotab,
                    itertools.chain(code.co_lnotab[1:], [1])), 1, None, 2):
        lno += line_incr
        if byte_incr == 0:
            continue
        if lno != valid_lno:
            valid_lno = lno
            yield valid_lno

def reiterate(it):
    """Iterator wrapper allowing to reiterate on items with send()."""
    while True:
        item = next(it)
        val = (yield item)
        # Reiterate while the sent value is true.
        while val:
            # The return value of send().
            yield item
            val = (yield item)

class BdbError(Exception):
    """Generic bdb exception."""

class BdbQuit(Exception):
    """Exception to give up completely."""

class BdbModule:
    """A module.

    Instance attributes:
        functions_firstlno: a dictionary mapping function names and fully
        qualified method names to their first line number.
    """

    def __init__(self, filename):
        self.filename = filename
        self.functions_firstlno = None
        self.source_lines = linecache.getlines(filename)
        if not self.source_lines:
            raise BdbError('No lines in {}.'.format(filename))
        try:
            self.code = compile(''.join(self.source_lines), filename, 'exec')
        except (SyntaxError, TypeError) as err:
            raise BdbError('{}: {}.'.format(filename, err))

    def get_func_lno(self, funcname):
        """The first line number of the last defined 'funcname' function."""
        if self.functions_firstlno is None:
            self.functions_firstlno = {}
            self.parse(reiterate(tokenize.generate_tokens(
                                    iter(self.source_lines).__next__)))
        try:
            return self.functions_firstlno[funcname]
        except KeyError:
            raise BdbError('{}: function "{}" not found.'.format(
                self.filename, funcname))

    def get_actual_bp(self, lineno):
        """Get the actual breakpoint line number.

        When an exact match cannot be found in the lnotab expansion of the
        module code object or one of its subcodes, pick up the next valid
        statement line number.

        Return the statement line defined by the tuple (code firstlineno,
        statement line number) which is at the shortest distance to line
        'lineno' and greater or equal to 'lineno'. When 'lineno' is the first
        line number of a subcode, use its first statement line instead.
        """

        def _distance(code, module_level=False):
            """The shortest distance to the next valid statement."""
            subcodes = dict((c.co_firstlineno, c) for c in code.co_consts
                                if isinstance(c, types.CodeType) and not
                                    c.co_name.startswith('<'))
            # Get the shortest distance to the subcode whose first line number
            # is the last to be less or equal to lineno. That is, find the
            # index of the first subcode whose first_lno is the first to be
            # strictly greater than lineno.
            subcode_dist = None
            subcodes_flnos = sorted(subcodes)
            idx = bisect(subcodes_flnos, lineno)
            if idx != 0:
                flno = subcodes_flnos[idx-1]
                subcode_dist = _distance(subcodes[flno])

            # Check if lineno is a valid statement line number in the current
            # code, excluding function or method definition lines.
            code_lnos = sorted(code_line_numbers(code))
            # Do not stop at execution of function definitions.
            if not module_level and len(code_lnos) > 1:
                code_lnos = code_lnos[1:]
            if lineno in code_lnos and lineno not in subcodes_flnos:
                return 0, (code.co_firstlineno, lineno)

            # Compute the distance to the next valid statement in this code.
            idx = bisect(code_lnos, lineno)
            if idx == len(code_lnos):
                # lineno is greater that all 'code' line numbers.
                return subcode_dist
            actual_lno = code_lnos[idx]
            dist = actual_lno - lineno
            if subcode_dist and subcode_dist[0] < dist:
                return subcode_dist
            if actual_lno not in subcodes_flnos:
                return dist, (code.co_firstlineno, actual_lno)
            else:
                # The actual line number is the line number of the first
                # statement of the subcode following lineno (recursively).
                return _distance(subcodes[actual_lno])

        code_dist = _distance(self.code, module_level=True)
        if not code_dist:
            raise BdbError('{}: line {} is after the last '
                'valid statement.'.format(self.filename, lineno))
        return code_dist[1]

    def parse(self, tok_generator, cindent=0, clss=None):
        func_lno = 0
        indent = 0
        try:
            for tokentype, tok, srowcol, _end, _line in tok_generator:
                if tokentype == token.DEDENT:
                    # End of function definition.
                    if func_lno and srowcol[1] <= indent:
                        func_lno = 0
                    # End of class definition.
                    if clss and srowcol[1] <= cindent:
                        return
                elif tok == 'def' or tok == 'class':
                    if func_lno and srowcol[1] <= indent:
                        func_lno = 0
                    if clss and srowcol[1] <= cindent:
                        tok_generator.send(1)
                        return
                    tokentype, name = next(tok_generator)[0:2]
                    if tokentype != token.NAME:
                        continue  # syntax error
                    # Nested def or class in a function.
                    if func_lno:
                            continue
                    if clss:
                        name = '{}.{}'.format(clss, name)
                    if tok == 'def':
                        lineno, indent = srowcol
                        func_lno = lineno
                        self.functions_firstlno[name] = lineno
                    else:
                        self.parse(tok_generator, srowcol[1], name)
        except StopIteration:
            pass

class ModuleBreakpoints:
    """The breakpoints of a module.

    The 'breakpts' attribute is a dictionary that maps a code firstlineno to a
    'line_bps' dictionary that maps each line number of the code, where one or
    more breakpoints are set, to the list of corresponding Breakpoint
    instances.

    Note:
    A line in 'line_bps' is the actual line of the breakpoint (the line where the
    debugger stops), this line may differ from the line attribute of the
    Breakpoint instance as set by the user.
    """

    def __init__(self, filename):
        if filename not in _modules:
            _modules[filename] = BdbModule(filename)
        self.bdb_module = _modules[filename]
        self.breakpts = {}

    def add_breakpoint(self, bp):
        firstlineno, actual_lno = self.bdb_module.get_actual_bp(bp.line)
        if firstlineno not in self.breakpts:
            self.breakpts[firstlineno] = {}
        line_bps = self.breakpts[firstlineno]
        if actual_lno not in line_bps:
            line_bps[actual_lno] = []
        line_bps[actual_lno].append(bp)
        return firstlineno, actual_lno

    def delete_breakpoint(self, bp):
        firstlineno, actual_lno = bp.actual_bp
        try:
            line_bps = self.breakpts[firstlineno]
            bplist = line_bps[actual_lno]
            bplist.remove(bp)
        except (KeyError, ValueError):
            assert False, ('Internal error: bpbynumber and breakpts'
                            ' are inconsistent')
        if not bplist:
            del line_bps[actual_lno]
        if not line_bps:
            del self.breakpts[firstlineno]

    def get_breakpoints(self, lineno):
        """Return the list of breakpoints set at lineno."""
        try:
            firstlineno, actual_lno = self.bdb_module.get_actual_bp(lineno)
        except BdbError:
            return []
        if firstlineno not in self.breakpts:
            return []
        line_bps = self.breakpts[firstlineno]
        if actual_lno not in line_bps:
            return []
        return [bp for bp in sorted(line_bps[actual_lno],
                    key=attrgetter('number')) if bp.line == lineno]

    def all_breakpoints(self):
        bpts = []
        for line_bps in self.breakpts.values():
            for bplist in line_bps.values():
                bpts.extend(bplist)
        return [bp for bp in sorted(bpts, key=attrgetter('number'))]

class Bdb:
    """Generic Python debugger base class.

    This class takes care of details of the trace facility;
    a derived class should implement user interaction.
    The standard debugger class (pdb.Pdb) is an example.

    The 'stopframe_lno' attribute is a tuple of (stopframe, lineno) where:
        'stopframe' is the frame where the debugger must stop. With a value of
        None, it means stop at any frame. When not None, the debugger stops at
        the 'return' debug event in that frame, whatever the value of 'lineno'.

        The debugger stops when the current line number in 'stopframe' is
        greater or equal to 'lineno'. The value of -1 means the infinite line
        number, i.e. don't stop.

        Therefore:
            (None, 0):   always stop
            (None, -1):  never stop
            (frame, 0):  stop on next statement in that frame
            (frame, -1): stop when returning from frame
    """

    def __init__(self, skip=None):
        self.skip = set(skip) if skip else None
        # A dictionary mapping a filename to a ModuleBreakpoints instance.
        self.breakpoints = {}

        # Backward compatibility
    def canonic(self, filename):
        return canonic(filename)

    def reset(self):
        linecache.checkcache()
        self.botframe = None
        self._curframe = None
        self._set_stopinfo((None, 0))

    def trace_dispatch(self, frame, event, arg):
        self._curframe = frame
        if self.quitting:
            return # None
        if event == 'line':
            return self.dispatch_line(frame)
        if event == 'call':
            return self.dispatch_call(frame, arg)
        if event == 'return':
            return self.dispatch_return(frame, arg)
        if event == 'exception':
            return self.dispatch_exception(frame, arg)
        if event == 'c_call':
            return self.trace_dispatch
        if event == 'c_exception':
            return self.trace_dispatch
        if event == 'c_return':
            return self.trace_dispatch
        print('bdb.Bdb.dispatch: unknown debugging event:', repr(event))
        return self.trace_dispatch

    def dispatch_line(self, frame):
        if self.stop_here(frame):
            self.user_line(frame)
            if self.quitting: raise BdbQuit
        else:
            breakpoint_hits = self.break_here(frame)
            if breakpoint_hits:
                self.user_line(frame, breakpoint_hits)
                if self.quitting: raise BdbQuit
        return self.trace_dispatch

    def dispatch_call(self, frame, arg):
        # XXX 'arg' is no longer used
        if self.botframe is None:
            # First call of dispatch since reset()
            self.botframe = frame.f_back # (CT) Note that this may also be None!
            return self.trace_dispatch
        if not (self.stop_here(frame) or self.break_at_function(frame)):
            # No need to trace this function
            return # None
        self.user_call(frame, arg)
        if self.quitting: raise BdbQuit
        return self.trace_dispatch

    def dispatch_return(self, frame, arg):
        if self.stop_here(frame) or frame is self.stopframe_lno[0]:
            self.user_return(frame, arg)
            if self.quitting: raise BdbQuit
            # Set the trace function in the caller when returning from the
            # current frame after step, next, until, return commands.
            if (self.stopframe_lno == (None, 0) or
                                    frame is self.stopframe_lno[0]):
                if frame.f_back and not frame.f_back.f_trace:
                    frame.f_back.f_trace = self.trace_dispatch
                self._set_stopinfo((None, 0))
        return self.trace_dispatch

    def dispatch_exception(self, frame, arg):
        if self.stop_here(frame):
            self.user_exception(frame, arg)
            if self.quitting: raise BdbQuit
        return self.trace_dispatch

    # Normally derived classes don't override the following
    # methods, but they may if they want to redefine the
    # definition of stopping and breakpoints.

    def is_skipped_module(self, module_name):
        for pattern in self.skip:
            if fnmatch.fnmatch(module_name, pattern):
                return True
        return False

    def stop_here(self, frame):
        if self.skip and \
               self.is_skipped_module(frame.f_globals.get('__name__')):
            return False
        stopframe, lineno = self.stopframe_lno
        if frame is stopframe or not stopframe:
            if lineno == -1:
                return False
            return frame.f_lineno >= lineno
        return False

    def break_here(self, frame):
        filename = canonic(frame.f_code.co_filename)
        if filename not in self.breakpoints:
            return None
        module_bps = self.breakpoints[filename]
        firstlineno = frame.f_code.co_firstlineno
        if (firstlineno not in module_bps.breakpts or
                frame.f_lineno not in module_bps.breakpts[firstlineno]):
            return None

        # Handle multiple breakpoints on the same line (issue 14789)
        effective_bp_list = []
        temporaries = []
        for bp in module_bps.breakpts[firstlineno][frame.f_lineno]:
            stop, delete = bp.process_hit_event(frame)
            if stop:
                effective_bp_list.append(bp.number)
                if bp.temporary and delete:
                    temporaries.append(bp.number)
        if effective_bp_list:
            return sorted(effective_bp_list), sorted(temporaries)

    def break_at_function(self, frame):
        filename = canonic(frame.f_code.co_filename)
        if filename not in self.breakpoints:
            return False
        if frame.f_code.co_firstlineno in self.breakpoints[filename].breakpts:
            return True
        return False

    # Derived classes should override the user_* methods
    # to gain control.

    def user_call(self, frame, argument_list):
        """This method is called when there is the remote possibility
        that we ever need to stop in this function."""
        pass

    def user_line(self, frame, breakpoint_hits=None):
        """This method is called when we stop or break at this line.

        'breakpoint_hits' is a tuple of the list of breakpoint numbers that
        have been hit at this line, and of the list of temporaries that must be
        deleted.
        """
        pass

    def user_return(self, frame, return_value):
        """This method is called when a return trap is set here."""
        pass

    def user_exception(self, frame, exc_info):
        """This method is called if an exception occurs,
        but only if we are to stop at or just below this level."""
        pass

    def _set_stopinfo(self, stopframe_lno):
        # Ensure that stopframe belongs to the stack frame in the interval
        # [self.botframe, self._curframe] and that it gets a trace function.
        stopframe, lineno = stopframe_lno
        frame = self._curframe
        while stopframe and frame and frame is not stopframe:
            if frame is self.botframe:
                stopframe = self.botframe
                break
            frame = frame.f_back
        if stopframe and not stopframe.f_trace:
            stopframe.f_trace = self.trace_dispatch
        self.stopframe_lno = stopframe, lineno
        self.quitting = False

    # Derived classes and clients can call the following methods
    # to affect the stepping state.

    def set_until(self, frame, lineno=None):
        """Stop when the current line number in frame is greater than lineno or
        when returning from frame."""
        if lineno is None:
            lineno = frame.f_lineno + 1
        self._set_stopinfo((frame, lineno))

    def set_step(self):
        """Stop after one line of code."""
        self._set_stopinfo((None, 0))

    def set_next(self, frame):
        """Stop on the next line in or below the given frame."""
        self._set_stopinfo((frame, 0))

    def set_return(self, frame):
        """Stop when returning from the given frame."""
        self._set_stopinfo((frame, -1))

    def set_trace(self, frame=None):
        """Start debugging from `frame`.

        If frame is not specified, debugging starts from caller's frame.
        """
        if frame is None:
            frame = sys._getframe().f_back
        self.reset()
        frame.f_trace = self.trace_dispatch
        while frame:
            self.botframe = frame
            frame = frame.f_back
        self.set_step()
        sys.settrace(self.trace_dispatch)

    def set_continue(self):
        # Don't stop except at breakpoints or when finished
        self._set_stopinfo((None, -1))
        if not self.has_breaks():
            # no breakpoints; run without debugger overhead
            sys.settrace(None)
            frame = sys._getframe().f_back
            while frame and frame is not self.botframe:
                del frame.f_trace
                frame = frame.f_back

    def set_quit(self):
        self.stopframe_lno = (None, -1)
        self.returnframe = None
        self.quitting = True
        sys.settrace(None)

    # Derived classes and clients can call the following methods
    # to manipulate breakpoints.  These methods return an
    # error message is something went wrong, None if all is well.
    # Call self.get_*break*() to see the breakpoints or better
    # for bp in Breakpoint.bpbynumber: if bp: bp.bpprint().

    def set_break(self, fname, lineno, temporary=False, cond=None,
                  funcname=None):
        filename = canonic(fname)
        if filename not in self.breakpoints:
            module_bps = ModuleBreakpoints(filename)
        else:
            module_bps = self.breakpoints[filename]
        if funcname:
            lineno = module_bps.bdb_module.get_func_lno(funcname)
        bp = Breakpoint(filename, lineno, module_bps, temporary, cond)
        if filename not in self.breakpoints:
            self.breakpoints[filename] = module_bps

        # Set the trace function when the breakpoint is set in one of the
        # frames of the frame stack.
        firstlineno, actual_lno = bp.actual_bp
        frame = self._curframe
        while frame:
            if (filename == frame.f_code.co_filename and
                        firstlineno == frame.f_code.co_firstlineno):
                if not frame.f_trace:
                    frame.f_trace = self.trace_dispatch
            if frame is self.botframe:
                break
            frame = frame.f_back

        return bp

    def clear_break(self, filename, lineno):
        bplist = self.get_breaks(filename, lineno)
        if not bplist:
            return 'There is no breakpoint at %s:%d' % (filename, lineno)
        for bp in bplist:
            bp.deleteMe()

    def clear_bpbynumber(self, arg):
        try:
            bp = self.get_bpbynumber(arg)
        except ValueError as err:
            return str(err)
        bp.deleteMe()

    def clear_all_breaks(self):
        if not self.has_breaks():
            return 'There are no breakpoints'
        for bp in Breakpoint.bpbynumber:
            if bp:
                bp.deleteMe()

    def get_bpbynumber(self, arg):
        if not arg:
            raise ValueError('Breakpoint number expected')
        try:
            number = int(arg)
        except ValueError:
            raise ValueError('Non-numeric breakpoint number %s' % arg)
        try:
            bp = Breakpoint.bpbynumber[number]
        except IndexError:
            raise ValueError('Breakpoint number %d out of range' % number)
        if bp is None:
            raise ValueError('Breakpoint %d already deleted' % number)
        return bp

    def get_breaks(self, filename, lineno):
        filename = canonic(filename)
        if filename in self.breakpoints:
            return self.breakpoints[filename].get_breakpoints(lineno)
        return []

    def get_file_breaks(self, filename):
        filename = canonic(filename)
        if filename not in self.breakpoints:
            return []
        return [bp.line for bp in self.breakpoints[filename].all_breakpoints()]

    def has_breaks(self):
        return any(self.breakpoints[f].breakpts.keys()
                        for f in self.breakpoints)

    # Derived classes and clients can call the following method
    # to get a data structure representing a stack trace.

    def get_stack(self, f, t):
        stack = []
        if t and t.tb_frame is f:
            t = t.tb_next
        while f is not None:
            stack.append((f, f.f_lineno))
            if f is self.botframe:
                break
            f = f.f_back
        stack.reverse()
        i = max(0, len(stack) - 1)
        while t is not None:
            stack.append((t.tb_frame, t.tb_lineno))
            t = t.tb_next
        if f is None:
            i = max(0, len(stack) - 1)
        return stack, i

    def format_stack_entry(self, frame_lineno, lprefix=': '):
        import reprlib
        frame, lineno = frame_lineno
        filename = canonic(frame.f_code.co_filename)
        s = '%s(%r)' % (filename, lineno)
        if frame.f_code.co_name:
            s += frame.f_code.co_name
        else:
            s += "<lambda>"
        if '__args__' in frame.f_locals:
            args = frame.f_locals['__args__']
        else:
            args = None
        if args:
            s += reprlib.repr(args)
        else:
            s += '()'
        if '__return__' in frame.f_locals:
            rv = frame.f_locals['__return__']
            s += '->'
            s += reprlib.repr(rv)
        line = linecache.getline(filename, lineno, frame.f_globals)
        if line:
            s += lprefix + line.strip()
        return s

    # The following methods can be called by clients to use
    # a debugger to debug a statement or an expression.
    # Both can be given as a string, or a code object.

    def run(self, cmd, globals=None, locals=None):
        if globals is None:
            import __main__
            globals = __main__.__dict__
        if locals is None:
            locals = globals
        self.reset()
        if isinstance(cmd, str):
            cmd = compile(cmd, "<string>", "exec")
        sys.settrace(self.trace_dispatch)
        try:
            exec(cmd, globals, locals)
        except BdbQuit:
            pass
        finally:
            self.quitting = True
            sys.settrace(None)

    def runeval(self, expr, globals=None, locals=None):
        if globals is None:
            import __main__
            globals = __main__.__dict__
        if locals is None:
            locals = globals
        self.reset()
        sys.settrace(self.trace_dispatch)
        try:
            return eval(expr, globals, locals)
        except BdbQuit:
            pass
        finally:
            self.quitting = True
            sys.settrace(None)

    def runctx(self, cmd, globals, locals):
        # B/W compatibility
        self.run(cmd, globals, locals)

    # This method is more useful to debug a single function call.

    def runcall(self, func, *args, **kwds):
        self.reset()
        sys.settrace(self.trace_dispatch)
        res = None
        try:
            res = func(*args, **kwds)
        except BdbQuit:
            pass
        finally:
            self.quitting = True
            sys.settrace(None)
        return res


def set_trace():
    Bdb().set_trace()


class Breakpoint:
    """Breakpoint class.

    Implements temporary breakpoints, ignore counts, disabling and
    (re)-enabling, and conditionals.

    Breakpoints are indexed by number through bpbynumber.

    """

    next = 1        # Next bp to be assigned
    bpbynumber = [None] # Each entry is None or an instance of Bpt

    def __init__(self, file, line, module, temporary=False,
                cond=None):
        self.file = file    # This better be in canonical form!
        self.line = line
        self.module = module
        self.actual_bp = module.add_breakpoint(self)
        self.temporary = temporary
        self.cond = cond
        self.enabled = True
        self.ignore = 0
        self.hits = 0
        self.number = Breakpoint.next
        Breakpoint.next += 1
        self.bpbynumber.append(self)

    def deleteMe(self):
        if self.bpbynumber[self.number]:
            self.bpbynumber[self.number] = None   # No longer in list
            self.module.delete_breakpoint(self)

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def process_hit_event(self, frame):
        """Return (stop_state, delete_temporary) at a breakpoint hit event."""
        if not self.enabled:
            return False, False
        # Count every hit when breakpoint is enabled.
        self.hits += 1
        # A conditional breakpoint.
        if self.cond:
            try:
                if not eval(self.cond, frame.f_globals, frame.f_locals):
                    return False, False
            except:
                # If the breakpoint condition evaluation fails, the most
                # conservative thing is to stop on the breakpoint.  Don't
                # delete temporary, as another hint to the user.
                return True, False
        if self.ignore > 0:
            self.ignore -= 1
            return False, False
        return True, True

    def bpprint(self, out=None):
        if out is None:
            out = sys.stdout
        print(self.bpformat(), file=out)

    def bpformat(self):
        if self.temporary:
            disp = 'del  '
        else:
            disp = 'keep '
        if self.enabled:
            disp = disp + 'yes  '
        else:
            disp = disp + 'no   '
        ret = '%-4dbreakpoint   %s at %s:%d' % (self.number, disp,
                                                self.file, self.line)
        if self.cond:
            ret += '\n\tstop only if %s' % (self.cond,)
        if self.ignore:
            ret += '\n\tignore next %d hits' % (self.ignore,)
        if self.hits:
            if self.hits > 1:
                ss = 's'
            else:
                ss = ''
            ret += '\n\tbreakpoint already hit %d time%s' % (self.hits, ss)
        return ret

    def __str__(self):
        return 'breakpoint %s at %s:%s' % (self.number, self.file, self.line)


# -------------------- testing --------------------

class Tdb(Bdb):
    def user_call(self, frame, args):
        name = frame.f_code.co_name
        if not name: name = '???'
        print('+++ call', name, args)
    def user_line(self, frame):
        name = frame.f_code.co_name
        if not name: name = '???'
        fn = canonic(frame.f_code.co_filename)
        line = linecache.getline(fn, frame.f_lineno, frame.f_globals)
        print('+++', fn, frame.f_lineno, name, ':', line.strip())
    def user_return(self, frame, retval):
        print('+++ return', retval)
    def user_exception(self, frame, exc_stuff):
        print('+++ exception', exc_stuff)
        self.set_continue()

def foo(n):
    print('foo(', n, ')')
    x = bar(n*10)
    print('bar returned', x)

def bar(a):
    print('bar(', a, ')')
    return a/2

def test():
    t = Tdb()
    t.run('from pdb_clone import bdb; bdb.foo(10)')
