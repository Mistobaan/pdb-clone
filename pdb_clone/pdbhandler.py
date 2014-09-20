"""The pdbhandler module."""

import sys
if sys.platform.startswith('win'):
    raise ImportError('The pdbhandler module is not supported on Windows.')

import signal
from pdb_clone import _pdbhandler
from pdb_clone.attach import DFLT_ADDRESS
from collections import namedtuple

Handler = namedtuple('Handler', 'signum, host, port')

def register(signum=signal.SIGUSR1,
             host=DFLT_ADDRESS[0], port=DFLT_ADDRESS[1]):
    """Register a pdb handler for signal 'signum'.

    The handler sets pdb to listen on the ('host', 'port') internet address
    and to start a remote debugging session on accepting a socket connection.
    """
    _pdbhandler._register(signum, host, port)

def unregister():
    """Unregister the pdb handler.

    Do nothing when no handler has been registered.
    """
    _pdbhandler._unregister()

def get_handler():
    """Return the handler as a named tuple.

    The named tuple attributes are 'signum', 'host', 'port'.
    Return None when no handler has been registered.
    """
    signum, host, port = _pdbhandler._registered()
    if signum:
        return Handler(signum, host if host else DFLT_ADDRESS[0],
                               port if port else DFLT_ADDRESS[1])

