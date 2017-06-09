import sys
import threading
import time
import csv
import Queue
import globals
import logging
import re
import time
from enum import Enum

class PVCWorkReq(Enum):
    PVC_CREATE_REQ     = 1
    PVC_DELETE_REQ     = 2
    PVC_ATTACH_REQ     = 3
    PVC_DETACH_REQ     = 4
    PVC_UPD_LBL_REQ    = 5
    PVC_VERIFY_PNG_REQ = 6
    PVC_CREATE_REPORT  = 7

PW_MAX_ID = 0x7FFFFFF
PW_MAX_RETRIES = 60

class Pvc:
    def __init__(self, pwid, pingStatus):
        self.pwid = pwid
        self.inLbl = -1
        self.outLbl = -1
        self.pingStatus = pingStatus

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

    def create(self, resultQ, chassis):
        self.workRequestQ.put((PVCWorkReq.PVC_CREATE_REQ, resultQ, None, chassis))

    def delete(self, resultQ):
        self.workRequestQ.put((PVCWorkReq.PVC_DELETE_REQ, resultQ, None, None))

    def attach(self, chassis):
        self.workRequestQ.put((PVCWorkReq.PVC_ATTACH_REQ, None, None, chassis))

    def detach(self, resultQ):
        self.workRequestQ.put((PVCWorkReq.PVC_DETACH_REQ, resultQ, None, None))

    def updateLabel(self, resultQ):
        self.workRequestQ.put((PVCWorkReq.PVC_UPD_LBL_REQ, resultQ, None, None))
        
    def verifyPing(self, resultQ=None):
        self.workRequestQ.put((PVCWorkReq.PVC_VERIFY_PNG_REQ, resultQ, None, None))

    def report(self, reportFile):
        self.workRequestQ.put((PVCWorkReq.PVC_CREATE_REPORT, None, reportFile, None))

    def run(self):
        while 1:
            q, resultQ, reportFile, chassis = self.workRequestQ.get()
            if q == PVCWorkReq.PVC_CREATE_REQ:
                self._create(resultQ)
            elif q == PVCWorkReq.PVC_DELETE_REQ:
                self._delete(resultQ)
            if q == PVCWorkReq.PVC_ATTACH_REQ:
                self._attach(chassis)
            elif q == PVCWorkReq.PVC_DETACH_REQ:
                self._detach(resultQ)
            elif q == PVCWorkReq.PVC_UPD_LBL_REQ:
                self._updateLabel(resultQ)
            elif q == PVCWorkReq.PVC_VERIFY_PNG_REQ:
                self._verifyPing(resultQ)
            elif q == PVCWorkReq.PVC_CREATE_REPORT:
                self._report(reportFile)

    def _readCfg(self):
        pvcCfgFile = open(self.cfgFile)
        csvReader = csv.reader(pvcCfgFile)
        next(csvReader, None)
        for row in csvReader:
            if row[3].strip() == 'dynamic':
                pvcType = 'dynamic-vc '
            if row[5].strip() == 'static-associated':
                tnnlType = 'tp-tunnel-assoc '
            elif row[5].strip() == 'dynamic-corout':
                tnnlType = 'tp-tunnel-ingr-corout '
            elif row[5].strip() == 'te':
                tnnlType = 'te-tunnel '
            self.cfg.append(tuple((row[0].strip(),      # destination IP
                                   row[1].strip(),      # PVCNamePrefix
                                   int(row[2].strip()), # PVCCount
                                   pvcType, 
                                   tnnlType, 
                                   row[6].strip(),      # TunnelPrefix
                                   row[7].strip(),      # fec-129
                                   row[8].strip(),      # agi
                                   row[9].strip(),      # saii
                                   row[10].strip(),     # taii
                                   row[11].strip(),     # status-tlv
                                   row[12].strip())))   # bw
        pvcCfgFile.close()

    def _getExistingPVC(self):
        return self.ts.writeCmd('mpls l2-vpn show')

    def _getPWId(self, pvcName):
        """
        Generate a pseudowire id using the PVC name. The IDs on the ingress and 
        egress nodes must match. One simple way is to use the same PVC name on 
        both nodes.
        """
        pwId = 0
        for c in pvcName:
            pwId += ord(c)
        return str(pwId % PW_MAX_ID)

    def _create(self, resultQ):
        logging.debug('Start creating PVCs ...')
        existingPVC = self._getExistingPVC()
        for cfg in self.cfg:
            if not len(cfg):
                continue
            for i in range(1, cfg[2]+1):
                pvcName = cfg[1] + str(i)
                if pvcName in existingPVC:
                    pvc = Pvc(0, 'Failed')
                    self.pvcDB[pvcName] = pvc
                    continue

                cmd = 'mpls l2-vpn create ' + cfg[3] + pvcName
                if cfg[6] == 'enabled':
                    cmd += ' fec-129' + ' agi ' + cfg[7] + str(i) + ' saii ' \
                           + cfg[8] + str(i) + ' taii ' + cfg[9] + str(i)
                else:
                    cmd += ' pw-id ' + self._getPWId(pvcName)
                cmd += ' peer ' + cfg[0] + ' '
                cmd += cfg[4] + cfg[5] + str(i) 
                # status-tlv option
                if cfg[10] == 'enabled':
                    cmd += ' status-tlv on'
                if cfg[11]:
                    cmd += ' bandwidth ' + cfg[11]

                result = self.ts.writeCmd(cmd)
                if 'FAILURE' in result:
                    logging.debug(result)
                else:
                    pvc = Pvc(0, 'Failed')
                    self.pvcDB[pvcName] = pvc
        resultQ.put(globals.ConfigResult.MPLS_PVC_CFG_DONE)

    def _delete(self, resultQ):
        for pvcName, pvc in self.pvcDB.items():
            cmd = 'mpls l2-vpn delete vc ' + pvcName
            self.ts.writeCmd(cmd)
            del self.pvcDB[pvcName]
        resultQ.put(globals.ConfigResult.MPLS_DELETE_PVC_DONE)

    def _attach(self, chassis):
        vlanId = 0
        for pvcName, pvc in self.pvcDB.items():
            cmd = 'virtual-switch interface attach mpls-vc '
            cmd += pvcName + ' vs ' + 'vs' + str(chassis.vlan + vlanId)
            vlanId += 1
            self.ts.writeCmd(cmd)

    def _detach(self, resultQ):
        logging.debug('Start detaching VCs ...')
        for pvcName, pvc in self.pvcDB.items():
            cmd = 'virtual-switch interface detach mpls-vc ' + pvcName
            self.ts.writeCmd(cmd)
        resultQ.put(globals.ConfigResult.MPLS_DETACH_PVC_DONE)
        
    def _updateLabel(self, resultQ):
        logging.debug('Start verifying VC labels ...')
        retries = 0
        exp = 'Operational State         | Up'
        while 1:
            upPvc = 0
            for pvcName, pvc in self.pvcDB.items():
                cmd = 'mpls l2-vpn show vc ' + pvcName
                result = self.ts.writeCmd(cmd)
                searchObj = re.search(r'(Incoming Label\s+)\| (\d+)' , result)
                if searchObj:
                    pvc.inLbl = searchObj.group(2)
                searchObj = re.search(r'(Outgoing Label\s+)\| (\d+)' , result)
                if searchObj:
                    pvc.outLbl = searchObj.group(2)
                if pvc.inLbl != '-1' and pvc.outLbl != '-1' and exp in result:
                    upPvc += 1
            if upPvc < len(self.pvcDB) and retries < PW_MAX_RETRIES:
                time.sleep(1)
                retries += 1
            else:
                resultQ.put(globals.ConfigResult.MPLS_PVC_LBL_UPD_DONE)
                logging.debug('Finish updating VC labels ... retries ' + 
                              str(retries) + ' upPvc ' + str(upPvc))
                break
        
    def _verifyPing(self, resultQ):
        for pvcName, pvc in self.pvcDB.items():
            cmd = 'mpls ping vc ' + pvcName
            exp = '5 packets transmitted, 5 packets received'
            result = self.ts.writeCmd(cmd)
            if exp in result:
                pvc.pingStatus = 'Passed'
            else:
                pvc.pingStatus = 'Failed'
        if resultQ:
            resultQ.put(globals.ConfigResult.PVC_PING_DONE)
        logging.debug('Finish verifying VC ping ...')

    def _report(self, reportFile):
        logging.debug('Reporting PVC result device ' + self.ts.ip + ' ...')
        fieldWidth = 12
        if reportFile:
            f = open(reportFile, 'a')
            t = time.localtime()
            f.write(time.asctime(t) + ' PVC = ' + str(len(self.pvcDB)) + '\n')
            f.write('PVC'.ljust(fieldWidth))
            f.write('InLabel'.ljust(fieldWidth))
            f.write('OutLabel'.ljust(fieldWidth))
            f.write('Ping'.ljust(fieldWidth) + '\n')
            for pvcName, pvc in self.pvcDB.items():
                f.write(pvcName.ljust(fieldWidth))
                f.write(str(pvc.inLbl).ljust(fieldWidth))
                f.write(str(pvc.outLbl).ljust(fieldWidth))
                f.write(pvc.pingStatus.ljust(fieldWidth) + '\n')
            f.close()
