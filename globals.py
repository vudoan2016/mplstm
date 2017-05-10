import sys
import telnet
import pvc
import tunnel
import vs
user = "gss"
password = "pureethernet"
pvcCfgFile = "ingress_pvc.csv"
egressTnnlCfgFile = "egress_tunnel.csv"
vsCfgFile = "ingress_vs.csv"
ingressTnnlCfgFile = "ingress_tunnel.csv"
reportFile = "ingress_report.txt"

ingressSession = telnet.TelnetSession(sys.argv[1], user, password)
iTnnlDB = tunnel.TnnlDB(ingressTnnlCfgFile, ingressSession, reportFile)
pvcDB = pvc.PvcDB(pvcCfgFile, ingressSession)
vsDB = vs.vs(vsCfgFile, ingressSession)
