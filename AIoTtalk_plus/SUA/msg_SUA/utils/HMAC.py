import hmac
import hashlib

class HMAC():
    def __init__(self):
        pass
    
    @classmethod
    def create(self, key, message):
        _hmac = hmac.new(key, message.encode('utf-8'), hashlib.sha256).digest()
        return _hmac

    def verify(self, _hmac, key, message):
        verify_hmac = hmac.new(key, message.encode('utf-8'), hashlib.sha256).digest()
        verify_hmac = verify_hmac.hex()

        print("============== Hmac ==============")
        print(_hmac)
        print("============== Hmac ==============")
        print("============== Verify Hmac ==============")
        print(verify_hmac)
        print("============== Verify Hmac ==============")
        
        return _hmac == verify_hmac