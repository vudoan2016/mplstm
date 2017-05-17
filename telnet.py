import pexpect
import telnetlib
import globals
import logging
import threading
import re

l = threading.Lock()
logging.basicConfig(filename='ingress.log', level=logging.DEBUG, 
                    format='%(asctime)s,%(threadName)-10s: %(message)s')
logger = logging.getLogger(__name__)
handler = logging.FileHandler('ingress.log')
logger.addHandler(handler)

class TelnetSession:
    def __init__(self, ip, user, password):
        self.ip = ip
        self.user = user
        self.password = password
        self._login()
        self._getHostName()

    def writeCmd(self, cmd):
        l.acquire()
        self.pe.sendline(cmd)
        try:
            self.pe.expect (self.prompt)
        except:
            logging.debug("Exception: cmd:" + cmd)
            logging.debug(str(self.pe))
        result = self.pe.before
        l.release()
        logging.debug(result)
        return result

    def connect(self):
        if self.pe.isalive():
            self.pe.close()
        self._login()
        self._getHostName()

    def _login(self):
        self.pe = pexpect.spawn ("telnet " + self.ip)
        self.pe.expect('login:')
        self.pe.sendline (self.user)
        self.pe.expect ('Password:')
        self.pe.sendline (self.password)
        self.pe.expect ('> ')

    def _getHostName(self):
        self.pe.sendline ("system show host-name")
        self.pe.expect ('> ')
        try:
            searchObj = re.search(r'(User) \| (\w+)', self.pe.before)
        except:
            self.prompt = '> '
        finally:
            self.prompt = searchObj.group(2)
