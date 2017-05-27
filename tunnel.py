import sys
import threading
import Queue
import time
import csv
import telnet
import re
import globals
import logging
import chassis
import time
from enum import IntEnum

class Direction(IntEnum):
    UNIDIRECTIONAL = 1
    BIDIRECTIONAL  = 2

class TnnlType(IntEnum):
    TP_DYNAMIC_COROUT = 0
    TP_DYNAMIC_UNIDIR = 1
    TP_STATIC_COROUT  = 2
    TP_STATIC_ASSOC   = 3
    TE_DYNAMIC_UNIDIR = 4

class TnnlOperation(IntEnum):
    CREATE_TUNNEL   = 1
    UPDATE_LABEL    = 2
    VERIFY_LABEL    = 3
    VERIFY_PING     = 4
    VERIFY_BFD      = 5
    VERIFY_TNNL_GRP = 6
    CREATE_REPORT   = 7
    DELETE_TUNNEL   = 8
    VERIFY_GR_AUDIT = 10
    VERIFY_ALL      = 11

tunnelType = ['Dynamic|Bidir', 'Dynamic|Unidir', 'Static|Bidir', 'Static|Assoc']

UPDATE_LABEL_MAX_RETRIES = 10

class Tunnel:
    def __init__(self, tnnlType, fwdOutLbl, reversedInLbl, pingResult, 
                 bfdState, lblRecoveryResult, tnnlGrpResult, tnnlTypeStr):
        self.tnnlType = tnnlType
        self.fwdOutLbl = fwdOutLbl
        self.reversedInLbl = reversedInLbl
        self.pingResult = pingResult
        self.bfdState = bfdState
        self.lblRecoveryResult = lblRecoveryResult
        self.tnnlGrpResult = tnnlGrpResult
        self.tnnlTypeStr = tnnlTypeStr

