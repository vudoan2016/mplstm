import sys
import traceback
import tunnel
import pvc
import vs
import telnet
import globals
import Queue
from enum import Enum

pvcCfgFile = "ingress_pvc.csv"
egressTnnlCfgFile = "egress_tunnel.csv"
egressPvcCfgFile = "egress_pvc.csv"
egressVsCfgFile = "egress_vs.csv"
vsCfgFile = "ingress_vs.csv"
ingressTnnlCfgFile = "ingress_tunnel.csv"
reportFile = "ingress_report.txt"

resultQ = Queue.Queue()
ts = iTnnlDB = pvcDB = vsDB = None
eTs = eTnnlDB = ePvcDB = eVsDB = None

def initGlobals():
    global ts, iTnnlDB, pvcDB, vsDB
    ts = telnet.TelnetSession(sys.argv[1], globals.user, globals.password)
    iTnnlDB = tunnel.TnnlDB('iTnnlDB', ingressTnnlCfgFile, ts, reportFile)
    pvcDB = pvc.PvcDB('pvcDB', pvcCfgFile, ts)
    vsDB = vs.vs('vsDB', vsCfgFile, ts)
    iTnnlDB.start()
    pvcDB.start()
    vsDB.start()

    if len(sys.argv) > 2:
        global eTs, eTnnlDB, ePvcDB, eVsDB
        eTs = telnet.TelnetSession(sys.argv[2], globals.user, globals.password)
        eTnnlDB = tunnel.TnnlDB('eTnnlDB', egressTnnlCfgFile, eTs)
        ePvcDB = pvc.PvcDB('epvcDB', egressPvcCfgFile, eTs)
        eVsDB = vs.vs('evsDB', egressVsCfgFile, eTs)
        eTnnlDB.start()
        ePvcDB.start()
        eVsDB.start()

def applyCfg():
    global ts, iTnnlDB, pvcDB, vsDB
    global eTs, eTnnlDB, ePvcDB, eVsDB

    # Create egress tunnels
    if eVsDB:
        eVsDB.create(resultQ)

        while 1:
            q = resultQ.get()
            if q == globals.CfgResult.CFG_VS_DONE:
                eTnnlDB.create(resultQ)
            elif q == globals.CfgResult.CFG_TUNNEL_DONE:
                pvcDB.create(resultQ)
            elif q == globals.CfgResult.CFG_PVC_DONE:
                break

    vsDB.create(resultQ)
    while 1:
        q = resultQ.get()
        if q == globals.CfgResult.CFG_VS_DONE:
            iTnnlDB.create(resultQ)
        elif q == globals.CfgResult.CFG_TUNNEL_DONE:
            pvcDB.create(resultQ)
        elif q == globals.CfgResult.CFG_PVC_DONE:
            break

def removeCfg():
    global ts, iTnnlDB, pvcDB, vsDB
    global eTs, eTnnlDB, ePvcDB, eVsDB

    # Create egress tunnels
    if ePvcDB:
        ePvcDB.detach(resultQ)

        while 1:
            q = resultQ.get()
            if q == globals.CfgResult.DETACH_PVC_DONE:
                ePvcDB.delete()
            elif q == globals.CfgResult.DELETE_PVC_DONE:
                eTnnlDB.delete()
                eVsDB.delete()
                break

    pvcDB.detach(resultQ)
    while 1:
        q = resultQ.get()
        if q == globals.CfgResult.DETACH_PVC_DONE:
            pvcDB.delete()
        elif q == globals.CfgResult.DELETE_PVC_DONE:
            iTnnlDB.delete()
            vsDB.delete()
            break

# Usage: python tunnel.py 10.33.10.142 [10.33.40.11]
if __name__ == "__main__":
    if len(sys.argv) < 1:
        print("Usage: python tunnel.py 10.33.10.142 [10.33.40.11]")

    initGlobals()
    applyCfg()

    while 1:
        ans = raw_input("1-HA, 2-delete, 3-report, 4-exit: ")
        if ans == "1":
            iTnnlDB.HA()
        elif ans == "2":
            removeCfg()
        elif ans == "3":
            iTnnlDB.report()
        elif ans == "4":
            ts.pe.close()
            if eTs:
                eTs.pe.close()
            sys.exit()
        
    iTnnlDB.join()
    pvcDB.join()
    vsDB.join()
    if eTnnlDB:
        eTnnlDB.join()
