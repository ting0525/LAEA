# -*- coding: UTF-8 -*-
#import DAN
from DAN import *
import config

IoTtalkServer = config.IoTtalkServer

class DAI:
    #ServerIP = '140.113.199.199' #Change to your IoTtalk IP or None for autoSearching
    #ServerIP = '140.113.131.100' #Change to your IoTtalk IP or None for autoSearching
    #Reg_addr = None # if None, Reg_addr = MAC address
    
    def __init__(self, ServerIP = IoTtalkServer, Reg_addr = None):
        self.ServerIP = ServerIP
        self.Reg_addr = Reg_addr
        self.DAN = DAN()
        self.state = 'SUSPEND'
        self.DfList   = []
        self.SIPDfList = []
        self.alias_check_thread = None;
        self.alias_check_thread_runing = False;
        self.alias_check_sleeptime = 2;
        #self.DAN.profile['d_name'] = 'V1_NB-IoT_UE_model'
        #print(self.DAN.profile['d_name'])
 
    def register(self, dm_name, df_list, d_name):
        self.DAN.profile['dm_name'] = dm_name
        self.DAN.profile['df_list'] = df_list
        #DAN.profile['d_name']= None # None for autoNaming
        self.DAN.profile['d_name'] = d_name # None for autoNaming
        #print(self.DAN.profile['d_name'])
        self.DAN.profile['is_sim'] = False
        self.DAN.device_registration_with_retry(self.DAN.profile, self.ServerIP, self.Reg_addr)
        self.Reg_addr = self.DAN.mac;
        self.alias_check_thread_runing = True;
        if self.alias_check_thread == None: 
            #print("self.alias_check_thread start")
            self.alias_check_thread=threading.Thread(target=self.alias_check)
            self.alias_check_thread.daemon = True
            self.alias_check_thread.start()
    
    def device_registration_with_retry(self):
        self.DAN.device_registration_with_retry(self.DAN.profile, self.ServerIP, self.Reg_addr)
        
    def pull(self, df):
        value = self.DAN.pull(df)
        self.state = self.DAN.state
        return value
    
    def push(self, df, *data):
        #print ('DAI, data', list(data))
        value = self.DAN.push (df, *data)
        self.state = self.DAN.state
        return value
    
    def get_alias(self, df):
        value = self.DAN.get_alias(df)
        return value

    def set_alias(self, df, alias_name):
        value = self.DAN.set_alias(df, alias_name)
        return value
        
    def deregister(self):
        value = self.DAN.deregister()
        return value
    
    def set_SIPDfList(self, DfList, SIPDfList):
        self.DfList   = DfList;
        self.SIPDfList = SIPDfList;
    
    def alias_check(self):
        time.sleep(5);
        while True:
            if len(self.DfList) > 0:
                if(self.DAN.state == "RESUME"):
                    time.sleep(self.alias_check_sleeptime/2);
                    setsucesscount = 0;
                    for i in range(len(self.SIPDfList)):
                        try: 
                            aliaslist = self.get_alias(self.SIPDfList[i]);
                            time.sleep(0.2);
                            setbool = False;
                            for j in range(len(aliaslist)):
                                if(aliaslist[j] != self.DfList[i]):
                                    setbool = True;
                                    break;
                                        
                            if(setbool):
                                self.set_alias(self.SIPDfList[i],self.DfList[i]);
                                time.sleep(0.2);
                                setsucesscount = setsucesscount + 1;
                            else:
                                setsucesscount = setsucesscount + 1;
                                continue;
                        except Exception as e:
                            time.sleep(2);
                    if setsucesscount == len(self.SIPDfList):
                        self.setalias_sleeptime = 120;
                    time.sleep(self.alias_check_sleeptime/2);
                elif(self.DAN.state != "RESUME"):
                    self.setalias_sleeptime = 4;
                    time.sleep(self.alias_check_sleeptime/2);
            else:
                time.sleep(60);
""" 
while True:
    try:
        #Pull data from a device feature called "Dummy_Control"
        #value1=DAN.pull('Dummy_Control')
        #print ('1')
        #if value1 != None: # if return data is null
        #    print (value1[0])

        #Push data to a device feature called "Dummy_Sensor"
        value2=random.uniform(1, 10)
        print ('2')
        DAN.push ('NB-IoT_UE_test', value2)

    except Exception as e:
        print(e)
        DAN.device_registration_with_retry(ServerIP, Reg_addr)

    time.sleep(1)
""" 
