"""Debugger basics"""

import fnmatch
import sys
import os
import linecache
import token
import tokenize
import itertools
import types
import tempfile
import shutil
from bisect import bisect
from operator import attrgetter

__all__ = ["BdbQuit", "Bdb", "Breakpoint"]

def case_sensitive_file_system():
    tmpdir = None
    f = None
    try:
        tmpdir = tempfile.mkdtemp()
        one = os.path.join(tmpdir, 'one')
        ONE = os.path.join(tmpdir, 'ONE')
        f = open(one, 'w')
        f.write('one')
        f.close()
        f = open(ONE, 'w')
        f.write('ONE')
        f.close()
        f = open(one)
        if f.read() == 'ONE':
            return False
    finally:
        if f:
            f.close()
        if tmpdir:
            shutil.rmtree(tmpdir)
    return True

# A dictionary mapping a filename to a BdbModule instance.
_modules = {}
_casesensitive_fs = case_sensitive_file_system()

def all_pathnames(abspath):
    yield abspath
    cwd = os.getcwd()
    if abspath.startswith(cwd):
        relpath = abspath[len(cwd):]
        if relpath.startswith(os.sep):
            relpath = relpath[len(os.sep):]
        if os.path.isfile(relpath):
            yield relpath
        relpath = os.path.join('.', relpath)
        if os.path.isfile(relpath):
            yield relpath

def canonic(filename):
    if filename[:1] + filename[-1:] == '<>':
        return filename
    pathname = os.path.normcase(os.path.abspath(filename))
    # On Mac OS X, normcase does not convert the path to lower case.
    if not _casesensitive_fs:
        pathname = pathname.lower()
    return pathname

def code_line_numbers(code):
    # Source code line numbers generator (see Objects/lnotab_notes.txt).
    valid_lno = lno = code.co_firstlineno
    yield valid_lno
    # The iterator yields (line_incr[i], byte_incr[i+1]) from lnotab.
    for line_incr, byte_incr in itertools.islice(zip(code.co_lnotab,
                    itertools.chain(code.co_lnotab[1:], ['1'])), 1, None, 2):
        lno += ord(line_incr)
        if ord(byte_incr) == 0:
            continue
        if lno != valid_lno:
            valid_lno = lno
            yield valid_lno

class BdbException(Exception):
    """A bdb exception."""

class BdbError(BdbException):
    """A bdb error."""

class BdbSourceError(BdbError):
    """An error related to the debuggee source code."""

class BdbSyntaxError(BdbError):
    """A syntax error in the debuggee source code."""

class BdbQuit(BdbException):
    """Exception to give up completely."""

