from utils.Thread import run_in_thread
from queue import Queue
#from Smart_Contract import SmartContract
import threading
import web3
import solcx
import time
import json

class SmartContract():
    def __init__(self, solidity_file_path, solc_version):
        self.file_path = solidity_file_path
        self.solc_version = solc_version
    
        name = self.file_path.replace(".sol", "")
        name = name[name.rfind("/")+1: ]
        self.name = name

        self.abi = None
        self.bytecode = None

    def compile(self):
        self.comipled_sol = solcx.compile_files(
            [self.file_path],
            output_values=["abi", "bin"],
            solc_version=self.solc_version
        )
        contract_id, contract_interface = self.comipled_sol.popitem()
        self.abi = contract_interface["abi"]
        self.bytecode = contract_interface["bin"]
    
    def get_abi(self):
        return self.abi

    def get_bytecode(self):
        return self.bytecode
        # self.comipled_sol = compile_standard{
        #     "Language": "Solidity",
        #     "sources": {
        #         solidity_file_path: {"content": self.file}
        #     }
        #     "settings":{
        #         "outputSelection":{
        #             "*":{
        #                 "*": ["abi", "metadata", "evm.bytecode", "evm.sourceMap"]
        #             }
        #         }
        #     },
        #     solc_version = self.solc_version,
        # }
        # self.bytecode = self.comipled_sol["contracts"][self.file_path][]
    def dump_smart_contract_json_file(self):
        with open("compiled_code.json", "w") as file:
            json.dump(self.comipled_sol, file)