#!/usr/bin/env python

from __future__ import print_function

import os
import sys
from enum import Enum
from l2vpn_util import *

LOG_FILENAME = 'l2vpn.log'
logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG)

class FdMode(Enum):
   VPLS = 1
   VPWS = 2

class Chassis:
   def __init__(self, dut, peerIp=''):
      self.dut = dut.lower()
      self.peerIp = peerIp
      self.yp = ypShell(self.dut)
      self.imi = imiShell(self.dut)
      self.console = hostShell(self.dut)
      self.stateUp = False

   def isUp(self):
      return (self.stateUp)

   def __del__(self):
      self.yp.close()
      self.imi.close()
      self.console.close()

class TestL2vpn:
   def __init__(self, mode, dut, startId, count):
      self.dut = dut
      self.startId = startId
      self.count = count
      self.mode = mode

   def configFD(self):
      print('Configure FD ...')
      self.dut.yp.sendline("conf t")
      self.dut.yp.expect('#')
      if self.mode == FdMode.VPLS:
         mode = 'vpls'
      else:
         mode = 'vpws'
      cmd = "fds fd fd%d mode %s" % (self.startId, mode)
      logging.debug(cmd)
      self.dut.yp.sendline(cmd)
      self.dut.yp.expect("#")
      self.dut.yp.sendline("exit")
      self.dut.yp.expect(">")

   def unconfigFD(self):
      print('Unconfigure FD ...')
      self.dut.yp.sendline("conf t")
      self.dut.yp.expect("#")
      self.dut.yp.sendline("no fds fd fd%d" % self.startId)
      self.dut.yp.expect("#")
      self.dut.yp.sendline("exit")
      self.dut.yp.expect(">")

   def configPseudowire(self):
      print('Configure pseudowire ...')
      self.dut.yp.sendline("conf t")
      if self.mode == FdMode.VPWS:
         mode = 'mode spoke'
      else:
         mode = ''
      for i in range(self.startId, self.startId+self.count):
         cmd = "pseudowires pseudowire pw%d %s configured-pw peer-ip %s " \
               "pw-id %d" % (i, mode, self.dut.peerIp, i)
         self.dut.yp.sendline(cmd)
         logging.debug(cmd)
         self.dut.yp.expect("#")
      self.dut.yp.sendline("exit")
      self.dut.yp.expect(">")

   def unconfigPseudowire(self):
      print('Unconfigure pseudowire ...')
      self.dut.yp.sendline("conf t")
      self.dut.yp.expect("#")
      for i in range(self.startId, self.startId+self.count):
         self.dut.yp.sendline("no pseudowires pseudowire pw%d" % i)
         self.dut.yp.expect("#")
      self.dut.yp.sendline("exit")
      self.dut.yp.expect(">")

   def configL2vpnInstance(self):
      print('Configure l2vpn instance ...')
      self.dut.yp.sendline("conf t")
      self.dut.yp.expect("#")
      for i in range(self.startId, self.startId+self.count):
         cmd = "l2vpn-services l2vpn instance%d signaling-type ldp service-type vlan" \
               " mtu 1500 forwarding-domain fd%d pseudowire pw%d" % (i, self.startId, i)
         self.dut.yp.sendline(cmd)
         logging.debug(cmd)
         self.dut.yp.expect("#")
      self.dut.yp.sendline("exit")
      self.dut.yp.expect(">")

   def unconfigL2vpnInstance(self):
      print('Unconfigure l2vpn instance ...')
      self.dut.yp.sendline("conf t")
      self.dut.yp.expect("#")
      for i in range(self.startId, self.startId+self.count):
         self.dut.yp.sendline("no l2vpn-services l2vpn instance%d pseudowire pw%d" % (i, i))
         self.dut.yp.expect("#")
         self.dut.yp.sendline("no l2vpn-services l2vpn instance%d" % i)
         self.dut.yp.expect("#")
      self.dut.yp.sendline("exit")
      self.dut.yp.expect(">")

   def healthCheck(self):
      print('System health check ... ', end='')
      self.dut.console.sendline("ls -al /var/crash/")
      self.dut.console.expect("$")
      # Check for crash
      if self.dut.console.before.find("core") != -1:
         print("\nCore file detected:")
         for line in self.dut.console.before.splitlines():
            if line.find("core-") != -1:
               fields = line.split()
               print('\t\t' + fields[5] + '-' + fields[6] + ' ' + 
                     fields[7] + ' ' + fields[8])
      else:
         print('clean')
      # Check for memory usage
      # Check for CPU usage

   def cpL2vpnInstanceCheck(self, instanceId=0):
      '''
      VPLS Identifier: 1
      Peer IP: 18.5.5.5
      VC State: UP
      VC Type: vlan
      VC Label Sent: 24320
      VC Label Received: 24320
      Local PW Status Capability: enabled
      Remote PW Status Capability: disabled
      Current PW Status TLV: disabled
      '''
      if instanceId == 0:
         startId = 1
      else:
         startId = instanceId
      if self.mode == FdMode.VPLS:
         mode = 'vpls'
      else:
         mode = 'vpws'
      for i in range(startId, self.count+1):
         self.dut.imi.sendline("show ldp %s %d" % (mode, i))
         self.dut.imi.expect("\#")
         for line in self.dut.imi.before.splitlines():
            field = line.split(':')
            if field[0].find('VC State') != -1 and field[1].find('DOWN') != -1:
               print('Instance %d is down' % i)
               break
         if instanceId:
            break
   def dpL2vpnInstanceCheck(self, instanceId):
      '''
      +------------------------------- L3-Cache Mpls Pw-Group Entries [*=key field] -----------------------+
      |            |                                      |      |      |        | Is HAL   |  HwProt      |
      | Group-ID*  | FD UUID                              | Size | Type | Proto  | Create   |    ID        |
      +------------+--------------------------------------+------+------+--------+----------+--------------+
      | 1          | 00000000-0000-0000-0000-000000000000 | 1    | Dir  | LDP    | false    | X            |
      '''
      for line in self.dp.sendline("dpdDebug l3-cache show 15"):
         if line.startwith(str(instanceId)):
            pass

      '''
      +----------------------- L3-Cache Mpls Pw-List Entries [*=key field] ------------------------------------------------------------------------------+
      | Pw-Group-ID*| Pw-Name*                             | PathGroupId | Out-Label | In-label | pwMode |F2C policy |Cos | Color | Fec   |HwLif  | Is   |
      | F2C UUID                             | HwF2C ID | C2F UUID                             | HWC2F ID |Mac-learning | ViewTagName | Opaque-ID |      |
      +-------------+--------------------------------------+-------------+-----------+----------+--------+-----------+----+-------+-------+-------+------+
      | 1           | 8b1426b5-7087-5501-b56e-f5f53da95d07 | 0           | X        | X         | Hub    | X         | X  | X       | 0     | 47164 | true |
      | XXXXXXXX-XXXX-XXXX-XXXXXXXXXXXX      | X        | XXXXXXXX-XXXX-XXXX-XXXXXXXXXXXX      | X        | Disable     | (null)      | X         |
      '''
      for line in self.dp.sendline("dpdDebug l3-cache show 16"):
         pass

