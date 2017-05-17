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
    PVC_ATTACH_REQ = 3
    PVC_DETACH_REQ = 4

class PvcDB(threading.Thread):
    def __init__(self, name, cfgFile, telnetSession):
        threading.Thread.__init__(self)
        self.name = name
        self.setDaemon(1)
        self.cfgFile = cfgFile
        self.ts = telnetSession
        self.workRequestQ = Queue.Queue()
        self.cfg = [] # list of config params
        self.pvcDB = {} # dictionary of PVCs
        self._readCfg()

    def _readCfg(self):
        pvcCfgFile = open(self.cfgFile)
        csvReader = csv.reader(pvcCfgFile)
        next(csvReader, None)
        for row in csvReader:
            if row[3] == "dynamic":
                pvcType = "dynamic-vc "
            if row[5] == "static-associated":
                tnnlType = "tp-tunnel-assoc "
            elif row[5] == "dynamic-corout":
                tnnlType = "tp-tunnel-ingr-corout "
            self.cfg.append(tuple((row[0], row[1], int(row[2]), 
                                   pvcType, tnnlType, row[6], row[7])))
        pvcCfgFile.close()

    def _getExistingPVC(self):
        return self.ts.writeCmd("mpls l2-vpn show")

    def _create(self, resultQ):
        existingPVC = self._getExistingPVC()

        for cfg in self.cfg:
            if not len(cfg):
                continue
            for i in range(1, cfg[2]+1):
                pvcName = cfg[1] + str(i)
                if pvcName in self.pvcDB:
                    self.pvcDB[pvcName] = [i, cfg[6]+str(i)]
                    continue

                cmd = "mpls l2-vpn create " + cfg[3] + pvcName
                cmd += " pw-id " + str(i) + " peer " + cfg[0] + " "
                cmd += cfg[4] + cfg[5] + str(i) + " status-tlv on"
                result = self.ts.writeCmd(cmd)
                if "FAILURE" in result:
                    logging.debug(result)
                else:
                    self.pvcDB[pvcName] = [i, cfg[6]+str(i)]
        resultQ.put(globals.CfgResult.CFG_PVC_DONE)
        # attach pvc to virtual-switch
        self.workRequestQ.put((PVCWorkReq.PVC_ATTACH_REQ, None))

    def _delete(self):
        for pvc in self.pvcDB:
            cmd = "mpls l2-vpn delete vc " + pvc
            self.ts.writeCmd(cmd)
            self.pvcDB.pop(pvc)

        resultQ.put(globals.CfgResult.DELETE_PVC_DONE)

    def _attach(self):
        for pvc, attrs in self.pvcDB.items():
            cmd = "virtual-switch interface attach mpls-vc "
            cmd += pvc + " vs " + attrs[1]
            self.ts.writeCmd(cmd)
        logging.debug("Finish configuring device " + sys.argv[1])

    def _detach(self, resultQ):
        for pvc in self.pvcDB:
            cmd = "virtual-switch interface detach mpls-vc " + pvc
            self.ts.writeCmd(cmd)
        resultQ.put(globals.CfgResult.DETACH_PVC_DONE)

    def create(self, resultQ):
        self.workRequestQ.put((PVCWorkReq.PVC_CREATE_REQ, resultQ))

    def delete(self):
        self.workRequestQ.put((PVCWorkReq.PVC_DELETE_REQ, None))

    def attach(self):
        self.workRequestQ.put((PVCWorkReq.PVC_ATTACH_REQ, None))

    def detach(self, resultQ):
        self.workRequestQ.put((PVCWorkReq.PVC_DETACH_REQ, resultQ))

    def run(self):
        while 1:
            q, resultQ = self.workRequestQ.get()
            if q == PVCWorkReq.PVC_CREATE_REQ:
                self._create(resultQ)
            elif q == PVCWorkReq.PVC_DELETE_REQ:
                self._delete()
            if q == PVCWorkReq.PVC_ATTACH_REQ:
                self._attach()
            elif q == PVCWorkReq.PVC_DETACH_REQ:
                self._detach(resultQ)

