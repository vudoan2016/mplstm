import sys
import threading
import csv
import Queue
import globals
from enum import Enum

class VirtualSwitchWorkReq(Enum):
    VS_CREATE_REQ   = 1
    VS_DELETE_REQ   = 2

class vs(threading.Thread):
    def __init__(self, name, cfgFile, telnetSession):
        threading.Thread.__init__(self)
        self.name = name
        self.setDaemon(1)
        self.cfgFile = cfgFile
        self.ts = telnetSession
        self.workRequestQ = Queue.Queue()
        self.vs = {} # dictionary of all virtual-switches
        self._readCfg()

    def _readCfg(self):
        cfgFile = open(self.cfgFile)
        csvReader = csv.reader(cfgFile)
        next(csvReader, None)
        self.cfg = [tuple(row) for row in csvReader]
        cfgFile.close()
        
    def _createFromCfg(self, cfg, existingVS):
        for i in range(1, int(cfg[2])+1):
            vs = cfg[1] + str(i)
            if vs in existingVS:
                self.vs[vs] = []
                continue
            cmd = "virtual-switch create vs " + vs
            result = self.ts.writeCmd(cmd)
            if "FAILURE" not in result and "ERROR" not in result:
                self.vs[vs] = []

    def _getExistingVS(self):
        return self.ts.writeCmd("virtual-switch show")

    def _create(self, resultQ):
        existingVS = self._getExistingVS()
        for cfg in self.cfg:
            if len(cfg):
                self._createFromCfg(cfg, existingVS)
        resultQ.put(globals.CfgResult.CFG_VS_DONE)
                
    def create(self, resultQ):
        self.workRequestQ.put((VirtualSwitchWorkReq.VS_CREATE_REQ, resultQ))

    def _delete(self):
        for vs in self.vs:
            cmd = "virtual-switch delete vs " + vs
            result = self.ts.writeCmd(cmd)
            self.vs.pop(vs)

    def delete(self):
        self.workRequestQ.put((VirtualSwitchWorkReq.VS_DELETE_REQ, None))

    def run(self):
        while 1:
            q, resultQ = self.workRequestQ.get()
            if q == VirtualSwitchWorkReq.VS_CREATE_REQ:
                self._create(resultQ)
            elif q == VirtualSwitchWorkReq.VS_DELETE_REQ:
                self._delete()