if __name__ == '__main__':
   l2vpnInstCount = 1
   startId = 100
   
   if sys.argv[1] == '-c' and len(sys.argv) >= 3:
      dut = Chassis(sys.argv[2], sys.argv[3])

      # VPLS creation 
      vpls = TestL2vpn(FdMode.VPLS, dut, startId, l2vpnInstCount)
      vpls.configFD()
      vpls.configPseudowire()
      vpls.configL2vpnInstance()

      # VPWS creation 
      startId = startId + l2vpnInstCount
      vpws = TestL2vpn(FdMode.VPWS, dut, startId, l2vpnInstCount)
      vpws.configFD()
      vpws.configPseudowire()
      vpws.configL2vpnInstance()

      # Verification
      vpls.cpL2vpnInstanceCheck()
      vpws.cpL2vpnInstanceCheck()
      vpws.healthCheck()
   elif sys.argv[1] == '-d' and len(sys.argv) >= 2:
      dut = Chassis(sys.argv[2])

      # VPLS deletion
      vpls = TestL2vpn(FdMode.VPLS, sys.argv[2], startId, l2vpnInstCount)
      vpls.unconfigL2vpnInstance()
      vpls.unconfigPseudowire()
      vpls.unconfigFD()

      # VPWS deletion
      startId = startId + l2vpnInstCount
      vpws = TestL2vpn(FdMode.VPWS, sys.argv[2], startId, l2vpnInstCount)
      vpws.unconfigL2vpnInstance()
      vpws.unconfigPseudowire()
      vpws.unconfigFD()
      vpws.healthCheck()

      # Verification
      vpls.cpL2vpnInstanceCheck()
      vpws.cpL2vpnInstanceCheck()
      vpls.healthCheck()
   else:
      print('Usage: l2vpn.py -c -d dev-ip peer-ip')

