import sys
import traceback
import logging
import globals
import chassis
import tunnel
import pvc
import telnet
import Queue
import time

pvcCfgFile = 'ingress_pvc.csv'
egressTnnlCfgFile = 'egress_tunnel.csv'
egressPvcCfgFile = 'egress_pvc.csv'
ingressTnnlCfgFile = 'ingress_tunnel.csv'
connFile = 'connection.csv'
iReport = 'report.txt'

resultQ = Queue.Queue()
ts = iTnnlDB = pvcDB = None
eTs = eTnnlDB = ePvcDB = None
xTs = None
iChassis = eChassis = xChassis = None

def initGlobals():
    global ts, iTnnlDB, pvcDB, iChassis

    ts = telnet.TelnetSession(sys.argv[1], globals.user, globals.password)
    iTnnlDB = tunnel.TnnlDB('iTnnlDB', ingressTnnlCfgFile, ts)
    pvcDB = pvc.PvcDB('pvcDB', pvcCfgFile, ts)
    iTnnlDB.start()
    pvcDB.start()
    iChassis = chassis.Chassis('iChassis', 'ingress', connFile, ts, iReport)
    iChassis.start()

    if len(sys.argv) > 2:
        global eTs, eTnnlDB, ePvcDB, eChassis
        eTs = telnet.TelnetSession(sys.argv[2], globals.user, globals.password)
        eTnnlDB = tunnel.TnnlDB('eTnnlDB', egressTnnlCfgFile, eTs)
        ePvcDB = pvc.PvcDB('epvcDB', egressPvcCfgFile, eTs)
        eTnnlDB.start()
        ePvcDB.start()
        eChassis = chassis.Chassis('eChassis', 'egress', connFile, eTs)
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

def ConfigApp(chassis, tnnlDB, pvcDB):
    while 1:
        q = resultQ.get()
        if q == globals.ConfigResult.MPLS_TUNNEL_CFG_DONE:
            pvcDB.create(resultQ, chassis)
        elif q == globals.ConfigResult.MPLS_PVC_CFG_DONE:
            pvcDB.attach(chassis)
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
    iChassis.removeCfg()
    if eChassis:
        ePvcDB.detach(resultQ)
        while 1:
            q = resultQ.get()
            if q == globals.ConfigResult.MPLS_DETACH_PVC_DONE:
                ePvcDB.delete(resultQ)
            elif q == globals.ConfigResult.MPLS_DELETE_PVC_DONE:
                eTnnlDB.delete()
                break
        eChassis.removeCfg()

# Usage: python tunnel.py ingress [egress] [transit] 
if __name__ == '__main__':
    if len(sys.argv) < 1:
        print('Usage: python tunnel.py ingress [egress] [transit]')

    initGlobals()
    if eChassis:
        print('Initializing device ' + eChassis.ts.ip + ' ...')
        eChassis.applyCfg()
        eTnnlDB.create(resultQ)
        ConfigApp(eChassis, eTnnlDB, ePvcDB)
    if xChassis:
        xChassis.applyCfg()
        
    print('Initializing device ' + iChassis.ts.ip + ' ...')
    iChassis.applyCfg()
    iTnnlDB.create(resultQ)
    ConfigApp(iChassis, iTnnlDB, pvcDB)
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
    if eChassis:
        eChassis.join()
        eTnnlDB.join()
        ePvcDB.join()
    if xChassis:
        xChassis.join()
        
