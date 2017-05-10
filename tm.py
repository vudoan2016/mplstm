import sys
import traceback
import logging
import telnet
import globals

# Usage: python tunnel.py 10.33.10.142
if __name__ == "__main__":
    egressSession = None

    logging.basicConfig(level=logging.DEBUG, format='%(threadName)-10s: %(message)s')
    globals.iTnnlDB.start()
    globals.pvcDB.start()
    globals.vsDB.start()

    if len(sys.argv) > 2:
        eSession = telnet.TelnetSession(sys.argv[2], user, password)
        eTnnlDB = tunnel.TnnlDB(egressTnnlCfgFile, eSession)
        eTnnlDB.start()
    else:
        eTnnlDB = None

    while 1:
        ans = raw_input("1-create, 2-test, 3-delete, 4-report, 5-exit: ")
        if ans == "1":
            if eTnnlDB:
                eTnnlDB.create()
            globals.iTnnlDB.create()
        elif ans == "2":
            while True:
                ans = raw_input("1-HA, 2-exit: ")
                if ans == "1":
                    globals.iTnnlDB.HA()
                else:
                    break
        elif ans == "3":
            globals.vsDB.detach()
        elif ans == "4":
            globals.iTnnlDB.report()
        elif ans == "5":
            sys.exit()
        
    globals.iTnnlDB.join()
    globals.pvcDB.join()
    globals.vsDB.join()
    if eTnnlDB:
        eTnnlDB.join()
