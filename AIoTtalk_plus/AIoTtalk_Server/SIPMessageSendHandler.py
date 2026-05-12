from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from collections import deque
from queue import Queue

import multiprocessing 

import os
import socket
import json
import datetime
import requests
import time
import subprocess
import threading
import sqlite3
import sys

from aiottalk_sip_application import AIoTtalk_SIPApplication, MessageSender
from utils.ECDH import ECDH
from utils.AES_Cipher import AES_Cipher
from utils.Socket import Server_Socket, Client_Socket
from utils.Thread import run_in_thread
from config import config

from blockchain_handler import BlockChain_Handler

from database_handler import Database_Handler


# IoTtalkServer = "140.114.77.93"
# IoTtalkServerPort = "9999"

#IoTtalk_input_device_feature = "RoadAvgSpeed-I"
#IoTtalk_output_device_feature = "PredictedSpeed-O"

# IoTtalk_input_device_feature = "Image-I"
# IoTtalk_output_device_feature = "Image-O"

# IoTtalk_input_device_feature = "AudioSession-I"
# IoTtalk_output_device_feature = "ClipDetect-O"

#IDG = "ScalarG1"
#ODG = "ScalarG2"

# IDG = "ScalarLongG1"
# ODG = "ScalarLongG2"

# IDG = "AudioG1"
# ODG = "AudioG2"

# IoTtalk_input_mac = "SIP-" + IDG
# IoTtalk_output_mac = "SIP-" + ODG

class SIPMessageSendHandler(AIoTtalk_SIPApplication):
    def __init__(self, username, sip_account):
        super().__init__()
        self.account = sip_account
        self.blockchain_handler = BlockChain_Handler()
        devicedbpath = str(username) + "_SIP.db"
        webdppath = "web.db"
        self.database_handler = Database_Handler(webdppath, devicedbpath)
        self.request_session = requests.Session()
        self.iottalk_pull_queue = Queue()
    
    def run(self):
        self.init_aes_cipher()
        self.start()
        time.sleep(3)
        
        self.ODG, self.ODF = self.database_handler.get_ODG_ODF()

        self.iottalk_pull()
        self.msg_parser()

    def init_aes_cipher(self):
        file_name = config["key_file_folder"] + "/BCProxy_shared_key.bin"
        with open(file_name, "rb") as key_file:
            shared_key = key_file.read()

        self.aes_cipher = AES_Cipher()
        self.aes_cipher.initialize(shared_key)
        print("AES Cipher Initialize Success!")
    
    def encryption(self, data):
        encrypted_data = []
        for value in data:
            encrypted_value = self.aes_cipher.encrypt(value)
            encrypted_data.append(encrypted_value)
        return encrypted_data
    
    #@run_in_thread
    def msg_parser(self):
        while(True):
            if not self.iottalk_pull_queue.empty():
                message = self.iottalk_pull_queue.get()
                self.process(message)
                
    
    def process(self, message):
        from_IMEI = message[1] + "-" + message[3]
        data = message[2]
        encrypted_data = self.encryption([data])
        send_message = [
            message[0],
            from_IMEI,
            encrypted_data[0]
        ]
        # send_message = from_IMEI + ":" + message[2]
        # encrypted_data = self.encryption([send_message])

        #print(send_message)
        device_list = self.database_handler.lookup_webdb("SELECT IMEI, devicegroup FROM Device")
        device_list = list(device_list)
        
        # find target device IMEI in ODG
        target_devices = []
        for item in device_list:
            IMEI, device_group = item[0], item[1]
            if device_group == self.ODG + ',':
                target_devices.append(IMEI)
        
        #find target device sip account in IMEI
        AUA_devices = []
        for IMEI in target_devices:
            AUA = IMEI.split("-")[1]
            AUA_devices.append(AUA)
        print(AUA_devices)

        self.send_sip_message(AUA_devices, str(send_message))
    
    def send_sip_message(self, AUA_devices, send_message):
        for device in AUA_devices:
            message_sender = MessageSender(
                self.account, device, send_message
            )
            message_sender.start()
            del(message_sender)

    @run_in_thread
    def iottalk_pull(self):
        IoTtalk_output_mac = "SIP-" + self.ODG
        IoTtalk_output_device_feature = self.ODF
        # IoTtalk_output_mac, IoTtalk_output_device_feature = self.database_handler.get_ODG_ODF()
        # IoTtalk_output_mac = "SIP-" + IoTtalk_output_mac
        pre_msg = []
        while(True):
            response = self.request_session.get(
                "http://" + config["IoTtalkServer_ip"] + ":" + config["IoTtalkServer_port"] + "/" + IoTtalk_output_mac + "/" + IoTtalk_output_device_feature, 
            )
            while("mac_addr not found" in response.text):
                time.sleep(5)
                response = self.request_session.get(
                    "http://" + config["IoTtalkServer_ip"] + ":" + config["IoTtalkServer_port"] + "/" + IoTtalk_output_mac + "/" + IoTtalk_output_device_feature,
                )
                print("SIPMessageSendHandler: " + response.text)
                #print(response.text)

            if response.status_code != 200:
                print(response.text)
            #print(response.status_code)

            content = eval(response.text)
            #print(content)
            if (len(content["samples"]) != 0):
                msg = content["samples"][0][1]
                #print(msg)
                
                if (len(msg) != 0):
                    if msg != pre_msg:
                        pre_msg = msg
                        self.iottalk_pull_queue.put(msg)
            
            time.sleep(0.01)

if __name__ == "__main__":

    username, sip_account = [sys.argv[1], sys.argv[2]]
    SIPMessageSendHandler_ = SIPMessageSendHandler(username, sip_account)
    SIPMessageSendHandler_.run()