import requests, json
import threading
import time
import re
import copy
from queue import Queue, Empty

from sipsimple.core import SDPMediaStream, SDPAttribute, SDPSession, SDPConnection
from utils.Thread import run_in_thread
from utils.sdp_process import parse_sdp, generate_sdp

from flask import Flask, jsonify, request, send_file
from flask_restx import Resource, Api

app = Flask(__name__)
api = Api(app)
rtp_establisher_namespace = api.namespace('RTPEstablisher')

IoTtalk_info = {
    "IoTtalkServer": "140.114.77.93",
    "IoTtalkServerPort": "9999",
    "SDPParserMac": "SDPParser",
    "SDPParserIDF": "ControlRequest-I",
    "SDPParserODF": "SDPOffer-O",
    "SDPGeneratorMac": "SDPGenerator",
    "SDPGeneratorIDF": "SDPAnswer-I",
    "SDPGeneratorODF": "ControlResponse-O"
}

sdp_offer_queue = Queue()
sdp_answer_queue = Queue()

mapping_table = {
    "devicetest1@127.0.0.1": "RTPDevice1",
    "devicetest2@127.0.0.1": "RTPDevice2",
    "devicetest1@140.114.77.72": "RTPDevice1",
    "devicetest2@140.114.77.72": "RTPDevice2",
    # "devicetest3@140.114.77.72": "RTPDevice3",
    # "devicetest4@140.114.77.72": "RTPDevice4",
    # "devicetest5@140.114.77.72": "RTPDevice5",
    # "devicetest6@140.114.77.72": "RTPDevice6",
    # "devicetest7@140.114.77.72": "RTPDevice7",
    # "devicetest8@140.114.77.72": "RTPDevice8",
    # "devicetest9@140.114.77.72": "RTPDevice9",
}

class Session_SDP_Info(object):
    def __init__(self, sip_device_sdp, rtp_device_sdp):
        self.sip_device_sdp = sip_device_sdp
        self.rtp_device_sdp = rtp_device_sdp

class Device_Bank(object):
    def __init__(self):
        # keep the connecting relationship between the sip device and rtp device
        # sip_device_id: [rtp_device_id, session_sdp_info]
        self.mapping_table = {}
        # self.sip_device_table = {}
        # self.mapping_table = {
        #     "devicetest1@127.0.0.1": "RTPDevice1",
        #     "devicetest2@127.0.0.1": "RTPDevice2",
        # }

    def get_sip_device(self, device_sip_account):
        sip_device = self.sip_device_table.get(device_sip_account)

device_bank = Device_Bank()
device_bank_lock = threading.Lock()

def push_iottalk_data(mac, device_feature, data):
    request_body = json.dumps({"data": data})
    request_headers = {"Content-Type": "application/json"}
    response = requests.put(
        "http://" + IoTtalk_info["IoTtalkServer"] + ":" + IoTtalk_info["IoTtalkServerPort"] + "/" + mac + "/" + device_feature,
        headers=request_headers,
        data=request_body
    )
    if response.status_code != 200:
        print("IoTtalk push failed, code: {}, reason: {}".format(str(response.status_code), response.text))
        return False
    return True

@rtp_establisher_namespace.route('/mapping_table')
class MappingTable(Resource):
    def get(self):
        ''' Get the mapping table of SIP devices to RTP devices. '''
        return jsonify(mapping_table)
    
    def post(self):
        ''' Update the mapping table with a new SIP device and its corresponding RTP device. '''
        data = request.get_json()
        if not data:
            return {"error": "No JSON data provided"}, 400

        action = data.get('ACTION')
        sip_device_id = data.get('SIP_DEVICE_ID')
        rtp_device_id = data.get('RTP_DEVICE_ID')

        if not action or not sip_device_id:
            return {"error": "Missing 'action' or 'sip_device_id'"}, 400

        if action == "add":
            if not rtp_device_id:
                return {"error": "Missing 'rtp_device_id' for 'add' action"}, 400
            if sip_device_id in mapping_table:
                return {"message": f"SIP account '{sip_device_id}' is not available, it already exists in the device bank."}, 409 # 409 Conflict
                # if sip_device_id in device_bank.mapping_table:
                #     return {"message": f"SIP device '{sip_device_id}' is not available, it already exists in the device bank."}, 409 # 409 Conflict
                # else:
                #     return {"message": f"SIP device '{sip_device_id}' already exists. Use 'update' to modify."}, 409 # 409 Conflict
            mapping_table[sip_device_id] = rtp_device_id
            return {"message": f"Mapping for SIP account '{sip_device_id}' added successfully"}, 201 # 201 Created

        # elif action == "update":
        #     if not rtp_device_id:
        #         return {"error": "Missing 'rtp_device_id' for 'update' action"}, 400
        #     if sip_device_id not in mapping_table:
        #         return {"message": f"SIP device '{sip_device_id}' not found. Use 'add' to create new mapping."}, 404 # 404 Not Found
            
        #     if sip_device_id in device_bank.mapping_table:
        #         return {"message": f"SIP device '{sip_device_id}' is not available, it already exists in the device bank."}, 409 # 409 Conflict
        #     else:
        #         mapping_table[sip_device_id] = rtp_device_id
        #         return {"message": f"Mapping for SIP device '{sip_device_id}' updated successfully"}, 200

        elif action == "delete":
            if sip_device_id in mapping_table:
                del mapping_table[sip_device_id]
                # Don't know why it doesn't receive disconnect in push_sdp_sdp
                # so delete it from device bank here
                if sip_device_id in device_bank.mapping_table:
                    del(device_bank.mapping_table[sip_device_id])
                return {"message": f"Mapping for SIP device '{sip_device_id}' deleted successfully"}, 200
            else:
                return {"message": f"SIP device '{sip_device_id}' not found"}, 404

        else:
            return {"error": "Invalid 'action' specified. Must be 'add', 'update', or 'delete'."}, 400

