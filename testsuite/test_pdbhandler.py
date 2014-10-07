import sys
import os
import StringIO
import signal
import unittest
import subprocess
import errno
from test.test_support import strip_python_stderr
from pdb_clone import DFLT_ADDRESS
from pdb_clone import attach as pdb_attach

class RemoteDebugging(unittest.TestCase):
    """Remote debugging support."""

    def setUp(self):
        self.address = DFLT_ADDRESS
        self.signum = signal.SIGUSR1

    def proc_error(self, stderr):
        stderr =  strip_python_stderr(stderr)
        if stderr or self.proc.returncode:
            raise AssertionError("Process return code is %d, "
                    "stderr follows:\n%s" %
                    (self.proc.returncode, stderr.decode('ascii', 'ignore')))

    def attach(self, commands, attach_stdout):
        # Wait for pdbhandler to be imported, the signal handler
        # registered and the main loop started.
        self.proc.stdout.readline()
        os.kill(self.proc.pid, self.signum)
        try:
            pdb_attach.attach(self.address,
                              StringIO.StringIO('\n'.join(commands)),
                              attach_stdout, verbose=False)
        except (IOError, SystemExit), err:
            if isinstance(err, IOError) and err.errno != errno.ECONNREFUSED:
                raise
            self.proc.terminate()
            stdout, stderr = self.proc.communicate()
            if not self.proc_error(stderr):
                raise

    def run_pdb_remotely(self, source, commands, next_commands=None):
        """Run 'source' in a spawned process."""
        header = ("""if 1:
            import sys
            from pdb_clone import pdbhandler
            pdbhandler.register('%s', %d, %d)
            started = False""" %
                (self.address[0], self.address[1], self.signum))
        cmd_line = [sys.executable, '-c', header + '\n' + source]
        self.proc = subprocess.Popen(cmd_line, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        try:
            attach_stdout = StringIO.StringIO()
            self.attach(commands, attach_stdout)
            if next_commands:
                self.attach(next_commands, attach_stdout)
            stdout, stderr = self.proc.communicate()
        finally:
            self.proc.stdout.close()
            self.proc.stderr.close()
        self.proc_error(stderr)
        return attach_stdout.getvalue()

@unittest.skipIf(sys.platform.startswith("win"), 'not supported on Windows')
class PdbHandlerTestCase(RemoteDebugging):
    """Remote debugging test cases."""
    def test_register(self):
        # Check pdbhandler.register.
        stdout = self.run_pdb_remotely("""if 1:
            import time
            i = 1
            while i:
                if not started:
                    print 'started.'
                    sys.stdout.flush()
                    started = True
                time.sleep(.020)
            """,
            [
                'i = 0',
                'detach',
            ]
        )
        self.assertIn(str(DFLT_ADDRESS), stdout)

    def test_attach_twice(self):
        # Attach twice to the same process and check the release of the
        # resources.
        stdout = self.run_pdb_remotely("""if 1:
            import time
            i = 1
            second_session = 0
            while i:
                if not started:
                    print 'started.'
                    sys.stdout.flush()
                    started = True
                i += 1
                if second_session:
                    second_session = 0
                    print 'Ready to be attached to.'
                    sys.stdout.flush()
                time.sleep(.020)
            """,
            [
                'second_session = 1',
                'detach',
            ],
            [
                'i = 0',
                'detach',
            ]
        )
        self.assertIn(str(DFLT_ADDRESS), stdout)

    def test_get_handler(self):
        # Check pdbhandler.get_handler.
        stdout = self.run_pdb_remotely("""if 1:
            import time
            i = 1
            while i:
                if not started:
                    print 'started.'
                    sys.stdout.flush()
                    started = True
                time.sleep(.020)
            """,
            [
                'from pdb_clone import pdbhandler',
                'pdbhandler.get_handler()',
                'i = 0',
                'detach',
            ]
        )
        self.assertIn("Handler(host='127.0.0.1', port=7935, signum=%d)" %
                      signal.SIGUSR1, stdout)

    def test_unregister(self):
        # Check pdbhandler.unregister.
        stdout = self.run_pdb_remotely("""if 1:
            import time
            i = 1
            while i:
                if not started:
                    print 'started.'
                    sys.stdout.flush()
                    started = True
                time.sleep(.020)
            """,
            [
                'from pdb_clone import pdbhandler',
                'pdbhandler.unregister()',
                'print pdbhandler.get_handler()',
                'i = 0',
                'detach',
            ]
        )
        self.assertIn('None', stdout)

    def test_register_non_default(self):
        # Check pdbhandler.register non default arguments.
        self.signum = signal.SIGUSR2
        self.address = ('localhost', 6825)
        stdout = self.run_pdb_remotely("""if 1:
            import time
            i = 1
            while i:
                if not started:
                    print 'started.'
                    sys.stdout.flush()
                    started = True
                time.sleep(.020)
            """,
            [
                'from pdb_clone import pdbhandler',
                'pdbhandler.get_handler()',
                'i = 0',
                'detach',
            ]
        )
        self.assertIn("Handler(host='localhost', port=6825, signum=%d)" %
            signal.SIGUSR2, stdout)

if __name__ == '__main__':
    unittest.main()
