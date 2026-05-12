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

from aiottalk_sip_application import AIoTtalk_SIPApplication
from utils.ECDH import ECDH
from utils.AES_Cipher import AES_Cipher
from utils.Socket import Server_Socket, Client_Socket
from utils.Thread import run_in_thread
from config import config

from blockchain_handler import BlockChain_Handler

from sip_message import SIPMessageApplication
from database_handler import Database_Handler


class SIPMessageReceiveHandler(AIoTtalk_SIPApplication):
    def __init__(self, username, sip_account):
        super().__init__()
        self.account = sip_account
        self.blockchain_handler = BlockChain_Handler()
        devicedbpath = str(username) + "_SIP.db"
        webdppath = "web.db"
        self.database_handler = Database_Handler(webdppath, devicedbpath)
        self.request_session = requests.Session()

    def run(self):
        self.init_aes_cipher()
        self.start(register=True)
        self.msg_parser()

    def init_aes_cipher(self):
        file_name = config["key_file_folder"] + "/BCProxy_shared_key.bin"
        with open(file_name, "rb") as key_file:
            shared_key = key_file.read()

        self.aes_cipher = AES_Cipher()
        self.aes_cipher.initialize(shared_key)
        print("AES Cipher Initialize Success!")
    
    def decryption(self, data):
        decrypted_data = []
        for value in data:
            decrypted_value = self.aes_cipher.decrypt(value)
            decrypted_data.append(decrypted_value)
        return decrypted_data
    
    #@run_in_thread
    def msg_parser(self):
        while(True):
            if not self.receive_message_queue.empty():
                message = self.receive_message_queue.get()
                message = eval(message)
                if (type(message) == str):
                    continue
                self.process(message)
                time.sleep(0.1)

    def process(self, message):
        # print(message)
        sequence_id = message["sequence_id"]
        input_device_sip_account = message["device_id"]
        input_device_data_list = message["data"]

        for data in input_device_data_list:
            decrypted_data = self.decryption(data)
            device_name = decrypted_data[0]
            device_value = decrypted_data[1]
            #target = device_name + input_device_sip_account

            device_group = None
            device_feature = None
            target = device_name + "-" + input_device_sip_account
            '''find iottalk device group mac'''
            device_list = self.database_handler.lookup_webdb("SELECT IMEI, devicegroup FROM Device")
            device_list = list(device_list)
            # print(target)
            # print(device_list)
            
            for item in device_list:
                if item[0] == target:
                    device_group = item[1].split(",")[0]
                    break
            
            if device_group == None:
                print("Error finding target device group")
                continue

            device_profile_list = self.database_handler.lookup_devicedb("SELECT IMEI, devicefeature FROM DeviceProfile")
            device_profile_list = list(device_profile_list)

            for item in device_profile_list:
                if item[0] == target:
                    device_feature = item[1]
                    break
            
            if device_feature == None:
                print("Error finding target device feature")
                continue
            
            timestamp = datetime.datetime.now().strftime("%m/%d, %H:%M:%S")
            iottalk_mac = 'SIP-' + device_group
            iottalk_feature = device_feature
            push_data = [sequence_id, device_name, device_value, input_device_sip_account, device_group, timestamp]
            # print(iottalk_mac)
            # print(iottalk_feature)
            # print(push_data)
            self.iottalk_push(push_data, iottalk_mac, iottalk_feature)

    def iottalk_push(self, push_data, iottalk_mac, iottalk_feature):
        request_headers = {
            "Content-Type": "application/json"
        }
        request_body = json.dumps({"data": push_data})
        response = self.request_session.put(
            "http://" + config["IoTtalkServer_ip"] + ":" + config["IoTtalkServer_port"] + "/" + iottalk_mac + "/" + iottalk_feature, 
            headers = request_headers,
            data = request_body
        )
        #print(response)
        if response.status_code != 200:
            print("Error in iottalk_push %s" % response.text)

if __name__ == "__main__":

    username, sip_account = [sys.argv[1], sys.argv[2]]
    SIPMessageReceiveHandler_ = SIPMessageReceiveHandler(username, sip_account)
    SIPMessageReceiveHandler_.run()