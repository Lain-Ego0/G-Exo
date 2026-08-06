###通过参考步态数据学习轨迹信息

from __future__ import annotations

import numpy as np

class GaitSource:
    '''
    空接口
    '''
    
    def get(self,t) -> tuple[np.ndarray, np.ndarray,float]:
        '''
        input: t:sim time,second
        
        output:
            q_ref,shape = (4,),reference joint positions,rad
            dq_ref,shape = (4,),reference joint velocities,rad/s
            phase,range = [0,1)
        '''        
        raise NotImplementedError
    
    