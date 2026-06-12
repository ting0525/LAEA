import requests, json
from aiottalk_plus_sip_application import AIoTtalk_plus_SIPApplication

IoTtalkServer = "140.114.77.93"
IoTtalkServerPort = "9999"

class SIPSignalingHandler(AIoTtalk_plus_SIPApplication):
    def __init__(self, sip_account):
        super().__init__()
        self.account = sip_account
    

    def iottalk_register(self, devicename, devicemodel, MAC, IDF, ODF):
        dfList = []
        dfList.append(str(IDF))
        dfList.append(str(ODF))
        params={
            "profile": {
                "d_name": str(devicename),
                "dm_name": str(devicemodel), 
                "u_name": "yb",
                "is_sim": False,
                "df_list": dfList
            }
        }
        print(params)
        body=json.dumps(params)
        headers={"Content-Type": "application/json"}
        r = requests.post("http://"+IoTtalkServer + ":" + IoTtalkServerPort + "/" +MAC, headers = headers, data = body)
        print(r.status_code)

    def run(self):
        self.iottalk_register("SIPSignalingHandler", "SIPStream", "SIPSignalingHandler", "SDPOffer-I", "SDPAnswer-O")
        self.iottalk_register("SDPParser", "SIPStream", "SDPParser", "ControlRequest-I", "SDPOffer-O")
        self.iottalk_register("SDPGenerator", "SIPStream", "SDPGenerator", "SDPAnswer-I", "ControlResponse-O")
        self.iottalk_register("RTPDevice", "SIPStream", "RTPDevice", "ControlResponse-I", "ControlRequest-O")
        self.start(register=True)
    
    
if __name__ == "__main__":

    sip_account = "devicetest1@140.114.77.83"
    SIPSignalingHandler_ = SIPSignalingHandler(sip_account)
    SIPSignalingHandler_.run()