class BdbModule:
    """A module.

    Instance attributes:
        functions_firstlno: a dictionary mapping function names and fully
        qualified method names to their first line number.
    """

    def __init__(self, filename):
        self.filename = filename
        self.linecache = None
        self.reset()

    def reset(self):
        if (self.filename not in linecache.cache or
                id(linecache.cache[self.filename]) != id(self.linecache)):
            self.functions_firstlno = None
            self.code = None
            self.source_lines = linecache.getlines(self.filename)
            if not self.source_lines:
                raise BdbSourceError('No lines in %s.' % self.filename)
            try:
                source = ''.join(self.source_lines)
                if not source.endswith('\n'):
                    source += '\n'
                self.code = compile(source, self.filename, 'exec')
            except (SyntaxError, TypeError), err:
                raise BdbSyntaxError('%s: %s.' % (self.filename, err))
            # At this point we still need to test for self.filename in
            # linecache.cache because of doctest scripts, as doctest installs a
            # hook at linecache.getlines to allow <doctest name> to be
            # linecache readable. But the condition is always true for real
            # filenames.
            if self.filename in linecache.cache:
                self.linecache = linecache.cache[self.filename]
            return True
        return False

    def get_func_lno(self, funcname):
        """The first line number of the last defined 'funcname' function."""
        if self.functions_firstlno is None:
            self.functions_firstlno = {}
            self.parse((tokenize.generate_tokens(
                                    iter(self.source_lines).next)))
        try:
            return self.functions_firstlno[funcname]
        except KeyError:
            raise BdbSourceError('%s: function "%s" not found.' % (
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

        if self.code:
            code_dist = _distance(self.code, module_level=True)
        if not self.code or not code_dist:
            raise BdbSourceError('%s: line %s is after the last '
                'valid statement.' % (self.filename, lineno))
        return code_dist[1]

    def parse(self, tok_generator, cindent=0, clss=None):
        func_lno = 0
        indent = 0
        previous = None
        try:
            while True:
                if previous:
                    tokentype, tok, srowcol = previous
                    previous = None
                else:
                    tokentype, tok, srowcol = tok_generator.next()[0:3]
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
                        return tokentype, tok, srowcol
                    tokentype, name = tok_generator.next()[0:2]
                    if tokentype != token.NAME:
                        continue  # syntax error
                    # Nested def or class in a function.
                    if func_lno:
                            continue
                    if clss:
                        name = '%s.%s' % (clss, name)
                    if tok == 'def':
                        lineno, indent = srowcol
                        func_lno = lineno
                        self.functions_firstlno[name] = lineno
                    else:
                        previous = self.parse(tok_generator, srowcol[1], name)
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

    def reset(self):
        try:
            do_reset = self.bdb_module.reset()
        except BdbSourceError:
            do_reset = True
        if do_reset:
            bplist = self.all_breakpoints()
            self.breakpts = {}
            for bp in bplist:
                try:
                    bp.actual_bp = self.add_breakpoint(bp)
                except BdbSourceError:
                    bp.deleteMe()

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
            # This may occur after a reset and the breakpoint could not be
            # added anymore.
            return
        if not bplist:
            del line_bps[actual_lno]
        if not line_bps:
            del self.breakpts[firstlineno]

    def get_breakpoints(self, lineno):
        """Return the list of breakpoints set at lineno."""
        try:
            firstlineno, actual_lno = self.bdb_module.get_actual_bp(lineno)
        except BdbSourceError:
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
        self.skip = None
        if skip:
            self.skip = set(skip)
        # A dictionary mapping a filename to a ModuleBreakpoints instance.
        self.breakpoints = {}
        self._reset()

    # Backward compatibility.
    def canonic(self, filename):
        return canonic(filename)

    def _reset(self, ignore_first_call_event=True, botframe=None):
        self.ignore_first_call_event = ignore_first_call_event
        self.botframe = botframe
        self.quitting = False
        self.topframe = None
        self.set_step()

    def restart(self):
        """Restart the debugger after source code changes."""
        linecache.checkcache()
        for module_bpts in self.breakpoints.values():
            module_bpts.reset()

    def trace_dispatch(self, frame, event, arg):
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
        print 'bdb.Bdb.dispatch: unknown debugging event:', repr(event)
        return self.trace_dispatch

    def dispatch_line(self, frame):
        if self.stop_here(frame):
            self._user_method(frame, 'line')
            return self._get_trace_function()
        else:
            breakpoint_hits = self.break_here(frame)
            if breakpoint_hits:
                self._user_method(frame, 'line', breakpoint_hits)
                return self._get_trace_function()
        return self.trace_dispatch

    def dispatch_call(self, frame, arg):
        # XXX 'arg' is no longer used.
        if self.ignore_first_call_event:
            self.ignore_first_call_event = False
            return self.trace_dispatch
        if not (self.stop_here(frame) or self.break_at_function(frame)):
            # No need to trace this function.
            return # None
        if self.stop_here(frame):
            self._user_method(frame, 'call', arg)
            return self._get_trace_function()
        return self.trace_dispatch

    def dispatch_return(self, frame, arg):
        if self.stop_here(frame) or frame is self.stopframe_lno[0]:
            self._user_method(frame, 'return', arg)
            if not self._get_trace_function():
                return None
            # Set the trace function in the caller when returning from the
            # current frame after step, next, until, return commands.
            if (frame is not self.botframe and
                    (self.stopframe_lno == (None, 0) or
                                    frame is self.stopframe_lno[0])):
                if frame.f_back and not frame.f_back.f_trace:
                    frame.f_back.f_trace = self.trace_dispatch
                self._set_stopinfo((None, 0))
        if frame is self.botframe:
            self._stop_tracing()
            return None
        return self.trace_dispatch

    def dispatch_exception(self, frame, arg):
        if self.stop_here(frame):
            self._user_method(frame, 'exception', arg)
            return self._get_trace_function()
        return self.trace_dispatch

    def get_locals(self, frame):
        # The f_locals dictionary of the top level frame is cached to avoid
        # being overwritten by invocation of its getter frame_getlocals (see
        # frameobject.c).
        if frame is self.topframe:
            if not self.topframe_locals:
                self.topframe_locals = self.topframe.f_locals
            return self.topframe_locals
        # Get the f_locals dictionary and thus explicitly overwrite the
        # previous changes made by the user to locals in this frame (see issue
        # 9633).
        return frame.f_locals

    def _user_method(self, frame, event, *args, **kwds):
        if not self.botframe:
            self.botframe = frame
        self.topframe = frame
        self.topframe_locals = None
        method = getattr(self, 'user_' + event)
        method(frame, *args, **kwds)
        self.topframe = None
        self.topframe_locals = None

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
        if _casesensitive_fs:
            filename = frame.f_code.co_filename
        else:
            filename = frame.f_code.co_filename.lower()
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
        if _casesensitive_fs:
            filename = frame.f_code.co_filename
        else:
            filename = frame.f_code.co_filename.lower()
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
        # [self.botframe, self.topframe] and that it gets a trace function.
        stopframe, lineno = stopframe_lno
        frame = self.topframe
        while stopframe and frame and frame is not stopframe:
            if frame is self.botframe:
                stopframe = self.botframe
                break
            frame = frame.f_back
        if stopframe and not stopframe.f_trace:
            stopframe.f_trace = self.trace_dispatch
        self.stopframe_lno = stopframe, lineno

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
        # First disable tracing temporarily as set_trace() may be called while
        # tracing is in use. For example when called from a signal handler and
        # within a debugging session started with runcall().
        sys.settrace(None)

        if not frame:
            frame = sys._getframe().f_back
        frame.f_trace = self.trace_dispatch

        # Do not change botframe when the debuggee has been started from an
        # instance of Pdb with one of the family of run methods.
        self._reset(ignore_first_call_event=False, botframe=self.botframe)
        while frame:
            if frame is self.botframe:
                break
            botframe = frame
            frame = frame.f_back
        else:
            self.botframe = botframe
            # Must trace the bottom frame to disable tracing on termination,
            # see issue 13044.
            self.botframe.f_trace = self.trace_dispatch
        sys.settrace(self.trace_dispatch)

    def _get_trace_function(self):
        # Do not raise BdbQuit when debugging is started with set_trace.
        if self.quitting and self.botframe.f_back:
            raise BdbQuit
        # Do not re-install the local trace when we are finished debugging, see
        # issues 16482 and 7238.
        if hasattr(sys, 'gettrace') and not sys.gettrace():
            return None
        return self.trace_dispatch

    def _stop_tracing(self):
        # Stop tracing, the thread trace function 'c_tracefunc' is NULL and
        # thus, call_trampoline() is not called anymore for all debug events:
        # PyTrace_CALL, PyTrace_RETURN, PyTrace_EXCEPTION and PyTrace_LINE.
        sys.settrace(None)

        # See PyFrame_GetLineNumber() in Objects/frameobject.c for why the
        # local trace functions must be deleted.
        frame = self.topframe
        while frame:
            del frame.f_trace
            if frame is self.botframe:
                break
            frame = frame.f_back

    def set_continue(self):
        # Don't stop except at breakpoints or when finished.
        self._set_stopinfo((None, -1))
        if not self.has_breaks():
            # No breakpoints; run without debugger overhead.
            self._stop_tracing()

    def set_quit(self):
        self.quitting = True
        self._stop_tracing()

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
            # self.breakpoints dictionary maps also the relative path names to
            # the common ModuleBreakpoints instance (co_filename may be a
            # relative path name).
            for pathname in all_pathnames(filename):
                self.breakpoints[pathname] = module_bps

        # Set the trace function when the breakpoint is set in one of the
        # frames of the frame stack.
        firstlineno, actual_lno = bp.actual_bp
        frame = self.topframe
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
        except ValueError, err:
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
        return bool([f for f in self.breakpoints
                        if self.breakpoints[f].breakpts.keys()])

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
        import repr
        frame, lineno = frame_lineno
        filename = canonic(frame.f_code.co_filename)
        s = '%s(%r)' % (filename, lineno)
        if frame.f_code.co_name:
            s += frame.f_code.co_name
        else:
            s += "<lambda>"
        locals = self.get_locals(frame)
        if '__args__' in locals:
            args = locals['__args__']
        else:
            args = None
        if args:
            s += repr.repr(args)
        else:
            s += '()'
        if '__return__' in locals:
            rv = locals['__return__']
            s += '->'
            s += repr.repr(rv)
        line = linecache.getline(filename, lineno)
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
        self._reset()
        if isinstance(cmd, str):
            if not cmd.endswith('\n'):
                cmd += '\n'
            cmd = compile(cmd, "<string>", "exec")
        sys.settrace(self.trace_dispatch)
        try:
            try:
                exec cmd in globals, locals
            except BdbQuit:
                pass
        finally:
            sys.settrace(None)

    def runeval(self, expr, globals=None, locals=None):
        if globals is None:
            import __main__
            globals = __main__.__dict__
        if locals is None:
            locals = globals
        self._reset()
        sys.settrace(self.trace_dispatch)
        try:
            try:
                return eval(expr, globals, locals)
            except BdbQuit:
                pass
        finally:
            sys.settrace(None)

    def runctx(self, cmd, globals, locals):
        # B/W compatibility
        self.run(cmd, globals, locals)

    # This method is more useful to debug a single function call.

    def runcall(self, func, *args, **kwds):
        self._reset(ignore_first_call_event=False)
        sys.settrace(self.trace_dispatch)
        res = None
        try:
            try:
                res = func(*args, **kwds)
            except BdbQuit:
                pass
        finally:
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
        print >> out, self.bpformat()

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
        print '+++ call', name, args
    def user_line(self, frame):
        name = frame.f_code.co_name
        if not name: name = '???'
        fn = canonic(frame.f_code.co_filename)
        line = linecache.getline(fn, frame.f_lineno)
        print '+++', fn, frame.f_lineno, name, ':', line.strip()
    def user_return(self, frame, retval):
        print '+++ return', retval
    def user_exception(self, frame, exc_stuff):
        print '+++ exception', exc_stuff
        self.set_continue()

def foo(n):
    print 'foo(', n, ')'
    x = bar(n*10)
    print 'bar returned', x

def bar(a):
    print 'bar(', a, ')'
    return a/2

def test():
    t = Tdb()
    t.run('from pdb_clone import bdb; bdb.foo(10)')