class SDP_Parser(object):
    def __init__(self):
        self.sdp_offer_queue = Queue()
        
    def start(self):
        self.pull_sdp_offer()
        self.push_control_request()
        print("Start pull sdp offer thread")
        print("Start push control request thread")
    
    ''' pull new sdp offer from the sipsignaling handler '''
    @run_in_thread
    def pull_sdp_offer(self):
        pre_message = []
        while(True):
            response = requests.get(
                "http://" + IoTtalk_info["IoTtalkServer"] + ":" + IoTtalk_info["IoTtalkServerPort"] + "/" + IoTtalk_info["SDPParserMac"] + "/" + IoTtalk_info["SDPParserODF"]
            )
            if(response.status_code != 200):
                print("IoTtalk pull failed, status code: {}, Mac: {}, ODF: {}".format(response.status_code, IoTtalk_info["SDPParserMac"], IoTtalk_info["SDPParserODF"]))
            else:
                #print(response.text)
                content = eval(response.text)
                # print("Content")
                # print(content)
                # print(content['samples'])
                # print("Content")
                if(len(content['samples']) > 0):
                    
                    message = content['samples'][0][1]
                    # print("Message")
                    # print(message)
                    # print("Message")
                    if(message != pre_message):
                        print("pre_message not equal to message")
                        pre_message = message
                        # print("push to sdp_offer_queue")
                        self.sdp_offer_queue.put(copy.deepcopy(message))
                        #print(message)
                    
                    time.sleep(5)

            #time.sleep(5)
    
    ''' handle the sdp offer and push the control response to the rtp device '''
    @run_in_thread
    def push_control_request(self):
        while(True):
            #print("hi")
            try :
                message = self.sdp_offer_queue.get_nowait()
            except Empty:
                # print("queue is empty, waiting for new sdp offer")
                time.sleep(1)
                continue
            # if(not self.sdp_offer_queue.empty()):
            #     message = self.sdp_offer_queue.get()
            print("Got new sdp request")
            print(message)
            sip_device_id = message[0]
            sdp = message[1]

            global device_bank
            print(sdp)

            ''' if the sip device is already in the device bank, check if it is need to disconnected '''
            if sip_device_id in device_bank.mapping_table:
                ''' if the sip device is disconnected, delete the sip device from the device bank '''
                if (sdp == "terminated"):
                    rtp_device_id = device_bank.mapping_table[sip_device_id][0]
                    print("Find SIP device {} for connected RTP device {}".format(sip_device_id, rtp_device_id))
                    data = [rtp_device_id, "disconnect", sip_device_id, "None"]
                    if not push_iottalk_data(IoTtalk_info["SDPParserMac"], IoTtalk_info["SDPParserIDF"], data):
                        continue

                    #print(device_bank.sip_device_table)
                    #del(device_bank.mapping_table[sip_device_id])
                    #print("Delete the SIP device {} and RTP device for Device Bank".format(sip_device_id, rtp_device_id))
                    time.sleep(1)
                    continue
                else:
                    old_rtp_device_id = device_bank.mapping_table[sip_device_id][0]
                    print("Replacing stale SIP device {} mapping for RTP device {}".format(sip_device_id, old_rtp_device_id))
                    push_iottalk_data(IoTtalk_info["SDPParserMac"], IoTtalk_info["SDPParserIDF"], [old_rtp_device_id, "disconnect", sip_device_id, "None"])
                    del(device_bank.mapping_table[sip_device_id])

            control_request, sdp_obj = parse_sdp(sdp)
            sip_device_sdp_info = sdp_obj

            #print(control_request)
            #print(sdp_obj)
            
            ''' find the corresponding rtp device matched for the sip device '''
            if sip_device_id in mapping_table:
                rtp_device_id = mapping_table[sip_device_id]
                print("Find SIP device {} for connecting RTP device {}".format(sip_device_id, rtp_device_id))
                rtp_device_sdp_info = SDPSession.new(sip_device_sdp_info)
                session_sdp_info = Session_SDP_Info(sip_device_sdp_info, rtp_device_sdp_info)
                device_bank.mapping_table[sip_device_id] = [rtp_device_id, session_sdp_info]
                print("SIP Device {} insert into Device Bank".format(sip_device_id))

                print(device_bank.mapping_table)
                #print(sip_device_id)
                
                ''' push the control request to the rtp device '''
                data = [rtp_device_id, "connect", sip_device_id, control_request]
                if not push_iottalk_data(IoTtalk_info["SDPParserMac"], IoTtalk_info["SDPParserIDF"], data):
                    exit()

                #break
            else:
                print("Cannot find the matched RTP device for SIP device {}".format(sip_device_id))
            time.sleep(1)    

