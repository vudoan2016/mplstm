import sys
import threading
import Queue
import logging
import time
import csv
import telnet
import re
import globals
from enum import Enum

class Direction(Enum):
    UNIDIRECTIONAL = 1
    BIDIRECTIONAL  = 2

class TnnlType(Enum):
    DYNAMIC_COROUT = 1
    DYNAMIC_UNIDIR = 2
    STATIC_COROUT  = 3
    STATIC_ASSOC   = 4

class TnnlOperation(Enum):
    CREATE_TUNNEL   = 1
    UPDATE_LABEL    = 2
    VERIFY_LABEL    = 3
    VERIFY_PING     = 4
    VERIFY_BFD      = 5
    VERIFY_TNNL_GRP = 6
    CREATE_REPORT   = 7
    PERFORM_HA      = 8
    VERIFY_ALL      = 9

class TnnlDB(threading.Thread):
    """
    """
    def __init__(self, cfgFile, telnetSession, reportFile=None):
        threading.Thread.__init__(self)
        self.setDaemon(1)
        self.workRequestQ = Queue.Queue()
        self.cfgFile = cfgFile
        self.reportFile = reportFile
        self.telnetSession = telnetSession
        self.tnnlCount = 0
        self.cfg = [] # list of configuration parameters
        self.tunnels = {} # dictionary of tunnels
        self._readCfg()

    def _readCfg(self):
        tnnlCfgFile = open(self.cfgFile)
        csvReader = csv.reader(tnnlCfgFile)
        next(csvReader, None)
        self.cfg = [tuple(row) for row in csvReader]
        tnnlCfgFile.close()

    def _createFromCfg(self, cfg):
        fwdTnnl = reversedTnnl = ""
        assocTnnl = False

        if cfg[3] == "dynamic" and cfg[4] == "bidirectional":
            tnnlTypeStr = "rsvp-ingress-corout"
            tnnlType = TnnlType.DYNAMIC_COROUT
        elif cfg[3] == "dynamic" and cfg[4] == "unidirectional":
            tnnlType = TnnlType.DYNAMIC_UNIDIR
            tnnlTypeStr = "rsvp-ingress-unidir"
        elif cfg[3] == "static" and cfg[4] == "bidirectional":
            tnnlType = TnnlType.STATIC_COROUT
            tnnlTypeStr = "static-ingress-corout"
        elif cfg[3] == "static" and cfg[4] == "associated":
            tnnlType = TnnlType.STATIC_ASSOC
            assocTnnl = True
            tnnlTypeStr = "static-ingress-assoc"
            fwdTnnl = " forward-tunnel "
            reversedTnnl = " reverse-dyntun-name "

        tnnlCnt = int(cfg[2])
        destIP = cfg[0]
        for i in range(1, tnnlCnt+1):
            tnnlName = cfg[1] + str(i) 
            cmd = "gmpls tp-tunnel create " + tnnlTypeStr + " " + tnnlName
            if assocTnnl:
                cmd += fwdTnnl + cfg[11] + str(i) + reversedTnnl + cfg[12] + str(i)
            else:
                cmd += " dest-ip " + destIP

            if cfg[5]:
                cmd += " explicit-tunnel-path " + self.path
            if cfg[6] == "enabled":
                cmd += " auto-backup on" 
            if cfg[7] == "enabled":
                cmd += " bfd-monitor enable"
            if cfg[8]:
                cmd += " bfd-profile " + self.bfdProfile
            if cfg[9] == "enabled":
                cmd += " lsp-reopt enable lsp-reopt-interval " + cfg[10]

            result = self.telnetSession.writeCmd(cmd)
            if "FAILURE" in result:
                logging.debug(cmd)
                print(result)
            else:
                self.tnnlCount += 1
                self.tunnels[tnnlName] = [tnnlType, -1, -1, "N/A", "N/A", "N/A"]

    def _create(self):
        for cfg in self.cfg:
            if len(cfg):
                self._createFromCfg(cfg)
        globals.pvcDB.create()
        time.sleep(10)
        self.workRequestQ.put(TnnlOperation.UPDATE_LABEL)

    def create(self):
        self.workRequestQ.put(TnnlOperation.CREATE_TUNNEL)

    def _delete(self, cfg):
        if cfg[3] == "dynamic" and cfg[4] == "bidirectional":
            tnnlTypeStr = "rsvp-ingress-corout"
        elif cfg[3] == "dynamic" and cfg[4] == "unidirectional":
            tnnlTypeStr = "rsvp-ingress-unidir"
        elif cfg[3] == "static" and cfg[4] == "bidirectional":
            tnnlTypeStr = "static-ingress-corout"
        elif cfg[3] == "static" and cfg[4] == "associated":
            tnnlTypeStr = "static-ingress-assoc"
        tnnlCnt = int(cfg[2])

        for i in range(1, tnnlCnt+1):
            tnnlName = cfg[1] + str(i) 
            cmd = "gmpls tp-tunnel delete " + tnnlTypeStr + " " + tnnlName
            result = self.telnetSession.writeCmd(cmd)
            if "FAILURE" in result:
                logging.debug(cmd)
                print(result)
            else:
                if tnnlName in self.tunnels:
                    del self.tunnels[tnnlName]
                self.tnnlCount -= 1
    def _HA(self):
        cmd = "module high-avail switchover-to-standby"
        result = self.telnetSession.writeCmd(cmd)
        time.sleep(3*60)
        self.telnetSession.connect()
        while True:
            result = self.telnetSession.writeCmd("module show")
            regex = re.compile(r'CTX\s*\|\s*Enabled\s*\|\s*Enabled\s*')
            matchObj = regex.findall(result)
            if len(matchObj) == 2:
                self.workRequestQ.put(TnnlOperation.VERIFY_LABEL)
                break
            else:
                time.sleep(30)

    def HA(self):
        self.workRequestQ.put(TnnlOperation.PERFORM_HA)

    def _report(self):
        if self.reportFile is not None:
            f = open(self.reportFile, "w")
            try:
                writer = csv.writer(f)
                writer.writerow(("Tunnel", "TnnlType", "Fwd-out-lbl", "Reversed-in-lbl", "Ping", "BFD", "Lbl-Recovery"))
                for tunnel, attrs in self.tunnels.items():
                    writer.writerow((tunnel, attrs[0], attrs[1], attrs[2], attrs[3], attrs[4], attrs[5]))
            finally:
                f.close()

    def report(self):
        self.workRequestQ.put(TnnlOperation.CREATE_REPORT)
 
    def delete(self):
        for cfg in self.cfg:
            self._delete(cfg)

    def _verifyPing(self):
        exp = "1 packets transmitted, 1 packets received"
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.STATIC_ASSOC:
                cmd = "mpls ping assoc-tp-lsp " + tunnel + " count 1"
                result = self.telnetSession.writeCmd(cmd)
                if exp in result:
                    attrs[3] = "Pass"
                else:
                    attrs[3] = "Fail"

    def _verifyBFD(self):
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.STATIC_ASSOC:
                cmd = "bfd session show tunnel tp-assoc " + tunnel
                result = self.telnetSession.writeCmd(cmd)
                if "Session operationally up" in result:
                    attrs[4] = "Up"
                else:
                    attrs[4] = "Down"

    def _verifyLblRecovery(self):
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.DYNAMIC_UNIDIR:
                cmd = "gmpls tp-tunnel show rsvp-ingress-unidir " + tunnel
                result = self.telnetSession.writeCmd(cmd)
                # Extract the label from the output:
                #|Forward Out-Label                    |100001
                searchObj = re.search(r'Forward\sOut-Label\s+\|\d+', result)
                if searchObj:
                    if attrs[1] == searchObj.group(0).split('|')[1]:
                        attrs[5] = "Pass"
                    else:
                        attrs[5] = "Fail"

    def _updateLabel(self):
        for tunnel, attrs in self.tunnels.items():
            if attrs[0] == TnnlType.DYNAMIC_UNIDIR:
                cmd = "gmpls tp-tunnel show rsvp-ingress-unidir " + tunnel
                result = self.telnetSession.writeCmd(cmd)
                # Extract the label from the output:
                #|Forward Out-Label                    |100001
                searchObj = re.search(r'Forward\sOut-Label\s+\|\d+', result)
                if searchObj:
                    attrs[1] = searchObj.group(0).split('|')[1]

        # Ready to verify MPLS ping
        self.workRequestQ.put(TnnlOperation.VERIFY_PING)
        self.workRequestQ.put(TnnlOperation.VERIFY_BFD)

    def run(self):
        while 1:
            q = self.workRequestQ.get()
            if q == TnnlOperation.CREATE_TUNNEL:
                self._create()
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
