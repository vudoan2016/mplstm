import sys
import threading
import Queue
import logging
import time
import csv
import telnet
import re
import globals
from enum import IntEnum

class Direction(IntEnum):
    UNIDIRECTIONAL = 1
    BIDIRECTIONAL  = 2

class TnnlType(IntEnum):
    DYNAMIC_COROUT = 0
    DYNAMIC_UNIDIR = 1
    STATIC_COROUT  = 2
    STATIC_ASSOC   = 3

class TnnlOperation(IntEnum):
    CREATE_TUNNEL   = 1
    UPDATE_LABEL    = 2
    VERIFY_LABEL    = 3
    VERIFY_PING     = 4
    VERIFY_BFD      = 5
    VERIFY_TNNL_GRP = 6
    CREATE_REPORT   = 7
    PERFORM_HA      = 8
    DELETE_TUNNEL   = 9
    VERIFY_ALL      = 10

tunnelType = ["Dynamic|Bidir", "Dynamic|Unidir", "Static|Bidir", "Static|Assoc"]

class TnnlDB(threading.Thread):
    """
    """
    def __init__(self, name, cfgFile, telnetSession, reportFile=None):
        threading.Thread.__init__(self)
        self.name = name
        self.setDaemon(1)
        self.workRequestQ = Queue.Queue()
        self.cfgFile = cfgFile
        self.reportFile = reportFile
        self.ts = telnetSession
        self.cfg = [] # list of configuration parameters
        self.tunnels = {} # dictionary of tunnels
        self._readCfg()

    def _readCfg(self):
        tnnlCfgFile = open(self.cfgFile)
        csvReader = csv.reader(tnnlCfgFile)
        next(csvReader, None)
        for row in csvReader:
            if not len(row):
                continue
            path = backup = bfd = bfdProfile = reopt = fwdTnnl = reversedTnnl = ""
            if row[3] == "dynamic" and row[4] == "bidirectional":
                tnnlTypeStr = "rsvp-ingress-corout"
                tnnlType = TnnlType.DYNAMIC_COROUT
            if row[3] == "dynamic" and row[4] == "unidirectional":
                tnnlType = TnnlType.DYNAMIC_UNIDIR
                tnnlTypeStr = "rsvp-ingress-unidir"
            if row[3] == "static" and row[4] == "bidirectional":
                tnnlType = TnnlType.STATIC_COROUT
                tnnlTypeStr = "static-ingress-corout"
            if row[3] == "static" and row[4] == "associated":
                tnnlType = TnnlType.STATIC_ASSOC
                tnnlTypeStr = "static-ingress-assoc"
            if row[5]:
                path = " explicit-tunnel-path " + row[5]
            if row[6] == "enabled":
                backup = " auto-backup on" 
            if row[7] == "enabled":
                bfd = " bfd-monitor enable"
            if row[8]:
                bfdProfile = " bfd-profile " + row[8]
            if row[9] == "enabled":
                reopt = " lsp-reopt enable lsp-reopt-interval " + row[10]
            if row[11]:
                fwdTnnl = " forward-tunnel " + row[11]
            if row[12]:
                reversedTnnl = " reverse-dyntun-name " + row[12]

            self.cfg.append(tuple((row[0], row[1], int(row[2]), tnnlType, 
                                   tnnlTypeStr, path, backup, bfd, bfdProfile, 
                                   reopt, fwdTnnl, reversedTnnl)))
        tnnlCfgFile.close()

    def _createFromCfg(self, cfg, existingTnnls):
        for i in range(1, cfg[2]+1):
            tnnlName = cfg[1] + str(i) 
            if tnnlName in existingTnnls:
                self.tunnels[tnnlName] = [cfg[3], -1, -1, "N/A", "N/A", 
                                          "N/A", "N/A", cfg[4]]
                continue
            
            cmd = "gmpls tp-tunnel create " + cfg[4] + " " + tnnlName
            if cfg[3] == TnnlType.STATIC_ASSOC:
                cmd += cfg[10] + str(i) + cfg[11] + str(i)
            else:
                cmd += " dest-ip " + cfg[0]

            cmd += cfg[5] + cfg[6] + cfg[7] + cfg[8] + cfg[9]
            result = self.ts.writeCmd(cmd)
            if "FAILURE" in result:
                print(result)
            else:
                self.tunnels[tnnlName] = [cfg[3], -1, -1, "N/A", "N/A", 
                                          "N/A", "N/A", cfg[4]]

    def _getExistingTnnl(self):
        tpTnnl = self.ts.writeCmd("gmpls tp-tunnel show")
        assocTnnl = self.ts.writeCmd("gmpls tp-tunnel show matching-assoc")
        return tpTnnl + assocTnnl

    def _create(self, resultQ):
        existingTnnls = self._getExistingTnnl()

        for cfg in self.cfg:
            if len(cfg):
                self._createFromCfg(cfg, existingTnnls)

        resultQ.put(globals.CfgResult.CFG_TUNNEL_DONE)
        time.sleep(5)
        self.workRequestQ.put((TnnlOperation.UPDATE_LABEL, None))

    def create(self, resultQ):
        self.workRequestQ.put((TnnlOperation.CREATE_TUNNEL, resultQ))

    def _HA(self):
        cmd = "module high-avail switchover-to-standby"
        result = self.ts.writeCmd(cmd)
        time.sleep(3*60)
        self.ts.connect()
        while True:
            result = self.ts.writeCmd("module show")
            regex = re.compile(r'CTX\s*\|\s*Enabled\s*\|\s*Enabled\s*')
            matchObj = regex.findall(result)
            if len(matchObj) == 2:
                self.workRequestQ.put((TnnlOperation.VERIFY_LABEL, None))
                self.workRequestQ.put((TnnlOperation.VERIFY_PING, None))
                self.workRequestQ.put((TnnlOperation.VERIFY_BFD, None))
                self.workRequestQ.put((TnnlOperation.CREATE_REPORT, None))
                break
            else:
                time.sleep(5)

    def HA(self):
        self.workRequestQ.put((TnnlOperation.PERFORM_HA, None))

    def _report(self):
        if self.reportFile is not None:
            f = open(self.reportFile, "w")
            try:
                writer = csv.writer(f)
                f.write("Tunnel = " + str(len(self.tunnels)) + "\n")
                writer.writerow(("Tunnel", "TnnlType", "Fwd-out-lbl", "Reversed-in-lbl", 
                                 "Ping", "BFD", "Lbl-Recovery", "Tnnl-Grp"))
                for tunnel, attrs in sorted(self.tunnels.items()):
                    writer.writerow((tunnel, tunnelType[attrs[0]], attrs[1], 
                                     attrs[2], attrs[3], attrs[4], attrs[5], 
                                     attrs[6]))
            finally:
                f.close()

    def report(self):
        self.workRequestQ.put((TnnlOperation.CREATE_REPORT, None))
 
    def _delete(self):
        # delete associated tunnels first
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.STATIC_ASSOC:
                cmd = "gmpls tp-tunnel delete " + attrs[7] + " " + tunnel
                result = self.ts.writeCmd(cmd)
                if "FAILURE" in result:
                    print(result)
                else:
                    self.tunnels.pop(tunnel)
            
        for tunnel, attrs in self.tunnels.items():
            cmd = "gmpls tp-tunnel delete " + attrs[7] + " " + tunnel
            result = self.ts.writeCmd(cmd)
            if "FAILURE" in result:
                print(result)
            else:
                self.tunnels.pop(tunnel)

    def delete(self):
        self.workRequestQ.put((TnnlOperation.DELETE_TUNNEL, None))

    def _verifyPing(self):
        logging.debug("Verifying mpls ping ...")
        exp = "1 packets transmitted, 1 packets received"
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.STATIC_ASSOC:
                cmd = "mpls ping assoc-tp-lsp " + tunnel + " count 1"
                result = self.ts.writeCmd(cmd)
                if exp in result:
                    attrs[3] = "Pass"
                else:
                    attrs[3] = "Fail"

    def _verifyBFD(self):
        logging.debug("Verifying bfd over mpls ...")
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.STATIC_ASSOC:
                cmd = "bfd session show tunnel tp-assoc " + tunnel
                result = self.ts.writeCmd(cmd)
                if "Session operationally up" in result:
                    attrs[4] = "Up"
                else:
                    attrs[4] = "Down"

    def _verifyLblRecovery(self):
        logging.debug("Verifying label recovering ...")
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.DYNAMIC_UNIDIR:
                cmd = "gmpls tp-tunnel show rsvp-ingress-unidir " + tunnel
                result = self.ts.writeCmd(cmd)
                # Extract the label from the output:
                #|Forward Out-Label                    |100001
                searchObj = re.search(r'Forward Out-Label\s+\|\d+', result)
                if searchObj:
                    if attrs[1] == searchObj.group(0).split('|')[1]:
                        attrs[5] = "Pass"
                    else:
                        attrs[5] = "Fail"

    def _updateLabel(self):
        logging.debug("Updating labels ...")
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.DYNAMIC_UNIDIR:
                cmd = "gmpls tp-tunnel show rsvp-ingress-unidir " + tunnel
                result = self.ts.writeCmd(cmd)
                # Extract the label from the output:
                #|Forward Out-Label                    |100001
                searchObj = re.search(r'Forward Out-Label\s+\|\d+', result)
                if searchObj:
                    attrs[1] = searchObj.group(0).split('|')[1]

        # Ready to verify MPLS ping
        self.workRequestQ.put((TnnlOperation.VERIFY_PING, None))
        self.workRequestQ.put((TnnlOperation.VERIFY_BFD, None))
        self.workRequestQ.put((TnnlOperation.VERIFY_TNNL_GRP, None))

    def _getStdbyCTXSession(self):
        result = self.ts.writeCmd("module show slot CTX1.ctm")
        searchObj = re.search(r'Protection Status\s+\| Primary', result)
        stdbyCTX = telnet.TelnetSession(sys.argv[1], globals.user, 
                                        globals.password)
        if searchObj:
            stdbyCTXSlot = "32"
        else:
            stdbyCTXSlot = "31"
        stdbyCTX.writeCmd("diag shell")
        stdbyCTX.pe.sendline("slot " + stdbyCTXSlot)
        stdbyCTX.pe.expect("login:")
        stdbyCTX.pe.sendline (globals.user)
        stdbyCTX.pe.expect ('Password:')
        stdbyCTX.pe.sendline (globals.password)
        stdbyCTX.pe.expect (">")
        stdbyCTX.writeCmd("diag shell")
        return stdbyCTX
        
    def _verifyTnnlGrp(self):
        logging.debug("Verifying tunnel groups ...")
        cmd = "mplstm show tunnel "
        stdbyCTX = self._getStdbyCTXSession()
        self.ts.writeCmd("diag shell")
        
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.STATIC_ASSOC:
                continue
            stdbyResult = stdbyCTX.writeCmd(cmd + tunnel)
            stdbySearchObj = re.search(r'Tunnel Group Index\s+\|\d+', stdbyResult)
            result = self.ts.writeCmd(cmd + tunnel)
            searchObj = re.search(r'Tunnel Group Index\s+\|\d+', result)
            attrs[6] = "Fail"
            if stdbySearchObj and searchObj:
                if stdbySearchObj.group(0) == searchObj.group(0):
                    attrs[6] = "Pass"
        self.ts.writeCmd("exit")
        stdbyCTX.pe.close()

    def run(self):
        while 1:
            q, resultQ = self.workRequestQ.get()
            if q == TnnlOperation.CREATE_TUNNEL:
                self._create(resultQ)
            if q == TnnlOperation.UPDATE_LABEL:
                self._updateLabel()
            elif q == TnnlOperation.VERIFY_PING:
                self._verifyPing()
            elif q == TnnlOperation.VERIFY_BFD:
                self._verifyBFD()
            elif q == TnnlOperation.CREATE_REPORT:
                self._report()
            elif q == TnnlOperation.VERIFY_LABEL:
                self._verifyLblRecovery()
            elif q == TnnlOperation.PERFORM_HA:
                self._HA()
            elif q == TnnlOperation.VERIFY_TNNL_GRP:
                self._verifyTnnlGrp()
            elif q == TnnlOperation.DELETE_TUNNEL:
                self._delete()