class TnnlDB(threading.Thread):
    """
    """
    def __init__(self, name, cfgFile, telnetSession):
        threading.Thread.__init__(self)
        self.name = name
        self.setDaemon(1)
        self.workRequestQ = Queue.Queue()
        self.cfgFile = cfgFile
        self.ts = telnetSession
        self.dynTnnls = 0
        self.cfg = [] # list of configuration parameters
        self.tunnels = {} # dictionary of tunnels
        self._readCfg()

    def create(self, resultQ):
        self.workRequestQ.put((TnnlOperation.CREATE_TUNNEL, resultQ, None))

    def delete(self):
        self.workRequestQ.put((TnnlOperation.DELETE_TUNNEL, None, None))

    def updateLabel(self, resultQ):
        self.workRequestQ.put((TnnlOperation.UPDATE_LABEL, resultQ, None))
        
    def report(self, reportFile):
        self.workRequestQ.put((TnnlOperation.CREATE_REPORT, None, reportFile))
 
    def verifyLabel(self):
        self.workRequestQ.put((TnnlOperation.VERIFY_LABEL, None, None))

    def verifyPing(self):
        self.workRequestQ.put((TnnlOperation.VERIFY_PING, None, None))

    def run(self):
        while 1:
            q, resultQ, reportFile = self.workRequestQ.get()
            if q == TnnlOperation.CREATE_TUNNEL:
                self._create(resultQ)
            if q == TnnlOperation.UPDATE_LABEL:
                self._updateLabel(resultQ)
            elif q == TnnlOperation.CREATE_REPORT:
                self._report(reportFile)
            elif q == TnnlOperation.DELETE_TUNNEL:
                self._delete()
            elif q == TnnlOperation.VERIFY_PING:
                self._verifyPing()
            elif q == TnnlOperation.VERIFY_BFD:
                self._verifyBFD()
            elif q == TnnlOperation.VERIFY_LABEL:
                self._verifyLblRecovery()
            elif q == TnnlOperation.VERIFY_TNNL_GRP:
                self._verifyTnnlGrp()
            elif q == TnnlOperation.VERIFY_GR_AUDIT:
                self._verifyGRAudit()

    def _readCfg(self):
        tnnlCfgFile = open(self.cfgFile)
        csvReader = csv.reader(tnnlCfgFile)
        next(csvReader, None)
        for row in csvReader:
            if not len(row):
                continue
            path = backup = bfd = bfdProfile = reopt = fwdTnnl = ''
            reversedTnnl = backupTnnl = bwProfile = ''
            if row[3] == 'tp-dynamic' and row[4] == 'bidirectional':
                tnnlTypeStr = 'rsvp-ingress-corout'
                tnnlType = TnnlType.TP_DYNAMIC_COROUT
            if row[3] == 'tp-dynamic' and row[4] == 'unidirectional':
                tnnlType = TnnlType.TP_DYNAMIC_UNIDIR
                tnnlTypeStr = 'rsvp-ingress-unidir'
            if row[3] == 'tp-static' and row[4] == 'bidirectional':
                tnnlType = TnnlType.TP_STATIC_COROUT
                tnnlTypeStr = 'static-ingress-corout'
            if row[3] == 'tp-static' and row[4] == 'associated':
                tnnlType = TnnlType.TP_STATIC_ASSOC
                tnnlTypeStr = 'static-ingress-assoc'
            if row[3] == 'te-dynamic' and row[4] == 'unidirectional':
                tnnlTypeStr = 'rsvp-ingress'
                tnnlType = TnnlType.TE_DYNAMIC_UNIDIR

            if row[5]:
                path = ' explicit-tunnel-path ' + row[5]
            if row[6] == 'enabled':
                backup = ' auto-backup on' 
            if row[7] == 'enabled':
                bfd = ' bfd-monitor enable'
            if row[8]:
                bfdProfile = ' bfd-profile ' + row[8]
            if row[9] == 'enabled':
                reopt = ' lsp-reopt enable lsp-reopt-interval ' + row[10]
            if row[11]:
                fwdTnnl = ' forward-tunnel ' + row[11]
            if row[12]:
                reversedTnnl = ' reverse-dyntun-name ' + row[12]
            if row[13]:
                backupTnnl = ' backup-tunnel ' + row[13]
            if row[14]:
                bwProfile = ' bandwidth-profile ' + row[14]
                
            self.cfg.append(tuple((row[0], row[1], int(row[2]), tnnlType, 
                                   tnnlTypeStr, path, backup, bfd, bfdProfile, 
                                   reopt, fwdTnnl, reversedTnnl, backupTnnl, 
                                   bwProfile)))
        tnnlCfgFile.close()

    def _mpls_cmd(self, tnnlType):
        if tnnlType == TnnlType.TP_DYNAMIC_COROUT or \
           tnnlType == TnnlType.TP_DYNAMIC_UNIDIR or \
           tnnlType == TnnlType.TP_STATIC_COROUT or \
           tnnlType == TnnlType.TP_STATIC_ASSOC:
            return 'gmpls tp-tunnel'
        elif tnnlType == TnnlType.TE_DYNAMIC_UNIDIR:
            return 'mpls tunnel'

    def _createFromCfg(self, cfg, existingTnnls):
        for i in range(1, cfg[2]+1):
            tnnlName = cfg[1] + str(i) 
            if tnnlName in existingTnnls:
                tnnl = Tunnel(cfg[3], -1, -1, 'N/A', 'N/A', 'N/A', 'N/A', cfg[4])
                self.tunnels[tnnlName] = tnnl
                if (cfg[3] == TnnlType.TP_DYNAMIC_UNIDIR or 
                    cfg[3] == TnnlType.TP_DYNAMIC_COROUT):
                    self.dynTnnls += 1
                continue
            cmd = self._mpls_cmd(cfg[3])
            cmd += ' create ' + cfg[4] + ' ' + tnnlName
            if cfg[3] == TnnlType.TP_STATIC_ASSOC:
                cmd += cfg[10] + str(i) + cfg[11] + str(i)
            else:
                cmd += ' dest-ip ' + cfg[0]

            cmd += cfg[5] + cfg[6] + cfg[7] + cfg[8] + cfg[9] 
            if cfg[12]:
                cmd += cfg[12] + str(i)
            cmd += cfg[13] # bw profile

            result = self.ts.writeCmd(cmd)
            if 'FAILURE' in result:
                print(result)
            else:
                tnnl = Tunnel(cfg[3], -1, -1, 'N/A', 'N/A', 'N/A', 'N/A', cfg[4])
                self.tunnels[tnnlName] = tnnl
                if (cfg[3] == TnnlType.TP_DYNAMIC_UNIDIR or 
                    cfg[3] == TnnlType.TP_DYNAMIC_COROUT):
                    self.dynTnnls += 1

    def _getExistingTnnl(self):
        tpTnnl = self.ts.writeCmd(self._mpls_cmd(TnnlType.TP_DYNAMIC_COROUT) + ' show')
        assocTnnl = self.ts.writeCmd(self._mpls_cmd(TnnlType.TP_STATIC_ASSOC) + 
                                     ' show matching-assoc')
        teTnnl = self.ts.writeCmd(self._mpls_cmd(TnnlType.TE_DYNAMIC_UNIDIR) + ' show')
        return tpTnnl + assocTnnl + teTnnl

    def _create(self, resultQ):
        global iChassis

        logging.debug('Start creating tunnels ...')
        existingTnnls = self._getExistingTnnl()

        for cfg in self.cfg:
            if len(cfg):
                self._createFromCfg(cfg, existingTnnls)
        resultQ.put(globals.ConfigResult.MPLS_TUNNEL_CFG_DONE)

    def _report(self, reportFile):
        logging.debug('Reporting tunnel result on device ' + self.ts.ip + ' ...')
        fieldWidth = 12
        if reportFile:
            f = open(reportFile, 'a')
            t = time.localtime()
            f.write(time.asctime(t) + ' Tunnel = ' + 
                             str(len(self.tunnels)) + '\n')
            f.write('Tunnel'.ljust(fieldWidth))
            f.write('Fwd-out-lbl'.ljust(fieldWidth)) 
            f.write('Ping'.ljust(fieldWidth))
            f.write('Lbl-Recovery'.ljust(fieldWidth) + '\n')
            for tnnlName, tnnl in sorted(self.tunnels.items()):
                if tnnl.tnnlType == TnnlType.TE_DYNAMIC_UNIDIR:
                    f.write(tnnlName.ljust(fieldWidth))
                    f.write(str(tnnl.fwdOutLbl).ljust(fieldWidth))
                    f.write(tnnl.pingResult.ljust(fieldWidth))
                    f.write(tnnl.lblRecoveryResult.ljust(fieldWidth) + '\n')
            f.close()

    def _delete(self):
        logging.debug('Deleting tunnels ...')
        # delete associated tunnels first
        for tnnlName, tnnl in self.tunnels.items():
            if tnnl.tnnlType == TnnlType.TP_STATIC_ASSOC or 'bkp' in tnnlName:
                cmd = self._mpls_cmd(tnnl.tnnlType)
                cmd += ' delete ' + tnnl.tnnlTypeStr + ' ' + tnnlName
                result = self.ts.writeCmd(cmd)
                if 'FAILURE' in result:
                    print(result)
                else:
                    del self.tunnels[tnnlName]
            
        for tnnlName, tnnl in self.tunnels.items():
            cmd = self._mpls_cmd(tnnl.tnnlType)
            cmd += ' delete ' + tnnl.tnnlTypeStr + ' ' + tnnlName
            result = self.ts.writeCmd(cmd)
            if 'FAILURE' in result:
                print(result)
            else:
                self.tunnels.pop(tnnlName)

    def _verifyPing(self):
        logging.debug('Start verifying mpls ping ...')
        exp = ' packets transmitted, 5 packets received'
        for tnnlName, tnnl in self.tunnels.items():
            cmd = ' mpls ping '
            if tnnl.tnnlType == TnnlType.STATIC_ASSOC:
                cmd += ' assoc-tp-lsp ' + tnnlName
            elif tnnl.tnnlType == TnnlType.TE_DYNAMIC_UNIDIR:
                cmd += ' tunnel '
            cmd =+ tnnlName
            result = self.ts.writeCmd(cmd)
            if exp in result:
                tnnl.pingResult = 'Pass'
            else:
                tnnl.pingResult = 'Fail'

    def _verifyBFD(self):
        logging.debug('Start verifying bfd over mpls ...')
        for tnnlName, tnnl in self.tunnels.items():
            if tnnl.tnnlType == TnnlType.TP_STATIC_ASSOC:
                cmd = 'bfd session show tunnel tp-assoc ' + tnnlName
                result = self.ts.writeCmd(cmd)
                if 'Session operationally up' in result:
                    tnnl.bfdState = 'Up'
                else:
                    tnnl.bfdState = 'Down'

    def _verifyLblRecovery(self):
        logging.debug('Start verifying label recovering ...')
        for tnnlName, tnnl in self.tunnels.items():
            searchObj = None
            cmd = self._mpls_cmd(tnnl.tnnlType)
            cmd += ' show ' + tnnl.tnnlTypeStr + ' ' + tnnlName
            result = self.ts.writeCmd(cmd)
            
            if tnnl.tnnlType == TnnlType.TP_DYNAMIC_UNIDIR:
                # Extract the label from the output:
                # Forward Out-Label                    |100001
                searchObj = re.search(r'Forward Out-Label\s+\|\d+', result)
            elif tnnl.tnnlType == TnnlType.TE_DYNAMIC_UNIDIR:
                searchObj = re.search(r'(Out-Label\s+)\|(\d+)', result)
            if searchObj:
                if tnnl.fwdOutLbl == searchObj.group(0).split('|')[1]:
                    tnnl.lblRecoveryResult = 'Pass'
                else:
                    tnnl.lblRecoveryResult = 'Fail'

    def _updateLabel(self, resultQ):
        logging.debug('Start updating labels ...')
        updateLblRetries = dynTnnlWithLbl = 0
        while 1:
            for tnnlName, tnnl in self.tunnels.items():
                searchObj = None
                cmd = self._mpls_cmd(tnnl.tnnlType)
                cmd += ' show ' + tnnl.tnnlTypeStr + ' ' + tnnlName
                result = self.ts.writeCmd(cmd)
                if tnnl.tnnlType == TnnlType.TP_DYNAMIC_UNIDIR:
                    # Forward Out-Label                    |100001
                    searchObj = re.search(r'(Forward Out-Label\s+)\|(\d+)', result)
                elif tnnl.tnnlType == TnnlType.TE_DYNAMIC_UNIDIR:
                    searchObj = re.search(r'(Out-Label\s+)\|(\d+)', result)
                # Extract the label from the output:
                if searchObj:
                    tnnl.fwdOutLbl = searchObj.group(2)
                    dynTnnlWithLbl += 1
            if dynTnnlWithLbl < self.dynTnnls:
                if updateLblRetries < UPDATE_LABEL_MAX_RETRIES:
                    time.sleep(1)
                    updateLblRetries += 1
            else:
                resultQ.put(globals.ConfigResult.MPLS_TNL_LBL_UPD_DONE)
                break

    def _getStdbyCTXSession(self):
        result = self.ts.writeCmd('module show slot CTX1.ctm')
        searchObj = re.search(r'Protection Status\s+\| Primary', result)
        stdbyCTX = telnet.TelnetSession(sys.argv[1], globals.user, 
                                        globals.password)
        if searchObj:
            stdbyCTXSlot = '32'
        else:
            stdbyCTXSlot = '31'
        stdbyCTX.writeCmd('diag shell')
        stdbyCTX.pe.sendline('slot ' + stdbyCTXSlot)
        stdbyCTX.pe.expect('login:')
        stdbyCTX.pe.sendline (globals.user)
        stdbyCTX.pe.expect ('Password:')
        stdbyCTX.pe.sendline (globals.password)
        stdbyCTX.pe.expect ('>')
        stdbyCTX.writeCmd('diag shell')
        return stdbyCTX
        
    def _verifyTnnlGrp(self):
        logging.debug('Start verifying tunnel groups ...')
        cmd = 'mplstm show tunnel '
        stdbyCTX = self._getStdbyCTXSession()
        self.ts.writeCmd('diag shell')
        
        for tnnlName, tnnl in self.tunnels.items():
            if tnnl.tnnlType == TnnlType.TP_STATIC_ASSOC:
                continue
            stdbyResult = stdbyCTX.writeCmd(cmd + tnnlName)
            stdbySearchObj = re.search(r'Tunnel Group Index\s+\|\d+', stdbyResult)
            result = self.ts.writeCmd(cmd + tnnlName)
            searchObj = re.search(r'Tunnel Group Index\s+\|\d+', result)
            tnnl.tnnlGrpResult = 'Fail'
            if stdbySearchObj and searchObj:
                if stdbySearchObj.group(0) == searchObj.group(0):
                    tnnl.tnnlGrpResult = 'Pass'
        self.ts.writeCmd('exit')
        stdbyCTX.pe.close()

