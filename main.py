import sys
import traceback
import logging
import globals
import chassis
import tunnel
import pvc
import vs
import telnet
import Queue
import time

pvcCfgFile = 'ingress_pvc.csv'
egressTnnlCfgFile = 'egress_tunnel.csv'
egressPvcCfgFile = 'egress_pvc.csv'
egressVsCfgFile = 'egress_vs.csv'
vsCfgFile = 'ingress_vs.csv'
ingressTnnlCfgFile = 'ingress_tunnel.csv'
connFile = 'connection.csv'
iReport = 'report.txt'

resultQ = Queue.Queue()
ts = iTnnlDB = pvcDB = vsDB = None
eTs = eTnnlDB = ePvcDB = eVsDB = None
xTs = None
iChassis = eChassis = xChassis = None

def initGlobals():
    global ts, iTnnlDB, pvcDB, vsDB, iChassis

    ts = telnet.TelnetSession(sys.argv[1], globals.user, globals.password)
    iTnnlDB = tunnel.TnnlDB('iTnnlDB', ingressTnnlCfgFile, ts)
    pvcDB = pvc.PvcDB('pvcDB', pvcCfgFile, ts)
    vsDB = vs.vs('vsDB', vsCfgFile, ts)
    iTnnlDB.start()
    pvcDB.start()
    vsDB.start()
    iChassis = chassis.Chassis('iChassis', connFile, ts, iReport)
    iChassis.start()

    if len(sys.argv) > 2:
        global eTs, eTnnlDB, ePvcDB, eVsDB, eChassis
        eTs = telnet.TelnetSession(sys.argv[2], globals.user, globals.password)
        eTnnlDB = tunnel.TnnlDB('eTnnlDB', egressTnnlCfgFile, eTs)
        ePvcDB = pvc.PvcDB('epvcDB', egressPvcCfgFile, eTs)
        eVsDB = vs.vs('evsDB', egressVsCfgFile, eTs)
        eTnnlDB.start()
        ePvcDB.start()
        eVsDB.start()
        eChassis = chassis.Chassis('eChassis', '', eTs)
        eChassis.start()
    
    if len(sys.argv) > 3:
        global xTs, xChassis
        xTs = telnet.TelnetSession(sys.argv[3], globals.user, globals.password)
        xChassis = chassis.Chassis('xChassis', '', xTs)
        xChassis.start()

def appIsUp(tnnlDB, pvcDB):
    tnnlDB.updateLabel(resultQ)
    while 1:
        q = resultQ.get()
        if q == globals.ConfigResult.MPLS_TNL_LBL_UPD_DONE:
            pvcDB.updateLabel(resultQ)
        elif q == globals.ConfigResult.MPLS_PVC_LBL_UPD_DONE:
            return True

def ConfigApp(chassis, vsDB, tnnlDB, pvcDB):
    vsDB.create(resultQ)
    while 1:
        q = resultQ.get()
        if q == globals.ConfigResult.VS_CFG_DONE:
            tnnlDB.create(resultQ)
        elif q == globals.ConfigResult.MPLS_TUNNEL_CFG_DONE:
            pvcDB.create(resultQ)
        elif q == globals.ConfigResult.MPLS_PVC_CFG_DONE:
            pvcDB.attach()
            break

    logging.debug('Finishing configuring device ' + chassis.ts.ip)

def performGR(iChassis, eChassis=None, xChassis=None):
    iChassis.gracefulRestart(resultQ, iTnnlDB, pvcDB)
    if eChassis:
        while 1:
            q = resultQ.get()
            if q == globals.ConfigResult.GRACEFULL_RESTART_DONE:
                eChassis.gracefulRestart(resultQ, eTnnlDB, ePvcDB)
                break
    
    if xChassis:
        while 1:
            q = resultQ.get()
            if q == globals.ConfigResult.GRACEFULL_RESTART_DONE:
                xChassis.gracefulRestart(resultQ, None, None)
                break

def cleanup():
    pvcDB.detach(resultQ)
    while 1:
        q = resultQ.get()
        if q == globals.ConfigResult.MPLS_DETACH_PVC_DONE:
            pvcDB.delete(resultQ)
        elif q == globals.ConfigResult.MPLS_DELETE_PVC_DONE:
            iTnnlDB.delete()
            break

    if eChassis:
        ePvcDB.detach(resultQ)
        while 1:
            q = resultQ.get()
            if q == globals.ConfigResult.MPLS_DETACH_PVC_DONE:
                ePvcDB.delete(resultQ)
            elif q == globals.ConfigResult.MPLS_DELETE_PVC_DONE:
                eTnnlDB.delete()
                break

# Usage: python tunnel.py ingress [egress] [transit] 
if __name__ == '__main__':
    if len(sys.argv) < 1:
        print('Usage: python tunnel.py ingress [egress] [transit]')

    initGlobals()
    if eChassis:
        print('Initializing device ' + eChassis.ts.ip + ' ...')
        eChassis.applyCfg()
        ConfigApp(eChassis, eVsDB, eTnnlDB, ePvcDB)
    if xChassis:
        xChassis.applyCfg()
        
    print('Initializing device ' + iChassis.ts.ip + ' ...')
    iChassis.applyCfg()
    ConfigApp(iChassis, vsDB, iTnnlDB, pvcDB)
    if appIsUp(iTnnlDB, pvcDB):
        print('Device ' + iChassis.ts.ip + ' is ready')
        logging.debug('device ' + iChassis.ts.ip + ' is ready')
        pvcDB.verifyPing()

    while 1:
        ans = raw_input('1. port-toggling\n2. lm-restart\n3. GR\n4. cleanup\n5. report\n6. exit: ')
        if ans == '1':
            iChassis.portToggle(iTnnlDB, pvcDB)
        elif ans == '2':
            iChassis.lmRestart(iTnnlDB, pvcDB)
        elif ans == '3':
            performGR(iChassis)
        elif ans == '4':
            cleanup()
        elif ans == '5':
            iChassis.report()
        elif ans == '6':
            ts.pe.close()
            if eTs:
                eTs.pe.close()
            sys.exit()
        
    iChassis.join()
    iTnnlDB.join()
    pvcDB.join()
    vsDB.join()
    if eChassis:
        eChassis.join()
        eTnnlDB.join()
        eVsDB.join()
        ePvcDB.join()
    if xChassis:
        xChassis.join()
        
