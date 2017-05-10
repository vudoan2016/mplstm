import sys
import threading
import logging
import csv
import Queue
import globals
from enum import Enum

class VirtualSwitchWorkReq(Enum):
    VS_CREATE_REQ   = 1
    VS_ATTACH_REQ   = 2
    VS_DETACH_REQ   = 3
    VS_DELETE_REQ   = 4

class vs(threading.Thread):
    def __init__(self, cfgFile, telnetSession):
        threading.Thread.__init__(self)
        self.setDaemon(1)
        self.vsCount = 0
        self.cfgFile = cfgFile
        self.ts = telnetSession
        self.workRequestQ = Queue.Queue()
        self._readCfg()

    def _readCfg(self):
        cfgFile = open(self.cfgFile)
        csvReader = csv.reader(cfgFile)
        next(csvReader, None)
        self.cfg = [tuple(row) for row in csvReader]
        cfgFile.close()
        
    def _createFromCfg(self, cfg):
        for i in range(1, int(cfg[2])+1):
            cmd = "virtual-switch create vs " + cfg[1] + str(i)
            result = self.ts.writeCmd(cmd)
            if "FAILURE" not in result and "ERROR" not in result:
                self.vsCount += 1

    def _create(self):
        for cfg in self.cfg:
            if len(cfg):
                self._createFromCfg(cfg)

    def create(self):
        self.workRequestQ.put(VirtualSwitchWorkReq.VS_CREATE_REQ)

    def _delete(self):
        for cfg in self.cfg:
            if not len(cfg):
                continue
            for i in range(1, self.vsCount+1):
                cmd = "virtual-switch delete vs " + cfg[1]
                self.ts.writeCmd(cmd)

    def delete(self):
        self.workRequestQ.put(VirtualSwitchWorkReq.VS_DELETE_REQ)

    def _attach(self):
        for cfg in self.cfg:
            if len(cfg):
                for i in range(1, int(cfg[2])+1):
                    cmd = "virtual-switch interface attach mpls-vc "
                    cmd += cfg[3] + str(i) + " vs " + cfg[1] + str(i)
                    self.ts.writeCmd(cmd)

    def attach(self):
        self.workRequestQ.put(VirtualSwitchWorkReq.VS_ATTACH_REQ)

    def _detach(self):
        for cfg in self.cfg:
            if not len(cfg):
                continue
            for i in range(1, self.vsCount+1):
                cmd = "virtual-switch interface detach mpls-vc " + cfg[3]
                self.ts.writeCmd(cmd)
        globals.pvcDB.delete()
        globals.vsDB.delete()

    def detach(self):
        self.workRequestQ.put(VirtualSwitchWorkReq.VS_DETACH_REQ)

    def run(self):
        while 1:
            q = self.workRequestQ.get()
            if q == VirtualSwitchWorkReq.VS_CREATE_REQ:
                self._create()
            elif q == VirtualSwitchWorkReq.VS_ATTACH_REQ:
                self._attach()
            elif q == VirtualSwitchWorkReq.VS_DETACH_REQ:
                self._detach()
            elif q == VirtualSwitchWorkReq.VS_DELETE_REQ:
                self._delete()
