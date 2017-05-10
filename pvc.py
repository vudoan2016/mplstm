import sys
import threading
import logging
import time
import csv
import Queue
import globals
from enum import Enum

class PVCWorkReq(Enum):
    PVC_CREATE_REQ = 1
    PVC_DELETE_REQ = 2

class PvcDB(threading.Thread):
    def __init__(self, cfgFile, telnetSession):
        threading.Thread.__init__(self)
        self.setDaemon(1)
        self.cfgFile = cfgFile
        self.telnetSession = telnetSession
        self.workRequestQ = Queue.Queue()
        self._readCfg()

    def _readCfg(self):
        pvcCfgFile = open(self.cfgFile)
        csvReader = csv.reader(pvcCfgFile)
        next(csvReader, None)
        self.cfg = [tuple(row) for row in csvReader]
        pvcCfgFile.close()

    def _create(self):
        self.pvcCount = 0
        for cfg in self.cfg:
            if not len(cfg):
                continue
            for i in range(1, int(cfg[2])+1):
                if cfg[3] == "dynamic":
                    pvcType = "dynamic-vc "
                if cfg[5] == "static-associated":
                    tnnlType = "tp-tunnel-assoc "
                elif cfg[5] == "dynamic-corout":
                    tnnlType = "tp-tunnel-ingr-corout "
                cmd = "mpls l2-vpn create " + pvcType + " " + cfg[1] + str(i) 
                cmd += " pw-id " + str(i) + " peer " + cfg[0] + " "
                cmd += tnnlType + cfg[6] + str(i) + " status-tlv on"
                result = self.telnetSession.writeCmd(cmd)
                if "FAILURE" in result:
                    print(result)
                else:
                    self.pvcCount += 1
        globals.vsDB.create()
        globals.vsDB.attach()

    def create(self):
        self.workRequestQ.put(PVCWorkReq.PVC_CREATE_REQ)

    def _delete(self):
        for cfg in self.cfg:
            if not len(cfg):
                continue
            cmd = "mpls l2-vpn delete vc " + cfg[1]
            self.telnetSession.writeCmd(cmd)
        globals.iTnnlDB.delete()

    def delete(self):
        self.workRequestQ.put(PVCWorkReq.PVC_DELETE_REQ)

    def run(self):
        while 1:
            q = self.workRequestQ.get()
            if q == PVCWorkReq.PVC_CREATE_REQ:
                self._create()
            elif q == PVCWorkReq.PVC_DELETE_REQ:
                self._delete()

