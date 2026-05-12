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

class AES_Cipher():
    def __init__(self):
        self.cipher = None
        self.encryptor = None
        self.decryptor = None
    
    def initialize(self, key):
        self.encryptor = AES.new(key, AES.MODE_ECB)
        self.decryptor = AES.new(key, AES.MODE_ECB)
        # self.cipher = Cipher(algorithms.AES(key), modes.CBC(os.urandom(16)))
        # self.encryptor = self.cipher.encryptor()
        # self.decryptor = self.cipher.decryptor()

    def encrypt(self, data):
        #print(type(data))
        #print(AES.block_size)
        # cipher_text = self.encryptor.encrypt(
        #     pad(data.encode("utf-8"), AES.block_size)
        # )
        cipher_text = self.encryptor.encrypt(
            self.padding(data).encode("utf-8")
        )
        return cipher_text

    def decrypt(self, data):
        plain_text = self.decryptor.decrypt(data)
        #print(plain_text)
        # print(AES.block_size)
        # plain_text = unpad(plain_text, AES.block_size)
        # plain_text = self.decryptor.update(data) + self.decryptor.finalize()
        plain_text = plain_text.decode("utf-8")
        return plain_text.strip('\x00')

    def padding(self, data):
        if len(data) % 16 != 0:
            data = data.ljust(
                (math.floor(len(data)/16)+1) * 16, '\0'
            )
        return data
    
if __name__ == "__main__":
    with open("./AIoTtalk_shared_keys/BCProxy_shared_key.bin", "rb") as key_file:
            shared_key = key_file.read()
    aes_cipher = AES_Cipher()
    aes_cipher.initialize(shared_key)
    text = "hello"
    x = aes_cipher.encrypt(text)
    print(x)
    y = aes_cipher.decrypt(x)
    print(y)