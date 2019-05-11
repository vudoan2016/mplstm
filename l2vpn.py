#!/usr/bin/env python

from __future__ import print_function

import os
import sys
import pxssh
import threading
import time
import json
from enum import Enum
from l2vpn_util import *

LOG_FILENAME = 'l2vpn.log'
logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG)

credential = ('diag', 'diag')

class FdMode(Enum):
   VPLS = 1
   VPWS = 2

class Chassis:
   def __init__(self, dut, peerIp=''):
      self.dut = dut.lower()
      self.peerIp = peerIp
      res = ypShell(self.dut)
      self.ypShellConnected = res[1]
      self.yp = res[0]
      self.ypPrompt = '[#>]'
      self.imiConnected = res[1]
      self.imiPrompt = '[#>]'

   def ypShellConnected(self):
      return self.ypShellConnected

   def imiConnected(self):
      return self.imiConnected

   def healthCheck(self):
      print('System health check ... ', end='')
      cmd = 'ls -al /var/crash/'
      host = pxssh.pxssh()
      host.login(self.dut, credential[0], credential[1])
      host.sendline(cmd)
      host.prompt()
      
      # Check for crash
      clean = True
      output = ''
      for line in host.before.splitlines():
         if line.find("core-") != -1:
            clean = False
            fields = line.split()
            output = (output + fields[5] + '-' + fields[6] + ' ' + 
                      fields[7] + ' ' + fields[8] + '\n')
      if clean:
         print('clean')
      else:
         print("Core file detected:")
         print(output)
         
      # Check for memory usage
      # Check for CPU usage
      host.logout
      return clean

   def __del__(self):
      self.yp.close()
      #self.imi.close()

