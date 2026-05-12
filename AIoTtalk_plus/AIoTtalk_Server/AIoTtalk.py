from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from collections import deque
from queue import Queue

import multiprocessing 
import threading
import os
import sys
import time

from sipsimple.threading import ThreadManager
from sipsimple.storage import FileStorage
from sipsimple.application import SIPApplication
from sipsimple.configuration import ConfigurationManager, datatypes
from sipsimple.account import Account, AccountManager

from utils.ECDH import ECDH
from utils.Socket import Server_Socket, Client_Socket
from config import config

from SIPMessageReceiveHandler import SIPMessageReceiveHandler
from SIPMessageSendHandler import SIPMessageSendHandler
from blockchain_handler import BlockChain_Handler
from database_handler import lookupODGODF

file = "print.txt"

class AIoTtalkServer(object):
    def __init__(self, username):
        # self.sip_message_receive_handler = SIPMessageReceiveHandler(username)
        # self.sip_message_send_handler = SIPMessageSendHandler(username)

        self.recv_handler = threading.Thread(target=os.system, args = ("python3 SIPMessageReceiveHandler.py " + username + " " + sip_account, ))
        self.send_handler = threading.Thread(target=os.system, args = ("python3 SIPMessageSendHandler.py " + username + " " + sip_account, ))
        self.shared_keys = {}
        
    def run(self):
        self.BCProxy_ECDH_key_exchange()
        #self.deploy_smart_contract()

        self.recv_handler.start()
        self.send_handler.start()
    
    def add_sip_account(self, sip_account, password, sip_proxy_addr, sip_proxy_port):
        SIPApplication.storage = FileStorage("./sip_accounts")
        configuration_manager = ConfigurationManager()
        configuration_manager.start()
        account_manager = AccountManager()
        account_manager.load()
        
        if account_manager.has_account(sip_account):
            print("already has sip account: " + sip_account)
            with open(file, "a+") as f:
                f.write("already has sip account!!!!!!!!!!!!")
        else:
            try:
                new_account = Account(sip_account)
            except ValueError as e:
                print("Except value error occured!")
                exit()
            new_account.auth.password = password
            new_account.enabled = True
            '''udp or tcp 可以換'''
            new_account.sip.outbound_proxy = datatypes.SIPProxyAddress(sip_proxy_addr, sip_proxy_port, 'udp')
            new_account.save()
            print("Add sip account: " + sip_account)
        time.sleep(1.5)
    
    def BCProxy_ECDH_key_exchange(self):
        BCProxy_ECDH_key_exchange_socket = Server_Socket("0.0.0.0", 9999, "TCP")
        BCProxy_ECDH_key_exchange_socket.bind()
        BCProxy_connection, address = BCProxy_ECDH_key_exchange_socket.accept()

        ecdh = ECDH()
        send_message = {
            "public_key": ecdh.get_public_key()
        }
        print(send_message)

        recv_message = BCProxy_ECDH_key_exchange_socket.receive_message()
        print(recv_message)

        BCProxy_ECDH_key_exchange_socket.send_message(
            str(send_message)
        )
        
        shared_key = ecdh.generate_shared_key(
            eval(recv_message)["public_key"]
        )
        print("--------shared_key--------")
        print(shared_key)
        print("--------shared_key--------")
        ecdh.save_shared_key(
            config["key_file_folder"] + "BCProxy_shared_key.bin"
        )
        self.shared_keys["BCProxy"] = shared_key
        BCProxy_ECDH_key_exchange_socket.close()
    
    def deploy_smart_contract(self):
        self.blockchain_handler = BlockChain_Handler()
        self.blockchain_handler.start()
        self.blockchain_handler.deploly_smart_contract()

if __name__ == "__main__":
    
    '''見 ManagementWeb 下的 SIP_IDA.py 下的函數 loadconfiguration() 最後幾行 os.system cmd 的指令 python3 AIoTtalk.py...'''
    ''' python3 AIoTtalk.py sip_address password sip_proxy_addr sip_proxy_port username'''
    '''Ex. python3 AIoTtalk.py siptalk@140.114.77.83 123 140.114.77.84 5566 siptalk'''

    cmd, sip_account, password, sip_proxy_addr, sip_proxy_port, username = [sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]]
    
    '''username 是 sqlite 下面 database 的 username_SIP.db 的字串'''
    '''不想跑 ManagementWeb.py， 可以 database 建好後，直接指定'''
    # path =  os.path.dirname(os.getcwd())
    # print(path)
    # sys.path.append(path)
    # org_path = os.getcwd()
    # target_path = os.path.dirname(org_path)
    # print(target_path)
    # exit()
    
    if(cmd == '0'):
        AIoTtalkServer_ = AIoTtalkServer(username)
        AIoTtalkServer_.add_sip_account(sip_account, password, sip_proxy_addr, sip_proxy_port)
        AIoTtalkServer_.run()
    
    
    # SIPApplication.storage = FileStorage("./sip_accounts")
    # configuration_manager = ConfigurationManager()
    # configuration_manager.start()

    # account_manager = AccountManager()
    # #account_manager.start()
    # account_manager.load()
    
    # sip_addr = "aaacdggg@140.114.77.83"
    # sip_proxy_addr = "140.114.77.83"
    # if account_manager.has_account(sip_addr):
    #     print("has account!")
    #     pass
    # else:
    #     try:
    #         new_account = Account(sip_addr)
    #         print(new_account)
    #     except ValueError as e:
    #         print("error occured")

    #     new_account.auth.password = "123456"
    #     new_account.enabled = True
    #     new_account.sip.outbound_proxy = datatypes.SIPProxyAddress(sip_proxy_addr, 5566, 'tcp')
    #     new_account.save()
    #     print("hello")
    # import time
    # time.sleep(1)
    # AIoTtalkServer_ = AIoTtalkServer()
    # AIoTtalkServer_.run()

