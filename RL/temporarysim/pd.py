from __future__ import annotations

import numpy as np

class PDMimic:
    '''
    refer to reference q and dq and now q and dq,
    output four joint torque
    
    joint:left_hip,left_knee,right_hip,right_knee
    '''
    def __init__(self,
                 kp= 50.0,
                 kd = 5.0,
                 torque_limit = 80.0,
                 ):
            self.kp = float(kp)
            self.kd = float(kd)
            self.torque_limit = float(torque_limit)
            
    def __call__(
                self,
                q:np.ndarray,
                dq:np.ndarray,
                q_ref:np.ndarray,
                dq_ref:np.ndarray,
                ) -> np.ndarray:
        tau = self.kp * (q_ref - q) + self.kd * (dq_ref - dq)
        tau = np.clip(tau,-self.torque_limit,self.torque_limit)
        return tau.astype(np.float32)