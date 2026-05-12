# DAI.py #coding=utf-8 -- 注意這原版 Dummy_Device 沒指定 Reg_addr 會使用 UUID (在 DAN.py內)
import time, random, requests
import DAN

#ServerURL = 'http://yourServerIP:9999'     #with non-secure connection;
ServerURL = 'https://demo.iottalk.tw' #with SSL connection 若用 IP 則無法用 https:// 
#Reg_addr = None 
Reg_addr = "AABB3388" + str( random.randint(100,999 ) )  #None #if None, Reg_addr = MAC address
##  上列原版 Reg_addr =  None # 則在 DAN.py 內會用 UUID, 這樣一部電腦只能跑一份這程式
DAN.profile['dm_name']='Dummy_Device'    ##  What are you? 你是啥東東 
DAN.profile['df_list']=['Dummy_Sensor', 'Dummy_Control',]   ##  你有哪些功能, 包括 IDF 和 ODF 
DAN.profile['d_name']= str( random.randint(1,999))+'.RealHaha'  ##  who are you? 你是誰 

DAN.device_registration_with_retry(ServerURL, Reg_addr)
#DAN.deregister()  #if you want to deregister this device, uncomment this line
#exit()            #if you want to deregister this device, uncomment this line

while True:
    try:
        IDF_data = random.uniform(1, 10)    ## 通常去讀取 sendor 的值 
        DAN.push ('Dummy_Sensor', IDF_data) #Push data to an input device feature "Dummy_Sensor"
        ## 可以 push 很長的字串, 最長可以 14950 個字 (中文英文都算一字)
        #==================================

        ODF_data = DAN.pull('Dummy_Control')#Pull data from an output device feature "Dummy_Control"
        if ODF_data != None:
            print (ODF_data[0])

    except Exception as e:
        print(e)
        if str(e).find('mac_addr not found:') != -1:
            print('Reg_addr is not found. Try to re-register...')
            DAN.device_registration_with_retry(ServerURL, Reg_addr)
        else:
            print('Connection failed due to unknow reasons.')
            time.sleep(1)    

    time.sleep(0.2)