class L2vpnAgent:
   def __init__(self, modeAttrs, dut, startId, count):
      self.dut = dut
      self.startId = startId
      self.count = count
      self.modeAttrs = modeAttrs
      if modeAttrs[0] == FdMode.VPWS:
         self.pwMode = 'spoke'
      else:
         self.pwMode = 'mesh'
      self.pwPrefix = 'pw'

   def config(self, cmd):
      logging.debug(cmd)
      self.dut.yp.sendline(cmd)
      self.dut.yp.expect(self.dut.ypPrompt)
      return self.dut.yp.before 

   def queryIMI(self, cmd):
      logging.debug(cmd)
      imish = pxssh.pxssh(timeout=1)
      imish.logfile_read = sys.stdout
      imish.login(self.dut.dut, credential[0], credential[1])
      imish.prompt()
      imish.sendline('docker exec -it cn_ipservices_1 bash')
      imish.prompt()
      imish.sendline('imish')
      imish.prompt()
      imish.sendline('enable')
      imish.prompt()
      imish.sendline('terminal length 0')
      imish.prompt()
      imish.sendline(cmd)
      imish.prompt()
      result = imish.before
      imish.logout()
      return result

   def queryDp(self, cmd):
      logging.debug(cmd)
      dp = pxssh.pxssh()
      dp.login(self.dut.dut, credential[0], credential[1])
      dp.sendline('docker exec -it cn_dataplane_1 %s' % cmd)
      dp.prompt()
      result = dp.before
      dp.logout()
      return result

   def configFD(self):
      print('Configure FD ...')
      self.config('config t')
      cmd = "fds fd fd%d mode %s" % (self.startId, self.modeAttrs[1])
      self.config(cmd)
      self.config('exit')

   def unconfigFD(self):
      print('Unconfigure FD ...')
      self.config('config t')
      self.config('no fds fd fd%d' % self.startId)
      self.config('exit')

   def configPseudowire(self, pwId=0):
      print('Configure pseudowire ...')
      self.config('config t')
      if pwId:
         start = pwId
         end = start+1
      else:
         start = self.startId
         end = start + self.count
      for i in range(start, end):
         self.pw = {i : self.pwPrefix+str(i)}
         cmd = "pseudowires pseudowire %s%d %s configured-pw peer-ip %s " \
               "pw-id %d" % (self.pwPrefix, i, 'mode ' + self.pwMode, self.dut.peerIp, i)
         self.config(cmd)
      self.config('exit')

   def unconfigPseudowire(self, pwId=0):
      print('Unconfigure pseudowire ...')
      self.config('conf t')
      if pwId:
         start = pwId
         end = start+1
      else:
         start = self.startId
         end = start + self.count
      for i in range(start, end):
         self.config("no pseudowires pseudowire pw%d" % i)
      self.config('exit')

   def configL2vpnInstance(self):
      print('Configure l2vpn instance ...')
      self.config("conf t")
      for i in range(self.startId, self.startId+self.count):
         self.instances = {i : ['down']}
         cmd = ("l2vpn-services l2vpn instance%d signaling-type ldp " \
                "service-type %s mtu 1500 forwarding-domain fd%d pseudowire pw%d" % 
                (i, self.modeAttrs[2], self.startId, i))
         self.config(cmd)
      self.config('exit')

   def unconfigL2vpnInstance(self):
      print('Unconfigure l2vpn instance ...')
      self.config("conf t")
      for i in range(self.startId, self.startId+self.count):
         self.config("no l2vpn-services l2vpn instance%d pseudowire pw%d" % (i, i))
         self.config("no l2vpn-services l2vpn instance%d" % i)
      self.config("exit")

   def pseudowireCheck(self, op, pwId=0):
      if pwId:
         start = pwId
         end = start+1
      else:
         start = self.startId
         end = start + self.count

      res = self.queryIMI('show mpls l2-circuit')
      for i in range(start, end):
         if op == '-c' and not res.find(self.pwPrefix+str(i)) != -1:
            print('Pseudowire %s%d is missing' % (self.pwPrefix, i))
         elif op == '-d' and res.find(self.pwPrefix+str(i)) != -1:
            print('Pseudowire %s%d is not deleted' % (self.pwPrefix, i))

   def parseVPLSOutput(self, op, instance, output):
      state = ''
      passed = False
      if op == '-d':
         if str(instance) not in output:
            passed = True
      else:
         for line in output:
            field = line.split()
            if (len(field) > 2 and field[0] == str(instance) and 
                field[2].lower == 'up'):
               passed = True
               state = field[2]
               break
      return (passed, state)

   def parseVPWSOutput(self, op, instance, output):
      passed = False
      state = ''
      if op == '-d':
         if str(instance) not in output:
            passed = True
      else:
         for line in output:
            field = line.split()
            if len(field) > 2 and field[0] == str(instance) and field[2].lower() == 'up':
               passed = True
               state = field[2]
               break
      return (passed, state)

   def cpL2vpnInstanceCheck(self, op, instanceId=0):
      if instanceId == 0:
         startId = self.startId
      else:
         startId = instanceId

      res = self.config("sget /pseudowires-state")
      
      res = res[res.index('{'):]
      start = res.index('[')
      stop = res.index(']')
      print(res[start:stop+1])
      print(json.loads(res[start:stop+1]))

      '''
      for i in range(startId, startId+2):
         print(states.yuma-netconf.yuma-netconf.ciena-pseudowires.pseudowire[i])
      '''
      time.sleep(1)

      '''
      while True:
         self.config('sget /pseudowire')
         res = self.queryIMI("show ldp %s" % option)
         for i in range(startId, startId+self.count):
            if self.modeAttrs[0] == FdMode.VPWS:
               result = self.parseVPWSOutput(op, i, res.splitlines())
            else:
               result = self.parseVPLSOutput(op, i, res.splitlines())
               
            if not result[0] and op == '-v':
               print('\tInstance %d is down' % i)
            elif not result[0] and op == '-d':
               print('\tInstance %d is stale' % i)
            self.instances[i] = [result[1]]

            if instanceId:
               break
         time.sleep(1)
      '''
   def dpL2vpnInstanceCheck(self, op, instanceId=0):
      if instanceId == 0:
         startId = self.startId
      else:
         startId = instanceId

      res = self.queryDp("dpdDebug l3-cache show 15")
      for i in range(startId, startId+self.count):
         if res.find(str(i)) == -1:
            print('\tInstance %d is not downloaded to DP' % i)
         if instanceId:
            break

