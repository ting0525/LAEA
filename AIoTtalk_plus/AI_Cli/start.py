#!flask/bin/python
# -*- coding: UTF-8 -*-
from flask import Flask, redirect, url_for, render_template,request
#import config,json,requests,time
import socket
#from datetime import datetime
import sys, traceback
import threading
import ast
import random, uuid
import json, atexit, sys, requests, os, signal, sqlite3
import ntplib
from openpyxl import Workbook, load_workbook
from sqlalchemy.dialects.mssql.information_schema import key_constraints
from queue import Queue
from sip_application import AICli_SIPApplication

import time
import ntplib
import datetime
import copy

IoTtalkServer = "140.114.77.93"
IoTtalkServerPort = "9999"

app = Flask(__name__)

sip_application = AICli_SIPApplication()
sip_application.start("7001@140.114.77.83")
# sip_application = SIPSessionApplication("7001@140.114.77.83")
# sip_application.start()

scalar_push_queue = Queue()
scalar_long_push_queue = Queue()
media_push_queue = Queue()

def register(devicename, devicemodel, MAC, IDF, ODF):
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

def scalar_push_handler(modeladdress, IoTtalk_mac, IoTtalk_input_device_feature):
    print("start scalar push handler!")
    while(True):
        if(not scalar_push_queue.empty()):
            data = scalar_push_queue.get()
            response = requests.post("http://" + modeladdress, data = {"data":data[2]})
            print("AI model Response: " + str(response))
            print("AI model Result: " + str(response.text))
            timestamp = datetime.datetime.now().strftime("%m/%d, %H:%M:%S")
            push_data = [
                data[0],
                data[1],
                response.text,
                data[3],
                data[4],
                timestamp
            ]
            request_headers = {
                "Content-Type": "application/json"
            }
            request_body = json.dumps({"data": push_data})
            response = requests.put(
                "http://" + IoTtalkServer + ":" + IoTtalkServerPort + "/" + IoTtalk_mac + "/" + IoTtalk_input_device_feature, 
                headers = request_headers,
                data = request_body
            )
            print("IoTtalk Response: " + str(response))
            time.sleep(0.5)
            #print(response)
        pass
    
def scalar_pull_handler(modeladdress, IoTtalk_mac, IoTtalk_output_device_feature):
    pre_data = []
    print("start scalar pull handler!")
    while(True):     
        #pre_data = []
        response = requests.get(
            "http://" + IoTtalkServer + ":" + IoTtalkServerPort + "/" + IoTtalk_mac + "/" + IoTtalk_output_device_feature, 
        ) 
        #print(r.text)
        content = eval(response.text)
        #print(content["samples"])
        if (len(content["samples"]) != 0):
            data = content["samples"][0][1]
            #print(data)
            if (len(data) != 0):
                if data != pre_data:
                    print(data)
                    pre_data = data
                    scalar_push_queue.put(data)

device_img = {}

def scalar_long_push_handler(modeladdress, IoTtalk_mac, IoTtalk_input_device_feature):
    while(True):
        if(not scalar_long_push_queue.empty()):
            data = scalar_long_push_queue.get()
            response = requests.post("http://" + modeladdress +  "/detect/image", data = {"robot_id": 1,"image":data[2]})
            print("AI model Response: " + str(response))
            print("AI model Result: " + response.text)
            timestamp = datetime.datetime.now().strftime("%m/%d, %H:%M:%S")

            push_data = [
                data[0],
                data[1],
                response.text.strip(),
                data[3],
                data[4],
                timestamp
            ]
            request_headers = {
                "Content-Type": "application/json"
            }
            request_body = json.dumps({"data": push_data})
            response = requests.put(
                "http://" + IoTtalkServer + ":" + IoTtalkServerPort + "/" + IoTtalk_mac + "/" + IoTtalk_input_device_feature, 
                headers = request_headers,
                data = request_body
            )
            print("IoTtalk Response: " + str(response))
            time.sleep(0.5)
        pass


def scalar_long_pull_handler(modeladdress, IoTtalk_mac, IoTtalk_output_device_feature):
    image = ""
    pre_data = []
    while(True):     
        #pre_data = []
        response = requests.get(
            "http://" + IoTtalkServer + ":" + IoTtalkServerPort + "/" + IoTtalk_mac + "/" + IoTtalk_output_device_feature, 
        ) 
        #print(r.text)
        content = eval(response.text)
        #print(content["samples"])
        if (len(content["samples"]) != 0):
            data = content["samples"][0][1]
            #print(data)
            if (len(data) != 0):
                if data != pre_data:
                    IMEI = data[1] + "-" + data[3]
                    #print(data)
                    if IMEI not in device_img:
                        device_img[IMEI] = ""
                    device_img[IMEI] += data[2]
                    pre_data = data
                    if (int(data[0]) == -1):
                        print(len(device_img[IMEI]))
                    if(int(data[0]) == -1 and (len(device_img[IMEI]) > 20000)):
                        img = copy.deepcopy(device_img[IMEI])
                        device_img[IMEI] = ""
                        img_data = [
                            data[0],
                            data[1],
                            img,
                            data[3],
                            data[4],
                            data[5]
                        ]
                        
                        scalar_long_push_queue.put(img_data)
        time.sleep(0.01)

