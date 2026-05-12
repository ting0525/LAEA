#import setup_path
import airsim
import time
import numpy as np
import os
import tempfile
import pprint
import cv2
import math
 
 
client = airsim.MultirotorClient()  # connect to the AirSim simulator
client.enableApiControl(True)       # 获取控制权
client.armDisarm(True)              # 解锁
client.takeoffAsync().join()        # 第一阶段：起飞
print("taking off") 
client.moveToZAsync(-2, 1).join()   # 第二阶段：第一个参数是高度，第二个参数是向上飞的速度,

print("moving forward")
client.moveByVelocityZAsync(2, 0, -2, 40.5).join()     # 第一个参数y方向速度(初始前方后方）向前为正，向后为负。第二个参数x方向速度(初始时向右为正，向左为负)，最后一个参数是飞行时间
print("moving lefthand")
client.moveByVelocityZAsync(0, -2, -2, 66.5).join()    
print("moving backward")
client.moveByVelocityZAsync(-2, 0, -2, 40.5).join()  
print("moving righthand") 
client.moveByVelocityZAsync(0, 2, -2, 66.5).join()   

 # 悬停 2 秒钟
client.hoverAsync().join()          # 第四阶段：悬停6秒钟
time.sleep(6)
 
client.landAsync().join()           # 第五阶段：降落
client.armDisarm(False)             # 上锁
client.enableApiControl(False)
