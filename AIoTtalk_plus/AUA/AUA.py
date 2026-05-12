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
from utils.HMAC import HMAC
from utils.Socket import Server_Socket, Client_Socket
from utils.ECDH import ECDH
from sip_message import SIPMessageApplication
#from utils import ECDH, HMAC
#from Socket import Client_Socket
#from blockchain import BlockChain
#from Thread import run_in_thread

# config = {
#     "key_file_folder": "SUA_shared_keys/"
# }

class AUA(object):
    def __init__(self, sip_account):
        self.sip_account = sip_account
        self.sip_message_application = SIPMessageApplication()
    
    def init_socket(self):
        self.message_socket = Client_Socket("127.0.0.1", 6666, "TCP")
        self.message_socket.connect()

    def get_blockchain_account(self):
        pass

    def start(self):
        self.init_socket()
        self.start_sip_message_application()
        self.sip_message_receive_handler()

    def start_sip_message_application(self):
        self.sip_message_application.start(self.sip_account, "./sip_accounts")
        self.sip_message_application.wait_for_initialization()
        self.sip_message_application.wait_for_account_registration()
    
    def decryption_handler(self, message):
        timestamp = datetime.datetime.now().strftime("%m/%d, %H:%M:%S")
        send_message = {
            "sequence_id": message[0],
            "device_id": message[1],
            "data": [message[2]],
            "timestamp": timestamp
        }
        print(send_message)
        send_message = str(send_message)
        self.message_socket.send_message(send_message)
        recv_message = self.message_socket.receive_message()
        #print("============== Got Reply ==============")
        #print(recv_message)
        #print("============== Got Reply ==============")
        return recv_message

    def sip_message_receive_handler(self):
        num = 0
        while(True):
            #print(self.sip_message_application.sip_message_queue.qsize())
            #time.sleep(2)
            '''if sip_message_queue is not empty'''
            if (not self.sip_message_application.sip_message_queue.empty()):
                message = self.sip_message_application.sip_message_queue.get()
                '''convert string to dict'''
                message = eval(message)
                #self.blockchain_handler.add_request(
                    
                #)
                #print(message)
                # send_message = {
                #     "data": message
                # }
                decryption_message = self.decryption_handler(message)
                num = num + 1
                print(num)
                #msg_dict = eval(decryption_message)
                #print(msg_dict[1])
                #print("-----------------decryption-----------------")
                #print(decryption_message)
                #print("-----------------decryption-----------------")

if __name__ == "__main__":
    
    if (len(sys.argv)) == 2:
        sip_account = sys.argv[1]
    else:
        print("No account")
        sip_account = "deviceatest1@140.114.77.83"
    print("Using Account: " + sip_account)
    aua = AUA(sip_account)
    aua.start()