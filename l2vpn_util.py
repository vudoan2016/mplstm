import time
import pexpect
import sys
import logging

def ypShell(ipAddr):
    connected = False
    logging.debug('Connecting to YP shell ...')
    s = pexpect.spawn("ssh diag@" + ipAddr + " -p 830")
    #s.logfile_read = sys.stdout
    try:
        s.expect ("password:", timeout=1)
        s.sendline("ciena123")
        try:
            s.expect(">", timeout=1)
            s.sendline("diag shell")
            try:
                s.expect("\$", timeout=1)
                s.sendline("yp-shell")
                try:
                    s.expect('>', timeout=2)
                    connected = True
                except:
                    print('Unable to bring up the yp-shell')
            except:
                print('Unable to enter diag mode')
        except:
            print('Password is not accepted')
    except:
        print('Unable to connect to the yp-shell')
    return (s, connected)