if __name__ == '__main__':
   l2vpnInstCount = 100 
   startId = 101
   
   if len(sys.argv) > 3 and sys.argv[1] == '-c':
      dut = Chassis(sys.argv[2], sys.argv[3])

      # Tagged VPLS creation 
      taggedVpls = L2vpnAgent((FdMode.VPLS, 'vpls', 'vlan'), dut, startId, 
                              l2vpnInstCount)
      taggedVpls.configFD()
      taggedVpls.configPseudowire()
      taggedVpls.configL2vpnInstance()
      taggedVpls.dpL2vpnInstanceCheck(sys.argv[1])
      dut.healthCheck()

      # Ethernet VPLS creation 
      startId = startId + l2vpnInstCount
      ethernetVpls = L2vpnAgent((FdMode.VPLS, 'vpls', 'ethernet'), dut, startId, 
                                l2vpnInstCount)
      ethernetVpls.configFD()
      ethernetVpls.configPseudowire()
      ethernetVpls.configL2vpnInstance()
      ethernetVpls.dpL2vpnInstanceCheck(sys.argv[1])
      dut.healthCheck()

      # Tagged VPWS creation 
      startId = startId + l2vpnInstCount
      taggedVpws = L2vpnAgent((FdMode.VPWS, 'vpws', 'vlan'), dut, startId, 
                              l2vpnInstCount)
      taggedVpws.configFD()
      taggedVpws.configPseudowire()
      taggedVpws.configL2vpnInstance()
      # taggedVpws.pseudowireCheck(sys.argv[1])
      taggedVpws.dpL2vpnInstanceCheck(sys.argv[1])
      dut.healthCheck()

      # Ethernet VPWS creation 
      startId = startId + l2vpnInstCount
      ethernetVpws = L2vpnAgent((FdMode.VPWS, 'vpws', 'ethernet'), dut, startId, 
                                l2vpnInstCount)
      ethernetVpws.configFD()
      ethernetVpws.configPseudowire()
      ethernetVpws.configL2vpnInstance()
      # ethernetVpws.pseudowireCheck(sys.argv[1])
      ethernetVpws.dpL2vpnInstanceCheck(sys.argv[1])
      dut.healthCheck()

   elif len(sys.argv) >  2 and sys.argv[1] == '-d':
      dut = Chassis(sys.argv[2])

      # Tagged VPLS deletion
      taggedVpls = L2vpnAgent((FdMode.VPLS, 'vpls', 'vlan'), dut, startId, 
                        l2vpnInstCount)
      taggedVpls.unconfigL2vpnInstance()

      taggedVpls.unconfigPseudowire()
      taggedVpls.unconfigFD()
      dut.healthCheck()

      # Ethernet VPLS deletion
      startId = startId + l2vpnInstCount
      ethernetVpls = L2vpnAgent((FdMode.VPLS, 'vpls', 'vlan'), dut, startId, 
                        l2vpnInstCount)
      ethernetVpls.unconfigL2vpnInstance()
      ethernetVpls.unconfigPseudowire()
      ethernetVpls.unconfigFD()
      dut.healthCheck()

      # Tagged VPWS deletion
      startId = startId + l2vpnInstCount
      taggedVpws = L2vpnAgent((FdMode.VPWS, 'vpws', 'vlan'), dut, startId, l2vpnInstCount)
      taggedVpws.unconfigL2vpnInstance()
      taggedVpws.unconfigPseudowire()
      taggedVpws.unconfigFD()
      dut.healthCheck()

      # Ethernet VPWS deletion
      startId = startId + l2vpnInstCount
      ethernetVpws = L2vpnAgent((FdMode.VPWS, 'vpws', 'vlan'), dut, startId, l2vpnInstCount)
      ethernetVpws.unconfigL2vpnInstance()
      ethernetVpws.unconfigPseudowire()
      ethernetVpws.unconfigFD()
      dut.healthCheck()

   elif len(sys.argv) > 2 and sys.argv[1] == '-v':
      dut = Chassis(sys.argv[2])

      taggedVpls = L2vpnAgent((FdMode.VPLS, 'vpls', 'vlan'), dut, startId, 
                              l2vpnInstCount)
      startId = startId + l2vpnInstCount
      ethernetVpls = L2vpnAgent((FdMode.VPLS, 'vpls', 'ethernet'), dut, startId, 
                                l2vpnInstCount)
      startId = startId + l2vpnInstCount
      taggedVpws = L2vpnAgent((FdMode.VPWS, 'vpws', 'vlan'), dut, startId, 
                              l2vpnInstCount)
      '''
      startId = startId + l2vpnInstCount
      ethernetVpws = L2vpnAgent((FdMode.VPWS, 'vpws', 'ethernet'), dut, startId, 
                                l2vpnInstCount)
      taggedVplsThread = threading.Thread(target=taggedVpls.cpL2vpnInstanceCheck, 
                                          args=(sys.argv[1],))
      taggedVplsThread.daemon = True
      taggedVplsThread.start()

      ethernetVplsThread = threading.Thread(target=ethernetVpls.cpL2vpnInstanceCheck, 
                                            args=(sys.argv[1],))
      ethernetVplsThread.daemon = True
      ethernetVplsThread.start()
      '''
      taggedVpwsThrd = threading.Thread(target=taggedVpws.cpL2vpnInstanceCheck, 
                                        args=(sys.argv[1],))
      taggedVpwsThrd.daemon = True
      taggedVpwsThrd.start()
      '''
      ethernetVpwsThrd = threading.Thread(target=ethernetVpws.cpL2vpnInstanceCheck,
                                          args=(sys.argv[1],))
      ethernetVpwsThrd.daemon = True
      ethernetVpwsThrd.start()
      '''
      taggedVpwsThrd.join()
      '''
      taggedVplsThread.join()
      ethernetVplsThread.join()
      ethernetVpwsThrd.join()
      '''
      dut.yp.close()
   else:
      print('Usage: l2vpn.py -c dev-ip peer-ip')
      print('                -d dev-ip')
      print('                -v dev-ip')
