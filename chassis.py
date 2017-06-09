import threading
import logging
import time
import Queue
import csv
import re
import time
import globals
from enum import Enum

resultQ = Queue.Queue()

class ChassisOperation(Enum):
    CHASSIS_APPLY_CONFIG     = 1    
    CHASSIS_REMOVE_CONFIG    = 2
    PERFORM_GRACEFUL_RESTART = 3
    VERIFY_GR_LABEL_RECOVERY = 4
    VERIFY_GR_AUDIT          = 5
    CHASSIS_REPORT           = 6
    LM_RESTART               = 7
    PORT_TOGGLE              = 8

class Chassis(threading.Thread):
    def __init__(self, name, role, cfgFile, telnetSession, reportFile=None):
        threading.Thread.__init__(self)
        self.workRequestQ = Queue.Queue()
        self.name = name
        self.role = role
        self.ts = telnetSession
        self.setDaemon(1)
        self.result = []
        self.cfgFile = cfgFile
        self.iport = ''
        self.eport = ''
        self.islot = ''
        self.eslot = ''
        self.reportFile = reportFile
        self._readCfg()

    def applyCfg(self):
        self.workRequestQ.put((ChassisOperation.CHASSIS_APPLY_CONFIG, 
                               None, None, None))
    def removeCfg(self):
        self.workRequestQ.put((ChassisOperation.CHASSIS_REMOVE_CONFIG, 
                               None, None, None))
    def portToggle(self, tnnlDB, pvcDB):
        self.workRequestQ.put((ChassisOperation.PORT_TOGGLE, 
                               None, tnnlDB, pvcDB))
    def lmRestart(self, tnnlDB, pvcDB):
        self.workRequestQ.put((ChassisOperation.LM_RESTART, 
                               None, tnnlDB, pvcDB))
    def gracefulRestart(self, resultQ, tnnlDB, pvcDB):
        self.workRequestQ.put((ChassisOperation.PERFORM_GRACEFUL_RESTART, 
                               resultQ, tnnlDB, pvcDB))
    def verifyGRSummary(self):
        self.workRequestQ.put((ChassisOperation.VERIFY_GR_LABEL_RECOVERY, 
                               None, None, None))
    def report(self):
        self.workRequestQ.put((ChassisOperation.CHASSIS_REPORT, 
                               None, None, None))
    def run(self):
        while 1:
            q, resultQ, tnnlDB, pvcDB = self.workRequestQ.get()
            if q == ChassisOperation.CHASSIS_APPLY_CONFIG:
                self._applyCfg()
            elif q == ChassisOperation.CHASSIS_REMOVE_CONFIG:
                self._removeCfg()
            elif q == ChassisOperation.PERFORM_GRACEFUL_RESTART:
                self._gracefulRestart(resultQ, tnnlDB, pvcDB)
            elif q == ChassisOperation.PORT_TOGGLE:
                self._portToggle(tnnlDB, pvcDB)
            elif q == ChassisOperation.LM_RESTART:
                self._lmRestart(tnnlDB, pvcDB)
            elif q == ChassisOperation.VERIFY_GR_LABEL_RECOVERY:
                self._verifyLabelRecovery()
            elif q == ChassisOperation.VERIFY_GR_AUDIT:
                self._verifyGRAudit()
            elif q == ChassisOperation.CHASSIS_REPORT:
                self._report()

    def _readCfg(self):
        if not self.cfgFile:
            return

        connFile = open(self.cfgFile)
        csvReader = csv.reader(connFile)
        i = 0
        for row in csvReader:
            # skip the top 8 lines of the header
            if i < 8:
                i += 1
                continue
            if not len(row):
                continue # skip blank lines
                
            self.iAcPort = row[0]
            self.eAcPort = row[5]
            self.iport = row[1]
            self.eport = row[4]
            if self.iport[1] == '/':
                self.islot = 'LM' + self.iport[0]
            else:
                self.islot = 'LM' + self.iport[0:1]
            if self.eport[1] == '/':
                self.eslot = 'LM' + self.eport[0]
            else:
                self.eslot = 'LM' + self.eport[0:1]
            self.vlan = int(row[6])
            self.vlanCount = int(row[7])

    def _createVS(self):
        for i in range(self.vlanCount):
            self.ts.writeCmd('virtual-switch create vs ' + 'vs' + str(self.vlan + i))

    def _createACSubport(self):
        if self.role == 'ingress':
            port = self.iAcPort
        else:
            port = self.eAcPort
        for i in range(self.vlanCount):
            self.ts.writeCmd('sub-port create sub-port ac-' + str(self.vlan + i) + 
                             ' parent-port ' + port + ' classifier-precedence ' + 
                             str(self.vlan + i))
            self.ts.writeCmd('sub-port add sub-port ' + 'ac-' + str(self.vlan + i) +
                             ' vtag-stack ' + str(self.vlan + i))

    def _attachACSubport(self):
        for i in range(self.vlanCount):
            self.ts.writeCmd('virtual-switch interface attach sub-port ' + 
                             'ac-' + str(self.vlan + i) + ' vs ' + 'vs' + 
                             str(self.vlan + i))

    def _applyCfg(self):
        logging.debug('Start applying global config ...')
        self.ts.writeCmd('system shell set global-more off')
        self.ts.writeCmd('rsvp-te graceful-restart enable')
        self.ts.writeCmd('rsvp-te graceful-restart set restart-time 180')
        self.ts.writeCmd('rsvp-te graceful-restart set recovery-time 240 ')
        self.ts.writeCmd('ldp graceful-restart enable')
        self.ts.writeCmd('ldp graceful-restart set reconnect-time 300')
        self.ts.writeCmd('ldp graceful-restart set recovery-time  360')
        self.ts.writeCmd('mpls tunnel-bandwidth-profile create bandwidth-profile xyz bandwidth 1000000')
        self._createVS()
        self._createACSubport()
        self._attachACSubport()

    def _removeCfg(self):
        logging.debug('Start removing global config ...')
        for i in range(self.vlanCount):
            self.ts.writeCmd('virtual-switch interface detach sub-port ' + 
                             'ac-' + str(self.vlan + i))
            self.ts.writeCmd('sub-port delete sub-port ac-' + str(self.vlan + i)) 
            self.ts.writeCmd('virtual-switch delete vs ' + 'vs' + str(self.vlan + i))

    def _gracefulRestart(self, resultQ, tnnlDB, pvcDB):
        logging.debug('Performing graceful restart ...')
        if self.reportFile:
            f = open(self.reportFile, 'a')
            f.write('Performing graceful restart ...\n')
            f.close()

        #cmd = 'module high-avail switchover-to-standby'
        #result = self.ts.writeCmd(cmd)
        #time.sleep(4*60)
        #self.ts.connect()
        while 1:
            result = self.ts.writeCmd('module show')
            regex = re.compile(r'CTX\s*\|\s*Enabled\s*\|\s*Enabled\s*')
            matchObj = regex.findall(result)
            if len(matchObj) == 2:
                self._verifyGRAudit()
                self._verifyLabelRecovery()
                tnnlDB.updateLabel(resultQ)
                while 1:
                    q = resultQ.get()
                    if q == globals.ConfigResult.MPLS_TNL_LBL_UPD_DONE:
                        pvcDB.updateLabel(resultQ)
                    elif q == globals.ConfigResult.MPLS_PVC_LBL_UPD_DONE:
                        break
                tnnlDB.verifyLabel()
                pvcDB.verifyPing(resultQ)
                while 1:
                    q = resultQ.get()
                    if q == globals.ConfigResult.PVC_PING_DONE:
                        self._report()
                        pvcDB.report(self.reportFile)
                        tnnlDB.report(self.reportFile)
                        break
                resultQ.put(globals.ConfigResult.GRACEFULL_RESTART_DONE)
                break
            else:
                time.sleep(5)

    def _verifyGRAudit(self):
        logging.debug('Start verifying audit ...')
        cmd = 'module high-avail show'
        result = self.ts.writeCmd(cmd)
        searchObj = re.search(r'(Audit Result)\s\| (Audit Success)', result)
        if searchObj:
            self.auditResult = 'Pass'
        else:
            self.auditResult = 'Fail'

    def _verifyLabelRecovery(self):
        logging.debug('Start verifying GR summary ...')
        tunnelCnt = success = fail = 0
        startTime = ''
        cmd = 'rsvp-te graceful-restart show history'
        result = self.ts.writeCmd(cmd)

        searchObj = re.search(r'Last RSVP GR Start Date.*', result)
        if searchObj:
            startTime = searchObj.group(0).split('|')
            logging.debug(startTime)

        searchObj = re.search(r'(recovered succesfully)\s+\|(\d+)', result)
        if searchObj:
            success = searchObj.group(2)
        else:
            success = 0

        searchObj = re.search(r'(Total # of Tunls)\s+\|(\d+)', result)
        if searchObj:
            tunnelCnt = searchObj.group(2)
        else:
            tunnelCnt = 0

        searchObj = re.search(r'(failed recovery)\s+\|(\d+)', result)
        if searchObj:
            fail = searchObj.group(2)
        else:
            fail = tunnelCnt

        self.result.append((startTime, tunnelCnt, success, fail))

    def _report(self):
        if not len(self.result):
            return

        logging.debug('Reporting chassis result on device ' + self.ts.ip + ' ...')
        if self.reportFile:
            fieldWidth = 15
            f = open(self.reportFile, 'a')
            f.write('GR info:\n')
            f.write('StartTime'.ljust(2*fieldWidth))
            f.write('TunnelCnt'.ljust(fieldWidth))
            f.write('Sucess'.ljust(fieldWidth))
            f.write('Fail'.ljust(fieldWidth) + '\n')
            f.write(self.result[0][0].ljust(2*fieldWidth))
            f.write(str(self.result[0][1]).ljust(fieldWidth))
            f.write(str(self.result[0][2]).ljust(fieldWidth))
            f.write(str(self.result[0][3]).ljust(fieldWidth) + '\n')
            f.close()

    def _portToggle(self, tnnlDB, pvcDB):
        if self.reportFile:
            f = open(self.reportFile, 'a')
            f.write('Disabling/enabling ingress port ' + self.iport + '\n')
            f.close()

        cmd = 'port disable port ' + self.iport
        result = self.ts.writeCmd(cmd)
        time.sleep(.5)
        cmd = 'port enable port ' + self.iport
        result = self.ts.writeCmd(cmd)
        time.sleep(1)

        tnnlDB.updateLabel(resultQ)
        while 1:
            q = resultQ.get()
            if q == globals.ConfigResult.MPLS_TNL_LBL_UPD_DONE:
                pvcDB.updateLabel(resultQ)
            elif q == globals.ConfigResult.MPLS_PVC_LBL_UPD_DONE:
                break
        pvcDB.verifyPing(resultQ)
        while 1:
            q = resultQ.get()
            if q == globals.ConfigResult.PVC_PING_DONE:
                pvcDB.report(self.reportFile)
                break

    def _lmRestart(self, tnnlDB, pvcDB):
        if self.reportFile:
            f = open(self.reportFile, 'a')
            f.write('Restarting ingress slot ' + self.islot + '\n')
            f.close()

        result = self.ts.writeCmd('module restart slot ' + self.islot)
        exp = 'OperState              | Enabled' 
        time.sleep(180)
        while 1:
            result = self.ts.writeCmd('module show slot ' + self.islot)
            if exp in result:
                tnnlDB.updateLabel(resultQ)
                while 1:
                    q = resultQ.get()
                    if q == globals.ConfigResult.MPLS_TNL_LBL_UPD_DONE:
                        pvcDB.updateLabel(resultQ)
                    elif q == globals.ConfigResult.MPLS_PVC_LBL_UPD_DONE:
                        break
                pvcDB.verifyPing(resultQ)
                while 1:
                    q = resultQ.get()
                    if q == globals.ConfigResult.PVC_PING_DONE:
                        pvcDB.report(self.reportFile)
                        break
                break
            else:
                time.sleep(5)
        
