from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from queue import Queue
from collections import deque

import socket
import hmac
import hashlib
import threading
import multiprocessing
import time
import datetime
import json
import base64

from utils.Thread import run_in_thread
from utils.ECDH import ECDH
from utils.Socket import Server_Socket, Client_Socket
from utils.AES_Cipher import AES_Cipher
from utils.HMAC import HMAC
from blockchain_handler import BlockChain_Handler

config = {
    "key_file_folder": "BCProxy_shared_keys/"
}

class BCProxy():
    def __init__(self, name, child_pipe=None):
        self.name = name
        self.pipe = child_pipe
        self.shared_keys = {}
        self.parent_process_pipe = None
        self.thread_pool = []
        self.lock = threading.Lock()
    
    def start(self):
        
        self.AIoTtalk_ECDH_key_exchange("0.0.0.0", 9999)
        self.init_AES_cipher()
        #self.init_blockchain("0.0.0.0", 9000)
        #self.start_blockchain_handler()
        #self.blockchain_handler = BlockChain_Handler()
        #self.blockchain_handler.start()
        self.start_SUA_register_socket("0.0.0.0", 8888)
        self.start_SUA_message_socket("0.0.0.0", 7777)
        self.start_AUA_message_socket("0.0.0.0", 6666)

    def AIoTtalk_ECDH_key_exchange(self, host, port):
        AIoTtalk_ECDH_key_exchange_socket = Client_Socket(host, port, "TCP")
        AIoTtalk_ECDH_key_exchange_socket.connect()

        ecdh = ECDH()

        send_message = {"public_key": ecdh.get_public_key()}
        AIoTtalk_ECDH_key_exchange_socket.send_message(str(send_message))

        recv_message = AIoTtalk_ECDH_key_exchange_socket.receive_message()
        print("============== AIoTtalk Public Key ==============")
        print(recv_message)
        print("============== AIoTtalk Public Key ==============")

        shared_key = ecdh.generate_shared_key(
            eval(recv_message)["public_key"]
        )
        print(shared_key)
        ecdh.save_shared_key(
            config["key_file_folder"] + "AIoTtalk_shared_key.bin"
        )
        self.shared_keys["AIoTtalk"] = shared_key
        AIoTtalk_ECDH_key_exchange_socket.close()
    
    def init_AES_cipher(self):
        self.aes_cipher = AES_Cipher()
        self.aes_cipher.initialize(
            self.shared_keys["AIoTtalk"]
        )

    @run_in_thread
    def start_SUA_register_socket(self, host, port):
        print("Start SUA Register Socket!")
        register_socket = Server_Socket(host, port, "TCP")
        register_socket.bind()
        while(True):
            client_connection, client_address = register_socket.accept()
            self.SUA_register_handler(client_connection, client_address)
    
    @run_in_thread
    def start_SUA_message_socket(self, host, port):
        print("Start SUA Message Socket!")
        message_socket = Server_Socket(host, port, "TCP")
        message_socket.bind()
        while(True):
            client_connection, client_address = message_socket.accept()
            self.SUA_message_handler(client_connection, client_address)
    
    @run_in_thread
    def start_AUA_message_socket(self, host, port):
        print("Start AUA Message Socket!")
        message_socket = Server_Socket(host, port, "TCP")
        message_socket.bind()
        while(True):
            client_connection, client_address = message_socket.accept()
            print(client_connection, client_address)
            self.AUA_message_handler(client_connection, client_address)

    @run_in_thread
    def SUA_register_handler(self, connection, address):
        print("New Register Handler On Address %s" %str(address))
        device_profile = connection.recv(1024)
        recv_time = datetime.datetime.now().strftime("%H:%M")
        device_profile = eval(device_profile.decode("utf-8"))
        print("============== SUA Profile ==============")
        print(device_profile)
        print("============== SUA Profile ==============")
        
        # ECDH Key Exchange
        def ECDH_key_exchange():

            ecdh = ECDH()

            send_public_key = {"public_key": ecdh.get_public_key()}
            connection.send(
                str(send_public_key).encode("utf-8")
            )

            shared_key = ecdh.generate_shared_key(
                device_profile["public_key"]
            )
            print(shared_key)
            ecdh.save_shared_key(
                config["key_file_folder"] + device_profile["ID"] + "_shared_key.bin"
            )
            self.shared_keys[device_profile["ID"]] = shared_key

        ECDH_key_exchange()

        # Post Register Log to Blockchain
        args = [
            device_profile["ID"],
            "secret_key_" + device_profile["ID"],
            "IoTtalk_mac_" + device_profile["ID"],
            "IoTtalk_device_model_name_" + device_profile["ID"],
            "IoTtalk_device_feature_" + device_profile["ID"]
        ]
        request = {
            "smart_contract": "contract_1",
            "function": "save_device_profile",
            "function_args": args
        }
        #self.blockchain_handler.add_request(request)
        #self.blockchain_request_queue.put(request)

        '''Close Socket'''
        connection.close()
        print("Ending Registration With Device %s!" %device_profile["ID"])
    
    @run_in_thread
    def SUA_message_handler(self, connection, address):
        print("New SUA Message Handler On Address %s" %str(address))
        
        shared_key = None
        
        while(True):
            '''Receive Message From SUA'''
            message = connection.recv(10000)
            if(message):

                '''Message Receive Time'''
                recv_time = datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
            
                message = message.decode("utf-8")
                #print(message)
                message = eval(message)
                #print("============== Message ==============")
                #print(message)
                #print("============== Message ==============")
                reply_message = "Message Sending Success"
                connection.send(reply_message.encode("utf-8"))
            
                '''Receive HMAC of Message'''
                hmac = connection.recv(1024)
                hmac = hmac.decode("utf-8")
            
                '''authentication'''
                hmac_verify_result = HMAC.verify(
                    hmac, self.shared_keys[message["device_id"]], json.dumps(message)
                )
                if hmac_verify_result:
                    print("HMAC verify success!")
                else:
                    print("HMAC verify fail!")
                   
                # ---------------------------------------------------------------------
                # device_virtual_id = message["device_id"]
                # request = {
                #     "smart_contract": "contract_1",
                #     "function": "get_device_message_log",
                #     "function_args":"jtirjtritji"
                # }
                # ---------------------------------------------------------------------
            
                log_data = [
                    message["device_id"],
                    message["sequence_id"],
                    message["device_id"],
                    str(message["data"]),
                    str(recv_time)
                ]
                request = {
                    "smart_contract": "contract_1",
                    "function": "save_device_message_log",
                    "function_args": log_data
                }
                #self.blockchain_handler.add_request(request)
                #self.blockchain_request_queue.put(request)
            
                #encrypted_data = []
                #print(message["data"])
                # for value in message["data"]:
                #     encrypted_value = self.aes_cipher.encrypt(value)
                #     encrypted_data.append(encrypted_value)
                
                #encrypted_message = self.aes_cipher.encrypt(str(message))
                #connection.send(str(encrypted_message).encode("utf-8"))
                #message["data"] = encrypted_data
                encrypted_data = []
                for data_list in message["data"]:
                    encrypted_data_list = []
                    for value in data_list:
                        encrypted_value = self.aes_cipher.encrypt(value)
                        encrypted_data_list.append(encrypted_value)
                    encrypted_data.append(encrypted_data_list)

                message["data"] = encrypted_data
                connection.send(str(message).encode("utf-8"))
            else:
                print("End SUA Message Handler")
                break

        connection.close()
        pass
    
    @run_in_thread
    def AUA_message_handler(self, connection, address):

        while(True):
            message = connection.recv(10000)
            if(message):
                message = message.decode("utf-8")
                message = eval(message)
                print(message)
            # Message Receive Time
                recv_time = datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
            
            #decrypt the message
                decrypted_data = []
                for value in message["data"]:
                    decrypted_value = self.aes_cipher.decrypt(value)
                    decrypted_data.append(decrypted_value)

                #print(decrypted_data)

                # log_data = [
                #     message["device_id"],
                #     message["sequence_id"],
                #     message["device_id"],
                #     str(message["data"]),
                #     str(recv_time)
                # ]
                log_data = [
                    "test",
                    "test",
                    "test",
                    "test",
                    str(recv_time)
                ]
                request = {
                    "smart_contract": "contract_1",
                    "function": "save_device_message_log",
                    "function_args": log_data
                }
                #self.blockchain_handler.add_request(request)
            # self.blockchain_request_queue.put(request)
                message["data"] = decrypted_data
                connection.send(str(message).encode("utf-8"))
            else:
                print("End AUA Message Handler")
                break
                
        connection.close()
        pass


    def init_blockchain(self, host, port):
        self.smart_contracts = [
            "Smart_Contracts/contract_1.sol", "Smart_Contracts/contract_2.sol", "Smart_Contracts/contract_3.sol"
        ]
        self.blockchain = BlockChain(host, port)
        self.blockchain.connect()
        self.account_password = "123456"
        self.account_address = self.blockchain.create_account(self.account_password)
        for contract in self.smart_contracts:
            self.blockchain.deploly_smart_contract(
                self.account_address,
                self.account_password,
                contract,
                "0.6.0"
            )
        print("BlockChain Init Finish!")   

    @run_in_thread
    def start_blockchain_handler(self):
        self.blockchain_request_queue = Queue(maxsize=0)
        while(True):
            if(not self.blockchain_request_queue.empty()):
                request = self.blockchain_request_queue.get()
                print(request)
                self.blockchain.transact_smart_contract(
                    self.account_address,
                    request["smart_contract"],
                    request["function"],
                    request["function_args"]
                )

    def change_proxy_owner(self):
        pass

    def stop(self):
        pass

if __name__ == '__main__':

    BC = BCProxy("BCProxy")
    BC.start()

    