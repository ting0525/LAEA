from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#import hmac
import hashlib
import time
#import multiprocessing
import base64
import json
import datetime
import threading
import sys
import base64
from utils.HMAC import HMAC
from utils.Socket import Server_Socket, Client_Socket
from utils.ECDH import ECDH
from sua_sip_application import SUA_SIPApplication

config = {
    "key_file_folder": "SUA_shared_keys/"
}
'''
message format
{
    "sequence_id":
    "device_id:
    "data":[[]]
    "time":
}
'''

class SUA(object):
    def __init__(self, sip_account):
        self.sip_account = sip_account
        self.sip_message_application = SUA_SIPApplication()
        self.shared_keys = {}
        self.register_socket = None
        self.message_socket = None
    
    def init_socket(self):
        self.register_socket = Client_Socket("0.0.0.0", 8888, "TCP")
        self.register_socket.connect()

    
    def start(self):
        self.read_profile_and_data()
        self.start_sip_message_application()
        self.init_socket()
        self.register_handler()
        self.message_socket = Client_Socket("0.0.0.0", 7777, "TCP")
        self.message_socket.connect()
        self.image_thread()
        #self.scalar_thread()
        exit()
        

    def start_sip_message_application(self):
        self.sip_message_application.start(self.sip_account, "./sip_accounts")
        self.sip_message_application.wait_for_initialization()
        self.sip_message_application.wait_for_account_registration()

    def read_profile_and_data(self):
        self.profile = {
            "ID": self.sip_account,
        }

        with open("device_msg/device1_msg.json") as data_file:
            self.scalar_data = json.load(data_file)["msg"]
        
        with open("./dog.jpg", "rb") as data_file:
            image_bytes = base64.b64encode(data_file.read())
            self.image_data = image_bytes.decode('ascii') 

    def get_blockchain_account(self):
        pass
    
    def message_format(self, device_id, sequence_id, data, time):
        message = {
            "sequence_id": sequence_id,
            "device_id": device_id,
            "data": [["sensor1", sequence_id, "deviceatest1@140.114.77.83"]],
            "time": time
        }
        return message

    def register_handler(self):
        ecdh = ECDH()
        send_public_key = ecdh.get_public_key()
        self.profile["public_key"] = send_public_key
        self.register_socket.send_message(
            str(self.profile)
        )
        
        recv_message = self.register_socket.receive_message()
        
        shared_key = ecdh.generate_shared_key(
            eval(recv_message)["public_key"]
        )
        print(shared_key)
        
        ecdh.save_shared_key(
            config["key_file_folder"] + self.profile["ID"] + "_shared_key.bin"
        )
        self.shared_keys["BCProxy"] = shared_key
        print("Ending Key Exchange With BCProxy!")
        self.register_socket.close()
        time.sleep(1)

    def encryption_handler(self, message):
        send_message = json.dumps(message)
        hmac = HMAC.create(self.shared_keys["BCProxy"], send_message)
        #print("hmac:" + str(hmac))
        hmac_string = hmac.hex()
        #print("len:" + str(len(send_message)))
        self.message_socket.send_message(send_message)
        recv_message = self.message_socket.receive_message()
        #print("============== Got Reply ==============")
        #print(recv_message)
        #print("============== Got Reply ==============")

        self.message_socket.send_message(hmac_string)
        recv_message = self.message_socket.receive_message()
        #print("============== Got Reply ==============")
        #print(recv_message)
        #print("============== Got Reply ==============")
        
        return recv_message

    def image_thread(self):
        # print(len(self.image_data))
        '''
        send data for each 4000 step size 
        '''
        step_size = 4000
        sequence_id = 0

        image_clip_data = [self.image_data[index:index+step_size] for index in range(0, len(self.image_data), step_size)]
        #print(image_clip_data)

        for i in range(3):
            for index, data in enumerate(image_clip_data):
                sequence_id = index if data != image_clip_data[-1] else -1
                #print(sequence_id)
                timestamp = datetime.datetime.now().strftime("%m/%d, %H:%M:%S")
                message = {
                    "sequence_id": str(sequence_id),
                    "device_id": self.sip_account,
                    "data": [["sensor2", data]],
                    "time": timestamp
                }

                encryption_message = self.encryption_handler(message)
                print(encryption_message)

                self.send_sip_message(encryption_message)
                time.sleep(1)
        self.message_socket.close()
    
    def scalar_thread(self):
        for message in self.scalar_data:
            message["device_id"] = self.sip_account
            timestamp = datetime.datetime.now().strftime("%m/%d, %H:%M:%S")
            message["time"] = timestamp
            
            encryption_message = self.encryption_handler(message)
            #print(encryption_message)
            self.send_sip_message(encryption_message)
            #self.send_sip_message(str(message))
            time.sleep(2)
        
        exit()
        self.message_socket.close()
    
    def send_sip_message(self, message):
        self.sip_message_application.start_send_message(
            "siptalktest@140.114.77.83", message, None
        )
    
if __name__ == "__main__":

    if (len(sys.argv)) == 2:
        sip_account = sys.argv[1]
    else:
        print("Using Default Account devicetest1@140.114.77.83")
        sip_account = "devicetest1@140.114.77.83"

    print("Using Account: " + sip_account)
    sua = SUA(sip_account)
    sua.start()