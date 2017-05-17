from enum import Enum

user = "gss"
password = "pureethernet"

class CfgResult(Enum):
    CFG_VS_DONE      = 1
    CFG_PVC_DONE     = 2
    CFG_TUNNEL_DONE  = 3
    DETACH_PVC_DONE  = 4
    DELETE_PVC_DONE  = 5
     


