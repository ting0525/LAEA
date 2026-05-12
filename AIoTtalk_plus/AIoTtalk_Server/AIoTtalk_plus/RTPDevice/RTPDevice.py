import requests, json
import time
import sys
import subprocess
import threading
import os
import copy
import json
from sipsimple.core import SDPMediaStream, SDPAttribute, SDPSession, SDPConnection
from utils.Thread import run_in_thread

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
        self.is_started = False
        self.local_ip = None
        self.remote_ip = None
        self.local_port = None
        self.remote_port = None
        self.rtp_session = None
    
    def terminate_all_proc(self):
        print("Ctrl+c Killing Subprocess")

        if self.rtp_session:
            self.rtp_session.kill()
            exit()

    def start(self):
        pre_message = []
        try:
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
                        sip_device_params = message[3]
                        # print(params[0])
                        # exit()
                        #print(rtp_device_id, request, sip_device_id, params)
                        
                        if(rtp_device_id == device_id):
                            print("-------- Got control request ---------")
                            print(str(rtp_device_id) + " " + str(request) + " " + str(sip_device_id))
                            #print("params: " + str(params[0]))
            
                            if(request == "connect"):
                                try:
                                    print(sip_device_params)
                                    sip_device_ip = sip_device_params.get('origin_ip_address')
                                    session_name = sip_device_params['session_name']
                                    print("origin_ip: " + str(sip_device_ip))
                                    print("session_name: " + str(session_name))
                                    sip_device_media = sip_device_params['media']
                                    print(sip_device_media)
                                    for media in sip_device_media:
                                        ip_address = media.get('ip_address')
                                        media_type = media['media_type']
                                        direction = media.get('direction')
                                        payload_type = media.get('payload_type')
                                        port = media.get('port')
                                        print("ip_address: " + str(ip_address))
                                        print("media_type: "+ str(media_type))
                                        print("direction: " + str(direction))
                                        print("payload_type: " + str(payload_type))
                                        print("sip_device_media_port: " + str(port)) 
                                
                                except Exception as e:
                                    print(f"Got Exception: {e}")

                                rtp_device_params = self.start_rtp_session(sip_device_params)
                                if rtp_device_params is not None:
                                    self.is_started = True
                                    data = [device_id, "connect", sip_device_id, rtp_device_params]
                                    self.return_control_response(data)
                                else:
                                    print("Failed to start RTP session, skipping control response")
                                
                            elif(request == "disconnect" and self.is_started == True):
                                self.stop_rtp_session()
                                data = [device_id, "disconnect", sip_device_id, "None"]
                                self.return_control_response(data)
                                self.end()

                            elif(request != "connect" and request != "disconnect"):
                                print("Unknown control request: {}".format(request))
                            
                            else:
                                print("Startup, continue pulling control request")
                                continue
        except KeyboardInterrupt:
            self.terminate_all_proc()
                        
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

    def start_rtp_session(self, sip_device_params):
        print("start_rtp_session")
        # print("sip_device_params: ")
        # print(sip_device_params)

        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()

        '''Create Session for the RTPdevice'''
        rtp_device_params = copy.deepcopy(sip_device_params)
        rtp_device_media = rtp_device_params["media"]
        for media in rtp_device_media:
            # media["ip_address"] = "127.0.0.1"
            # media["ip_address"] = "140.114.77.72"
            media["ip_address"] = ip_address
            media["port"] = int(media["port"]) + 2
            media["direction"] = "recvonly"
        
        sip_device_params_json_str = json.dumps(sip_device_params)
        rtp_device_params_json_str = json.dumps(rtp_device_params)
        receiver_script = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../AIoTtalk_plus_Lib/example/receiver.py")
        )
        if not os.path.exists(receiver_script):
            print(f"Receiver script not found: {receiver_script}")
            return None
        try:
            self.rtp_session = subprocess.Popen([sys.executable, receiver_script, rtp_device_params_json_str, sip_device_params_json_str])
        except Exception as e:
            print(f"Failed to launch RTP receiver: {e}")
            return None
        
        #print(rtp_device_params)
        
        return rtp_device_params
        # self.rtp_session = subprocess.Popen("./ROS_RTPDevice/LidarSLAM/catkin_ws/build/rtp_device/MAIN")
        # self.rtp_session = subprocess.Popen("./ROS_RTPDevice/VisualSLAM/catkin_ws/build/rtp_device/MAIN")
        # self.rtp_session = subprocess.Popen("./AI_RTPDevice/catkin_ws/build/rtp_device/MAIN")
        # pass
    
    def stop_rtp_session(self):
        print("stop_rtp_session")
        if self.rtp_session:
            self.rtp_session.kill()
        pass
    
    def end(self):
        print("Terminating RTPDevice")
        exit()

if __name__ == "__main__":
    rtp_device = RTPDevice()
    rtp_device.start()
    
    # try:
    #     while True:
    #         time.sleep(1)
    # except KeyboardInterrupt:
    #     rtp_device.terminate_all_proc()
#     sdp = {'session_name': 'SLAMDevice', 'ip_address': {'remote_ip': '127.0.0.1', 'local_ip': '127.0.0.1'}, 'media': [{'media_type': 'pointcloud', 'port': {'remote_port': 10000, 'local_port': 10002}, 'payload_type': {98: {'codec': 'PCL', 'params': {'fields': 'xyz'}}}, 'stream_name': 'Stream name', 'direction': 'sendonly'}, {'media_type': 'audio', 'port': {'remote_port': 11000, 'local_port': 11002}, 'payload_type': {111: {'codec': 'opus', 'params': {}}}, 'direction': 'sendonly'}, {'media_type': 'pointcloud', 'port': {'remote_port': 12000, 'local_port': 12002}, 'payload_type': {98: {'codec': 'octree_compression', 'params': {}}}, 'direction': 'sendonly'}]}
#     rtp_session = subprocess.Popen(
#     ["./test"], 
#     stdin=subprocess.PIPE,
#     stdout=subprocess.PIPE, 
#     stderr=subprocess.PIPE,
#     text=True
# )

# time.sleep(2)

# stdout_line = rtp_session.stdout.readline()
# print("C++: ", stdout_line.strip())
# #exit()

# json_data = json.dumps(sdp)
# print(json_data)
# rtp_session.stdin.write(json_data + "\n")
# rtp_session.stdin.flush()

# stdout, stderr = rtp_session.communicate()
# print("output: \n", stdout)
# print("C++ Error: \n", stderr)
