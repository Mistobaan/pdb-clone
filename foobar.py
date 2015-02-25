# Attach with gdb as root:
# pid=$(ps -ef | grep python | grep foobar | awk '{print $2}')
# $py ~/.local/bin/pdb-attach -p $pid

import time
def foo():
    x = 0
    while 1:
        # Attach with a signal, uncomment the following line and run:
        # $py ~/.local/bin/pdb-attach -k -p $pid
        #from pdb_clone import pdbhandler; pdbhandler.register()
        time.sleep(.1)
        x += 1

foo()
fin = True

