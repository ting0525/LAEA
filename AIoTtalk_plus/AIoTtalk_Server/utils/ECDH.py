from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto import Random

import threading
import hmac
import hashlib
import os
import math

class ECDH():
    def __init__(self):
        self.private_key = None
        self.public_key = None
        self.shared_key = None
        self.serialized_private_key = None
        self.serialized_public_key = None
        self.generate_private_and_public_keys()
    
    def generate_shared_key(self, public_key):
        public_key = serialization.load_pem_public_key(
            public_key
        )
        shared_key = self.private_key.exchange(
            ec.ECDH(), public_key
        )
        self.shared_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"secret",
            info=b"shared_key"
        ).derive(shared_key)

        return self.shared_key

    def generate_private_and_public_keys(self):
        self.private_key = ec.generate_private_key(
            ec.SECP384R1()
        )
        self.public_key = self.private_key.public_key()
        self.serialized_private_key = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(b'testpassword')
        )
        self.serialized_public_key = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
    
    def save_shared_key(self, save_file_path):
        with open(save_file_path, "wb") as save_file:
            save_file.write(self.shared_key)

        # shared_key = HKDF(
        #     algorithm=hashes.SHA256(),
        #     length=32,
        #     salt=b"secret",
        #     info=b"shared_key"
        # ).derive(_shared_key)
        # print("============== Shared Key ==============")
        # print(shared_key)
        # print("============== Shared Key ==============")
        # with open(save_file_path, "wb") as save_file:
        #     save_file.write(shared_key)
    
    def get_public_key(self):
        return self.serialized_public_key

    def get_private_key(self):
        return self.serialized_private_key

    def get_shared_key(self):
        return self.shared_key