from enum import Enum

user = "gss"
password = "pureethernet"
iChassis = eChassis = None

class ConfigResult(Enum):
    MPLS_TUNNEL_CFG_DONE   = 1
    MPLS_PVC_CFG_DONE      = 2
    VS_CFG_DONE            = 3
    MPLS_DETACH_PVC_DONE   = 4
    MPLS_DELETE_PVC_DONE   = 5
    MPLS_TNL_LBL_UPD_DONE  = 6
    MPLS_PVC_LBL_UPD_DONE  = 7
    GRACEFULL_RESTART_DONE = 8
    PVC_PING_DONE          = 9
