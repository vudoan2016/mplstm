import time
import pexpect
import sys
import logging

def hostShell(ipAddr):
    s = pexpect.spawn("ssh diag@" + ipAddr)
    #s.logfile_read = sys.stdout
    try:
        s.expect("\$", timeout=1)
    except:
        try:
            s.expect("password:", timeout=1)
            s.sendline("diag")
            s.expect("\$", timeout=1)
        except:
            print('Unable to log in to %s' % ipAddr)
    return s

def imiShell(ipAddr):
    logging.debug('Connecting to IMI shell ...')
    s = hostShell(ipAddr)
    s.sendline("docker exec -it cn_ipservices_1 bash")
    s.sendline()
    s.expect("#", timeout=1)
    s.sendline("imish")
    s.expect(">", timeout=1)
    s.sendline("ena")
    s.expect("#", timeout=1)
    return s

def ypShell(ipAddr):
    logging.debug('Connecting to YP shell ...')
    s = pexpect.spawn("ssh diag@" + ipAddr + " -p 830")
    #s.logfile_read = sys.stdout
    s.expect ("password:", timeout=1)
    s.sendline("ciena123")
    s.expect(">", timeout=1)
    s.sendline("diag shell")
    s.expect("\$", timeout=1)
    s.sendline("yp-shell")
    s.expect('>', timeout=1)
    return s