class SDP_Generator(object):
    def __init__(self):
        self.control_response_queue = Queue()

    def start(self):
        self.pull_control_response()
        self.push_sdp_answer()
        print("Start pull control response thread")
        print("Start push sdp answer thread")

    @run_in_thread
    def pull_control_response(self):
        pre_message = []
        while(True):
            response = requests.get(
                "http://" + IoTtalk_info["IoTtalkServer"] + ":" + IoTtalk_info["IoTtalkServerPort"] + "/" + IoTtalk_info["SDPGeneratorMac"] + "/" + IoTtalk_info["SDPGeneratorODF"]
            )
            if(response.status_code != 200):
                print("IoTtalk pull failed, status code: {}, Mac: {}, ODF: {}".format(response.status_code, IoTtalk_info["SDPGeneratorMac"], IoTtalk_info["SDPGeneratorODF"]))
                
            content = eval(response.text)
            if(len(content['samples']) > 0):
                message = content['samples'][0][1]
                if(message != pre_message):
                    pre_message = message
                    self.control_response_queue.put(copy.deepcopy(message))
                else:
                    continue
            time.sleep(0.05)

    @run_in_thread
    def push_sdp_answer(self):
        while(True):
            if(not self.control_response_queue.empty()):
                message = self.control_response_queue.get()
                print("Got new RTPDevice control response")
                #print(message)
                
                rtp_device_id = message[0]
                control_request = message[1]
                sip_device_id = message[2]
                params = message[3]
                
                if (control_request == "connect"):
                    if sip_device_id in device_bank.mapping_table:
                        item = device_bank.mapping_table[sip_device_id]
                        rtp_device_id = item[0]
                        session_sdp_info = item[1]
                        new_rtp_device_sdp = generate_sdp(params)
                        session_sdp_info.rtp_device_sdp = new_rtp_device_sdp
                        print("Update rtp_device_sdp for SIP Device {} and RTP Device {}".format(sip_device_id, rtp_device_id))
                        
                        ''' push sdp answer back to the sipsignaling handler'''
                        data = [sip_device_id, str(new_rtp_device_sdp).replace("\r", "")]
                        if not push_iottalk_data(IoTtalk_info["SDPGeneratorMac"], IoTtalk_info["SDPGeneratorIDF"], data):
                            exit()
                    else:
                        print("Cannot find the corresponding SIP device in the Device Bank {}".format(sip_device_id))

                elif (control_request == "disconnect"):
                    #print(device_bank.sip_device_table)
                    if sip_device_id in device_bank.mapping_table:
                        del(device_bank.mapping_table[sip_device_id])
                        print("Delete the SIP device {} and RTP device for Device Bank".format(sip_device_id, rtp_device_id))
                
                else:
                    print("unknown control request: {}".format(control_request))

            time.sleep(1)
            
        
        pass

def app_error(e):
    app.logger.error("An unhandled exception occurred: %s", str(e), exc_info=True)
    return {"error": "An internal server error occurred", "details": str(e)}, 500

if __name__ == "__main__":
    sdp_parser = SDP_Parser()
    sdp_generator = SDP_Generator()
    sdp_parser.start()
    sdp_generator.start()

    app.register_error_handler(Exception, app_error)
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=3003)
