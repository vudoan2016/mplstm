import pexpect
import logging
import threading

l = threading.Lock()

class TelnetSession:
    def __init__(self, ip, user, password):
        self.ip = ip
        self.user = user
        self.password = password
        self._login()

    def writeCmd(self, cmd):
        l.acquire()
        logging.debug(cmd)
        self.pe.sendline(cmd)
        self.pe.expect (">")
        l.release()
        return self.pe.before

    def connect(self):
        if self.pe.isalive():
            self.pe.close()
        self._login()

    def _login(self):
        self.pe = pexpect.spawn ("telnet " + self.ip)
        self.pe.expect("login:")
        self.pe.sendline (self.user)
        self.pe.expect ('Password:')
        self.pe.sendline (self.password)
        self.pe.expect (">")

