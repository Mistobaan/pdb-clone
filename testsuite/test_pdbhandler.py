import sys
import os
import io
import signal
import unittest
import subprocess
from pdb_clone import attach as pdb_attach

class RemoteDebugging(unittest.TestCase):
    """Remote debugging support."""

    def setUp(self):
        self.address = pdb_attach.DFLT_ADDRESS
        self.signum = signal.SIGUSR1

    def proc_error(self, stderr):
        if stderr or self.proc.returncode:
            raise AssertionError("Process return code is %d, "
                    "stderr follows:\n%s" %
                    (self.proc.returncode, stderr.decode('ascii', 'ignore')))

    def attach(self, commands, attach_stdout):
        # Wait for pdbhandler to be imported and the signal handler
        # registered.
        self.proc.stdout.readline()
        os.kill(self.proc.pid, self.signum)
        try:
            pdb_attach.attach(self.address, io.StringIO('\n'.join(commands)),
                              attach_stdout, verbose=False)
        except (ConnectionRefusedError, SystemExit):
            self.proc.terminate()
            stdout, stderr = self.proc.communicate()
            if not self.proc_error(stderr):
                raise

    def run_pdb_remotely(self, source, commands, next_commands=None):
        """Run 'source' in a spawned process."""
        header = ("""if 1:
            from pdb_clone import pdbhandler
            pdbhandler.register(%d, '%s', %d)
            print('Registered.', flush=True)""" %
                (self.signum, self.address[0], self.address[1]))
        cmd_line = [sys.executable, '-c', header + '\n' + source]
        self.proc = subprocess.Popen(cmd_line, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        try:
            attach_stdout = io.StringIO()
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
                time.sleep(.020)
            """,
            [
                'i = 0',
                'detach',
            ]
        )
        self.assertIn(str(pdb_attach.DFLT_ADDRESS), stdout)

    def test_attach_twice(self):
        # Attach twice to the same process and check the release of the
        # resources.
        stdout = self.run_pdb_remotely("""if 1:
            import time
            i = 1
            second_session = 0
            while i:
                i += 1
                if second_session:
                    second_session = 0
                    print('Ready to be attached to.', flush=True)
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
        self.assertIn(str(pdb_attach.DFLT_ADDRESS), stdout)

    def test_get_handler(self):
        # Check pdbhandler.get_handler.
        stdout = self.run_pdb_remotely("""if 1:
            import time
            i = 1
            while i:
                time.sleep(.020)
            """,
            [
                'from pdb_clone import pdbhandler',
                'pdbhandler.get_handler()',
                'i = 0',
                'detach',
            ]
        )
        self.assertIn('Handler(signum=%d' % signal.SIGUSR1, stdout)

    def test_unregister(self):
        # Check pdbhandler.unregister.
        stdout = self.run_pdb_remotely("""if 1:
            import time
            i = 1
            while i:
                time.sleep(.020)
            """,
            [
                'from pdb_clone import pdbhandler',
                'pdbhandler.unregister()',
                'print(pdbhandler.get_handler())',
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
                time.sleep(.020)
            """,
            [
                'from pdb_clone import pdbhandler',
                'pdbhandler.get_handler()',
                'i = 0',
                'detach',
            ]
        )
        self.assertIn("Handler(signum=%d, host=b'localhost', port=6825)" %
            signal.SIGUSR2, stdout)

def test_main():
    support.run_unittest(PdbHandlerTestCase)

if __name__ == '__main__':
    test_main()
