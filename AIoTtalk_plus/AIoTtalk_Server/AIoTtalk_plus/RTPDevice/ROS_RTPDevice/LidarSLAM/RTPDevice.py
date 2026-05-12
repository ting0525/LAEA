import requests, json
import time
import sys
import subprocess
import threading
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'utils')))
from sipsimple.core import SDPMediaStream, SDPAttribute, SDPSession, SDPConnection

#from utils.Thread import run_in_thread

IoTtalk_info = {
    "IoTtalkServer": "140.114.77.93",
    "IoTtalkServerPort": "9999",
    "RTPDeviceMac": "RTPDevice",
    "RTPDeviceIDF": "ControlResponse-I",
    "RTPDeviceODF": "ControlRequest-O"
}

IoTtalkServer = "140.114.77.93"
IoTtalkServerPort = "9999"
mac = "RTPDevice"
device_model = "SIPStream"
input_device_feature = "ControlResponse-I"
output_device_feature = "ControlRequest-O"

device_id = "RTPDevice1"

class RTPDevice:
    def __init__(self):
        self.local_ip = None
        self.remote_ip = None
        self.local_port = None
        self.remote_port = None
        pass
    
    def start(self):
        pre_message = []
        while(True):
            response = requests.get(
                "http://" + IoTtalk_info['IoTtalkServer'] + ":" + IoTtalk_info['IoTtalkServerPort'] + "/" + IoTtalk_info['RTPDeviceMac'] + "/" + IoTtalk_info['RTPDeviceODF']
            )

            if(response.status_code != 200):
                print("IoTtalk pull failed, code: {}, reason: {}".format(response.status_code, response.text))
                continue
            
            content = eval(response.text)
            if (len(content['samples']) > 0):
                message_time = content['samples'][0][0]
                message = content['samples'][0][1]
                
                if(message != pre_message):
                    pre_message = message
                    rtp_device_id = message[0]
                    request = message[1]
                    sip_device_id = message[2]
                    params = message[3]
                    
                    #print(rtp_device_id, request, sip_device_id, params)
                    
                    if(rtp_device_id == device_id):
                        print("-------- Got control request ---------")
                        print(str(rtp_device_id) + " " + str(request) + " " + str(sip_device_id))
                        #print("params: " + str(params[0]))
        
                        if(request == "connect"):
                            try:
                                print(params)
                                global_params = params[0]
                                #print(global_params)
                                
                                stream_params = [params[i] for i in range(1, len(params))]
                                #print(stream_params)
                                # params = params[0]
                                # for param in params.items():
                                #     print(param)
                            except:
                                print("Error on get params dict")

                            self.start_rtp_session()
                            request_headers = {
                                "Content-Type": "application/json"
                            }
                            data = [device_id, "connect", sip_device_id, params]
                            self.return_control_response(data)
                            
                        elif(request == "disconnect"):
                            self.stop_rtp_session()
                            data = [device_id, "disconnect", sip_device_id, params]
                            self.return_control_response(data)
                        else:
                            print("unknown control request: {}".format(request))
                            continue
                        
    def return_control_response(self, data):
        request_headers = {
            "Content-Type": "application/json"
        }
        request_body = json.dumps({"data":data})
        response = requests.put(
            "http://" + IoTtalk_info['IoTtalkServer'] + ":" + IoTtalk_info['IoTtalkServerPort'] + "/" + IoTtalk_info['RTPDeviceMac'] + "/" + IoTtalk_info['RTPDeviceIDF'],
            headers = request_headers,
            data = request_body
        )
        if(response.status_code != 200):
            print("IoTtalk push failed, code: {},  reason: {}".format(str(response.status_code), response.text))

    def start_rtp_session(self):
        print("start_rtp_session")
        
        #self.rtp_session = subprocess.Popen("./ROS_RTPDevice/LidarSLAM/catkin_ws/build/rtp_device/MAIN")
        # self.rtp_session = subprocess.Popen("./ROS_RTPDevice/VisualSLAM/catkin_ws/build/rtp_device/MAIN")
        # self.rtp_session = subprocess.Popen("./AI_RTPDevice/catkin_ws/build/rtp_device/MAIN")
        pass
    
    def stop_rtp_session(self):
        print("stop_rtp_session")
        #self.rtp_session.kill()
        pass

if __name__ == "__main__":
    print("Hello world")
    exit()
    # rtp_device = RTPDevice()
    # rtp_device.start()
    
#     sdp = {'session_name': 'SLAMDevice', 'ip_address': {'remote_ip': '127.0.0.1', 'local_ip': '127.0.0.1'}, 'media': [{'media_type': 'pointcloud', 'port': {'remote_port': 10000, 'local_port': 10002}, 'payload_type': {98: {'codec': 'PCL', 'params': {'fields': 'xyz'}}}, 'stream_name': 'pointcloud_stream name', 'direction': 'sendonly'}]}
#     rtp_session = subprocess.Popen(
#     ["./catkin_ws/build/rtp_device/SUA_SESSION"], 
#     stdin=subprocess.PIPE,
#     #stdout=subprocess.PIPE, 
#     stderr=subprocess.PIPE,
#     text=True
# )

# time.sleep(2)
# json_data = json.dumps(sdp)
# print(sdp)


# rtp_session.stdin.write(json_data + "\n")
# rtp_session.stdin.flush()

# stderr_line = rtp_session.stderr.readline()
# print(stderr_line.strip())
# print("C++: ", stderr_line.strip())

# time.sleep(10)

# print("python continue.......")

# rtp_session.terminate()
# print("terminate process")

# json_data = json.dumps(sdp)
# print(json_data)
# rtp_session.stdin.write(json_data + "\n")
# rtp_session.stdin.flush()

# stdout, stderr = rtp_session.communicate()
# print("output: \n", stdout)
# print("C++ Error: \n", stderr)