def media_push_handler(modeladdress, IoTtalk_mac, IoTtalk_input_device_feature):
    print("start media push handler!")
    while(True):
        if(not media_push_queue.empty()):
            push_data = media_push_queue.get()
            request_headers = {
                "Content-Type": "application/json"
            }
            request_body = json.dumps({"data": push_data})
            response = requests.put(
                "http://" + IoTtalkServer + ":" + IoTtalkServerPort + "/" + IoTtalk_mac + "/" + IoTtalk_input_device_feature, 
                headers = request_headers,
                data = request_body
            )
            print("IoTtalk Response: " + str(response))
            time.sleep(0.5)

def media_pull_handler(modeladdress, IoTtalk_mac, IoTtalk_output_device_feature):
    '''pull AI Cli sip account from IoTtalk Server'''
    print("start media pull handler!")
    while(True):
        r = requests.get(
            "http://" + IoTtalkServer + ":" + IoTtalkServerPort + "/" + IoTtalk_mac + "/" + IoTtalk_output_device_feature
        )
        while "mac_addr not found" in r.text:
            time.sleep(5)
            r = requests.get("http://" + IoTtalkServer + ":" + IoTtalkServerPort + "/" + IoTtalk_mac + "/" + IoTtalk_output_device_feature)
            print(r.text)
        #print(r.text)
        content = eval(r.text)
        if(len(content["samples"]) != 0):
            data = content["samples"][0][1]
            sip_account = data[0]
            sip_proxy = data[1]
            sip_password = data[2]
            Output_device_group = data[3]
            print("sip_account: " + sip_account)
            #options_dict["account"] = sip_account
            # target = None
            # options = set_options(options_dict)
            # sip_audio_application.start(target, options)

            while(True):
                pass
                # if(not sip_application.audio_file_queue.empty()):
                #     data = sip_application.audio_file_queue.get()
                #     record_file_path = data["file_path"]
                #     device_uri = data["device_uri"]
                #     filename_no = data["filename_no"]
                #     print("record_file_path:" + record_file_path)
                #     print("device_uri:" + device_uri)
                #     print("filename_no: " + filename_no)
                #     print("-------------------------")
                #     record_file = open(record_file_path, "rb")

                #     response = requests.post("http://" + modeladdress, files={"wav":record_file})
                #     result = response.text
                #     print("AI model Response: " + str(response))
                #     print("AI model Result: " + result)
                #     timestamp = datetime.datetime.now().strftime("%m/%d, %H:%M:%S")
                #     push_data = [
                #         filename_no,
                #         "sensor1",
                #         result,
                #         device_uri,
                #         Output_device_group,
                #         timestamp
                #     ]
                #     media_push_queue.put(push_data)


@app.route('/login', methods=['GET', 'POST'])
def start():
    if request.method == 'POST':
        modeladdress=request.form['modeladdress']
        devicename=request.form['devicename']
        devicemodel=request.form['devicemodel']
        IoTtalk_mac=request.form['MAC']
        IoTtalk_input_device_feature=request.form['IDF']
        IoTtalk_output_device_feature=request.form['ODF']
        datatype=request.form['datatype']
        register(devicename,devicemodel,IoTtalk_mac,IoTtalk_input_device_feature,IoTtalk_output_device_feature)
        
        if datatype == 'multimedia':
            media_pull_thread = threading.Thread(target = media_pull_handler, args=(modeladdress,IoTtalk_mac,IoTtalk_output_device_feature,)) 
            media_pull_thread.daemon = True
            media_pull_thread.start()
            media_push_thread = threading.Thread(target = media_push_handler, args=(modeladdress,IoTtalk_mac,IoTtalk_input_device_feature,)) 
            media_push_thread.daemon = True
            media_push_thread.start()

        elif datatype =='scalar_long' :
            scalar_long_push_thread = threading.Thread(target = scalar_long_push_handler, args=(modeladdress,IoTtalk_mac,IoTtalk_input_device_feature,)) 
            scalar_long_push_thread.daemon = True
            scalar_long_push_thread.start()
            scalar_long_pull_thread = threading.Thread(target = scalar_long_pull_handler, args=(modeladdress,IoTtalk_mac,IoTtalk_output_device_feature,))
            scalar_long_pull_thread.daemon = True
            scalar_long_pull_thread.start()
        
        elif datatype =='scalar' :
            print('scalar')
            scalar_push_thread = threading.Thread(target = scalar_push_handler, args=(modeladdress,IoTtalk_mac,IoTtalk_input_device_feature,)) 
            scalar_push_thread.daemon = True
            scalar_push_thread.start()
            scalar_pull_thread = threading.Thread(target = scalar_pull_handler, args=(modeladdress,IoTtalk_mac,IoTtalk_output_device_feature,))
            scalar_pull_thread.daemon = True
            scalar_pull_thread.start()
        
        if request.form['send']=='Register' :
            return render_template('login.html',modeladdress=modeladdress,devicename=devicename,devicemodel=devicemodel,MAC=IoTtalk_mac,IDF=IoTtalk_input_device_feature,ODF=IoTtalk_output_device_feature)

    return render_template("login.html")

if __name__ =="__main__":
    app.run(host='0.0.0.0', port = 50011)
