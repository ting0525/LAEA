import asyncio
from utils.Thread import run_in_thread
from utils.Socket import Server_Socket, Client_Socket
from queue import Queue
from Smart_Contract import SmartContract

from concurrent.futures import ThreadPoolExecutor
import threading
import web3
import solcx
import time


class BlockChain_Handler():
    _instance = None
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.blockchain_ip = "127.0.0.1"
        self.blockchain_port = 10000
        self.account_address = None
        self.account_password = "123456"
        self.account_unlocked = False
        self.smart_contracts = {}
        self.request_queue = Queue()
        # self.request_socket = Server_Socket("0.0.0.0", 4000, "TCP")
        self.miner_started = False
        self.lock = threading.Lock()
        self.request_queue = Queue()
    
    def initialize(self):
        pass

    def start(self):
        self.connect()
        self.create_account()
        self.unlock_account()
        self.start_miner()
        self.deploly_smart_contract()
        #self.start_miner()
        self.run()

    def connect(self):
        self.connection = web3.HTTPProvider("http://{0}:{1}".format(self.blockchain_ip, self.blockchain_port))
        self.connection = web3.Web3(self.connection)

    def create_account(self):
        accounts = self.connection.eth.accounts
        if len(accounts) == 0:
            self.account_address = self.connection.geth.personal.new_account(
                self.account_password
            )
        else:
            self.account_address = accounts[0]
        print('Using Geth Account: %s' %self.account_address)

    def unlock_account(self):
        unlocked = self.connection.geth.personal.unlock_account(
            self.account_address, self.account_password
        )
        if(not unlocked):
            print('Can not unlock blockchain account!')

    def deploly_smart_contract(self):
        smart_contract_file = "./smart_contract/contract_1.sol"
        solc_version = "0.6.0"
        smart_contract = SmartContract(smart_contract_file, solc_version)
        smart_contract.compile()
        unlocked = self.unlock_account()
        deployed_contract = self.connection.eth.contract(
            abi = smart_contract.abi, bytecode=smart_contract.bytecode
        )

        transaction_hash = deployed_contract.constructor().transact({
            "from": self.account_address,
            "gasPrice": self.connection.to_wei('0', "ether")
        })

        print("transaction_hash:",  transaction_hash)
        #self.start_miner()
        transaction_receipt = self.connection.eth.wait_for_transaction_receipt(
            transaction_hash
        )
        print(transaction_receipt)
        #self.stop_miner()

        contract_address = transaction_receipt["contractAddress"]

        deployed_contract = self.connection.eth.contract(
            address=contract_address,
            abi=smart_contract.abi
        )

        print(smart_contract.name)
        self.smart_contracts[smart_contract.name] = deployed_contract
        print(type(deployed_contract))

        print('Finishing Deploy Smart Contract!')
    
    def get_smart_contract(self):
        pass

    def transact_smart_contract(self, smart_contract, function, function_args):
        contract = self.smart_contracts[smart_contract]
        contract_function = contract.get_function_by_name(
            function
        )

        transaction_hash = contract_function(*function_args).transact(
            {
                "from": self.account_address,
                "gasPrice": self.connection.to_wei('0', "ether")
            }
        )

        print("transaction_hash: " + str(transaction_hash))
        transaction_receipt = self.connection.eth.wait_for_transaction_receipt(
            transaction_hash
        )
        print("transaction_receipt: ", transaction_receipt)

    def start_miner(self):

        self.miner_thread = 5
        self.connection.geth.miner.start(self.miner_thread)
        print("Start Geth Miner! ")
    
    def stop_miner(self):
        self.connection.geth.miner.stop()
        print("Stop Geth Miner! ")
    
    def add_request(self, request):
        self.request_queue.put(request)
    
    @run_in_thread
    def run(self):
        self.executor = ThreadPoolExecutor(max_workers=5)
        while True:
            if not self.request_queue.empty():
                request = self.request_queue.get()
                future = self.executor.submit(self.transact_smart_contract, "contract_1", "save_device_message_log", request)

if __name__ == "__main__":
    
    # log_data = [
    #             "123",
    #             "123",
    #             "123",
    #             "123",
    #             "123"
    #         ]
    BC = BlockChain_Handler()
    # for i in range(10):
    #     BC.request_queue.put(
    #         log_data
    #     )
    # BC.start()



