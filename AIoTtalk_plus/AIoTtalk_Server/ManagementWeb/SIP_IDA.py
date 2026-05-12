# -*- coding: UTF-8 -*-
# python 2.7
# coding: UTF-8	#兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯
import socket
import time
from datetime import datetime
import sys, traceback
import threading
import ast
import time, requests, random, uuid
import json, atexit, sys, requests, os, signal, sqlite3
import config
import ntplib
from openpyxl import Workbook, load_workbook

from DAI import *
from sqlalchemy.dialects.mssql.information_schema import key_constraints

global dbpath
dbpath = ""
global ExecutionState
ExecutionState = "Success"
IoTtalkServer = config.IoTtalkServer

moni_dbpath = "./sqlite/MonitorHistory.db"

class JSONObject:
	def __init__(self, d):
		self.__dict__ = d

def loadconfiguration():
	#讀取登入資訊的檔案SIP的帳號、密碼和Proxy
	global SIPAccount, SIPPassword, Domain, SIPProxy, SIPProxyPort;
	global sip_address, sip_proxy
	global Iottalk_dev_name;
	global username;
	global Provider;
	global dbpath;
	
	Iottalk_dev_name = "";
	
	dbpath = "./sqlite/" + username + "_"+ Provider +".db";
	webdbpath = "./sqlite/web.db";

	db = sqlite3.connect(dbpath);
	try:
		# 新增table和column
		create_tb_cmd="CREATE TABLE IF NOT EXISTS DeviceTypeMapping (DeviceName TEXT,DeviceType TEXT,FeatureCount INT,Feature TEXT)"
		# 主要就是上面的语句
		db.execute(create_tb_cmd)
		
		create_tb_cmd="CREATE TABLE IF NOT EXISTS DeviceFeatureMapping (Feature TEXT,ServiceName TEXT,Dimension INT,DataType TEXT,OldServiceName TEXT,DeviceName TEXT)"
		# 主要就是上面的语句
		db.execute(create_tb_cmd)

	except:
		# print("Create table failed")
		traceback.print_exc(file=open('debug.txt','a+'))
		db.close()

	Accountdb = sqlite3.connect(webdbpath)
	reslisttmp = Accountdb.execute("SELECT SIPAccount, SIPPassword, Domain, SIPProxy, SIPProxyPort, PSProxy, PSProxyPort FROM service_provider WHERE username = '"+username+"' AND Provider = 'SIP'")
	reslist = list(reslisttmp)
	Accountdb.close()
	for res in reslist:
		SIPAccount = res[0]
		SIPPassword = int(res[1])
		Domain = res[2]
		SIPProxy = res[3]
		SIPProxyPort = int(res[4])
	
	sip_address = SIPAccount+"@"+Domain
	#sip_proxy = SIPProxy+":"+str(SIPProxyPort)
	sip_proxy_addr = SIPProxy
	sip_proxy_port = SIPProxyPort
	# [SOCKET] 1. sent to SIPHandler.py, and trigger it 
	
	# 0 siptalk@140.114.77.84 123123 140.114.77.73:5566
	# modify
	#socket_content = "0 " + sip_address + " " + str(SIPPassword) + " " + sip_proxy
	socket_content = "0 " + sip_address + " " + str(SIPPassword) + " " + sip_proxy_addr + " " + str(sip_proxy_port)
	org_path = os.getcwd()
	target_path = os.path.dirname(org_path)
	
	#os.chdir(target_path)

	# cmd = "python3 " + "AIoTtalk.py" + " " + socket_content + " " + username
	# import subprocess
	# subprocess.run(
	# 	["python3", "AIoTtalk.py", "0", sip_address, str(SIPPassword), sip_proxy_addr, str(sip_proxy_port), username], 
	# 	cwd=target_path, 
	# 	shell=False
	# )
	# os.system(cmd)
	# os.chdir(org_path)
	#cmd = "python SIPHandler.py " + socket_content + " " + username
	#os.system(cmd)

def loadDeviceProfile():
	dbpath = "./sqlite/" + username + "_" + Provider + ".db"
	devicedb = sqlite3.connect(dbpath)
	deviceprofileList = devicedb.execute("SELECT IMEI, devicemodeltype, devicemodel, devicefeaturetype, devicefeature, dim, datatype, attr FROM DeviceProfile")
	deviceprofileList = list(deviceprofileList)
	#with open('devprofile.txt', "a+") as f:
	#	f.write("deviceprofileList: %s\n" % deviceprofileList)

	devicedb.commit()

	for item in deviceprofileList:
	##>>
		#print("jtrirtjritjritjerieetjerotjioerjtioerjtioejtoij")
		devicedb = sqlite3.connect(dbpath)
		if item[1] not in DeviceModelList.keys(): # item[1]為devicemodeltype
			DeviceModelList[item[1]] = {}
			DeviceModelList[item[1]]["DeviceList"] = []
			DeviceModelList[item[1]]["SIPDfList"] = [] # ps service
			DeviceModelList[item[1]]["DfList"] = []

			if (item[2] != None): # item[1]為devicemodeltype
				deviceretypecontent = devicedb.execute(
					"SELECT DeviceName, FeatureCount, Feature FROM DeviceTypeMapping WHERE DeviceType = '" + item[1] + "'")
				deviceretypecontent = list(deviceretypecontent)
				if (len(deviceretypecontent) == 0):
					devicedb.execute(
						"INSERT INTO DeviceTypeMapping (DeviceName, DeviceType) VALUES ('" + item[2] + "','" + item[1] + "')")
					DeviceModelList[item[1]]["DeviceModel"] = item[2]
				else:
					if (deviceretypecontent[0][0] != ""):
						DeviceModelList[item[1]]["DeviceModel"] = deviceretypecontent[0][0]
			else:
				deviceretypecontent = devicedb.execute(
						"INSERT INTO DeviceTypeMapping (DeviceName, DeviceType) VALUES ('" + item[2] + "','" + item[1] + "')")
				deviceretypecontent = list(deviceretypecontent)
				if (len(deviceretypecontent) > 0):
					if (deviceretypecontent[0][0] != ""):
						DeviceModelList[item[1]]["DeviceModel"] = deviceretypecontent[0][0]
				else:
					devicedb.execute(
						"INSERT INTO DeviceTypeMapping (DeviceName, DeviceType) VALUES ('" + item[2] + "','" + item[1] + "')")
					
			devicedb.commit()
			DeviceModelList[item[1]]["DeviceList"].append(item[0]) # item[0]為IMEI
			#print("jkjkjkjkjkjkjkjkj")
			## 紀錄devicefeature的部分
			## 目前一個DM先暫時只有一個DF
			if (item[3] != None): # item[3]為devicefeaturetype
				FeatureTotalstr = ""
				FeatureCount = 0
				FeatureInfo = {}

				DeviceFeatureMapping = devicedb.execute("SELECT Feature, ServiceName FROM DeviceFeatureMapping WHERE Feature = '"+item[3]+"'")
				DeviceFeatureMapping = list(DeviceFeatureMapping)
				if(len(DeviceFeatureMapping) > 0):
					item[4] = DeviceFeatureMapping[0][1] # item[4]為devicefeature
				else:
					if (item[4] == None):
						item[4] = item[3]
				
				if item[4] not in DeviceModelList[item[1]]["DfList"]:
					if DeviceFeaturealaismap.get(item[3]) ==None:
						DeviceFeaturealaismap[item[3]]={}
						DeviceFeaturealaismap[item[3]]=item[4]
					
					DeviceModelList[item[1]]["DfList"].append(item[4])
				
					FeatureTotalstr = FeatureTotalstr + item[3] + ","
					FeatureCount = FeatureCount + 1
					FeatureInfo["Feature"] = item[3]
					FeatureInfo["ServiceName"] = item[4]
					FeatureInfo["Dimension"] = item[5]
					FeatureInfo["DataType"] = item[6]
					
					DeviceFeatureMapping = devicedb.execute("SELECT Feature FROM DeviceFeatureMapping WHERE Feature = '"+FeatureInfo["Feature"]+"'")
					DeviceFeatureMapping = list(DeviceFeatureMapping)

					if(len(DeviceFeatureMapping) == 0):
						devicedb.execute("INSERT INTO DeviceFeatureMapping (Feature, ServiceName, Dimension, DataType) VALUES ('"+FeatureInfo["Feature"]+"', '"+FeatureInfo["ServiceName"]+"', '"+ str(FeatureInfo["Dimension"]) +"', '"+FeatureInfo["DataType"]+"')")
				
				# SIPDevStatus-I 直接在這加入
				# 要多判斷此device是input or output
				if "SIPDevStatus-I" not in DeviceModelList[item[1]]["DfList"] and item[7] == 'I':
					DeviceModelList[item[1]]["DfList"].append("SIPDevStatus-I")
					
				# SIPDevStatus-O 直接在這加入
				# 要多判斷此device是input or output
				if "SIPDevStatus-I" not in DeviceModelList[item[1]]["DfList"] and item[7] == 'O':
					DeviceModelList[item[1]]["DfList"].append("SIPDevStatus-O")
				
				deviceretypecontent = devicedb.execute("SELECT DeviceName, FeatureCount, Feature FROM DeviceTypeMapping WHERE DeviceType = '" + item[1]+"'")
				deviceretypecontent = list(deviceretypecontent)
				if(len(deviceretypecontent) > 0):
					devicedb.execute("UPDATE DeviceTypeMapping SET FeatureCount = "+ str(FeatureCount) +", Feature = '" + FeatureTotalstr + "' WHERE DeviceType = '" + item[1] + "'")
					DeviceModelList[item[1]]["DeviceModel"]=deviceretypecontent[0][0]
				
				devicedb.commit()
			else:
				deviceretypecontent = devicedb.execute("SELECT DeviceName, FeatureCount, Feature FROM DeviceTypeMapping WHERE DeviceType = '" + item[1] + "'")
				deviceretypecontent = list(deviceretypecontent)
				if(len(deviceretypecontent) > 0 and deviceretypecontent[0][1] != None):
					Featurestr = deviceretypecontent[0][2]
					Featurestr = Featurestr.strip()#清除換行符號
					Featurestr = Featurestr.replace(" ", "")#清除空白符號
					Featurestrlist = Featurestr.split(",") # 用,分割str字符串，并保存到列表
					for i in range(0,deviceretypecontent[0][1]):
						servicedb = sqlite3.connect(dbpath)
						servicereslisttmp = servicedb.execute("SELECT ServiceName, DataType, Dimension, Feature FROM DeviceFeatureMapping WHERE Feature = '"+Featurestrlist[i]+"'")
						servicereslist = list(servicereslisttmp)
						servicedb.close()
						for serviceres in servicereslist:
							if serviceres[0] not in DeviceModelList[item[1]]["DfList"]:
								if DeviceFeaturealaismap.get(serviceres[3]) ==None:
									DeviceFeaturealaismap[serviceres[3]]={}
									DeviceFeaturealaismap[serviceres[3]]=serviceres[0]
								DeviceModelList[item[1]]["DfList"].append(serviceres[0])
		else:
			#with open('devprofile.txt', "a+") as f:
				#f.write("devicemodel is in DeviceModelList.keys()\n")
			if(item[0] not in DeviceModelList[item[1]]["DeviceList"]):
				DeviceModelList[item[1]]["DeviceList"].append(item[0])

		#with open('devprofile.txt', "a+") as f:
		#	f.write("DeviceModelList = %s\n" % DeviceModelList)

		if item[0] not in AllDeviceList.keys():
			#with open('devprofile.txt', "a+") as f:
			#	f.write("if devprofile not in AllDeviceList.keys():\n")
			AllDeviceList[item[0]]={}
			timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
			AllDeviceList[item[0]]["TIME"] = timestamp
			
		if (item[3] != None):
			#with open('devprofile.txt', "a+") as f:
			#	f.write("if devprofile get df != None)\n")

			AllDeviceList[item[0]][item[4]] = '[23.0, 121.0]' #預設value

		needsub = True
		devicedb.close()
	##<<

		
def parse_SIPProxyAddress(type, value):
	# 轉換SIP proxy address為正確型態
	# print type = <class 'sipsimple.configuration.datatypes.SIPProxyAddress'>
	return type.from_description(value)

def register_PIPE():
	global ExecutionState;
	global DeviceModelList;
	global DeviceGroupList;
	global Iottalk_devlist;
	global exitbool;

	with open('print.txt', "a+") as f:
		f.write("register_PIPE start\n")
	
	count = 0
	while True:
		command = ""
		pipeinfo ={}
		#with open('print.txt', "a+") as f:
		#	f.write("%d\n" % count)
		
		try:
			#with open('debug.txt', "a+") as f:
			#	f.write("test4\n")
			command = json.loads(input())
			#with open("print.txt", 'a+') as f:
			#	f.write("ffffff Registerkkkkkkkk")
			#with open('debug.txt', "a+") as f:
			#	f.write("command is %s\n" % command)
			if(command["state"] == "DeviceList"):
				with open('print.txt', "a+") as f:
					f.write("state is DeviceList\n")
				pipeinfo["state"] = command["state"];
				#pipeinfo["result"] = dict(DeviceModelList)
				pipeinfo["result"] = DeviceModelList.copy()
				print(json.dumps(pipeinfo))
				sys.stdout.flush()
			elif(command["state"] == "ExecutionState"):
				with open('print.txt', "a+") as f:
					f.write("state is ExecutionState\n")
				pipeinfo["state"] = command["state"];
				pipeinfo["result"] = ExecutionState;
				print (json.dumps(pipeinfo))
				sys.stdout.flush()
			elif(command["state"] == "UpdateModelName"):
				with open('print.txt', "a+") as f:
					f.write("state is UpdateModelName\n")
				pipeinfo["state"] = command["state"];
				updatemodelname();
				#pipeinfo["result"] = ExecutionState;
				print (json.dumps(pipeinfo))
				sys.stdout.flush()
			elif(command["state"] == "UpdateFeatureName"):
				with open('print.txt', "a+") as f:
					f.write("state is UpdateFeatureName\n")
				pipeinfo["state"] = command["state"];
				updatefeaturename();
				#pipeinfo["result"] = ExecutionState;
				print (json.dumps(pipeinfo))
				sys.stdout.flush()
			elif(command["state"] == "Exit"):
				with open('print.txt', "a+") as f:
					f.write("state is Exit\n")
				pipeinfo["state"] = command["state"];
				exit();
				pipeinfo["result"] = "The IDA has been disconnected"
				print (json.dumps(pipeinfo))
				sys.stdout.flush()
				exitbool = True;
			elif(command["state"] == "Deregister"):
				with open('print.txt', "a+") as f:
					f.write("state is Deregister\n")
				pipeinfo["state"] = command["state"];
				if (command["result"]["DeviceGroup"]+command["result"]["DeviceModel"]) in Iottalk_devlist.keys():
					try:
						
						Iottalk_devlist[command["result"]["DeviceGroup"]+command["result"]["DeviceModel"]]["Iottalk_dev"].deregister();
					except Exception as e:
						stre = str(e);
						traceback.print_exc(file=open('debug.txt','a+'))
					pipeinfo["result"] = "Iottalk_devlist[" +Iottalk_devlist[command["result"]["DeviceGroup"]+command["result"]["DeviceModel"]]["Iottalk_dev"].DAN.profile['d_name'] +"].deregister()";
					del Iottalk_devlist[command["result"]["DeviceGroup"]+command["result"]["DeviceModel"]];
					del DeviceGroupList[command["result"]["DeviceGroup"]+command["result"]["DeviceModel"]];
				else:
					pipeinfo["result"] = "Iottalk_dev has not been register";
				print (json.dumps(pipeinfo))
				sys.stdout.flush()
			elif(command["state"] == "Register"):
				with open('print.txt', "a+") as f:
					f.write("state is Register\n")
				#print(json.dumps("Reg 1 "), flush=True)
				devicedb = sqlite3.connect(dbpath)
				deviceretypecontent = devicedb.execute("SELECT DeviceName,DeviceType,FeatureCount,Feature FROM DeviceTypeMapping")
				deviceretypecontent = list(deviceretypecontent);
				devicedb.close();
				#print(json.dumps("Reg 2 "), flush=True)
				#print(json.dumps(DeviceModelList), flush=True)
				for deviceretype in deviceretypecontent:
					if(deviceretype[2] != None):
						#print(json.dumps("Reg 21 = ", deviceretype[1]), flush=True)
						if DeviceModelList.get(deviceretype[1]) != None:
							DeviceModelList[deviceretype[1]]["DeviceModel"]=deviceretype[0];
				pipeinfo["state"] = command["state"];

				if(command["result"]["DeviceModel"] == "SIP"):
					DeviceGroupList["SIP"] = DeviceModelList.copy()
				else:
					DeviceModeltmp= {};
					DeviceModeltmp["DeviceList"] =list(command["result"]["DeviceList"]);
					DeviceModeltmp["SIPDfList"]=[];
					DeviceModeltmp["DfList"]=[];
					DeviceModeltmp["DeviceModel"]=command["result"]["DeviceModel"];
					DeviceModeltmp["DeviceGroup"]=command["result"]["DeviceGroup"];
					DeviceModeltmp["RegisterModel"] = command["result"]["RegisterModel"];
					DeviceModeltmp["Iottalk_dev"]=None;
					DeviceModeltmp["Lat"]=command["result"]["Lat"];
					DeviceModeltmp["Lng"]=command["result"]["Lng"];
					
					for key,val in DeviceModelList.items():
						if(val.get("DeviceModel") != None):
							if(DeviceModeltmp["DeviceModel"]== val["DeviceModel"] ):
								DeviceModeltmp["DfList"]=list(val['DfList']);
								DeviceModeltmp["SIPDfList"]=list(val['SIPDfList']);
					#DeviceGroupList[command["result"]["DeviceGroup"]+command["result"]["DeviceModel"]] = dict(DeviceModeltmp)
					DeviceGroupList[command["result"]["DeviceGroup"]+command["result"]["DeviceModel"]] = DeviceModeltmp.copy()
					#print(json.dumps(dict(DeviceModeltmp)), flush=True)
				with open('print.txt', "a+") as f:
					f.write("DeviceGroupList: %s\n" % DeviceGroupList)
				with open('print.txt', "a+") as f:
					f.write("IoTtalk_devlist: %s\n" % Iottalk_devlist)
				for k,v in DeviceGroupList.items():
					if(k == "SIP"):
						for k2,v2 in v.items():
							with open('print.txt', "a+") as f:
								f.write("k2: %s / v2: %s\n" % (k2,v2))
							if k2 not in Iottalk_devlist.keys():
								Iottalk_devlist[k2]={"DeviceModel": k,"DeviceGroup": v2["DeviceModel"] ,"Iottalk_dev":None};
								Iottalk_devlist[k2]["RegisterModel"] = v2["RegisterModel"];
								Iottalk_devlist[k2]["DeviceList"] = list(v2['DeviceList']);
								Iottalk_devlist[k2]["DfList"]=list(v2['DfList']);
								Iottalk_devlist[k2]["SIPDfList"]=list(v2['SIPDfList']);
								Iottalk_devlist[k2]["Lat"]=command["result"]["Lat"];
								Iottalk_devlist[k2]["Lng"]=command["result"]["Lng"];
							else:
								Iottalk_devlist[k2+command["result"]["DeviceModel"]]["DeviceList"] = list(v2['DeviceList']);
								Iottalk_devlist[k2+command["result"]["DeviceModel"]]["Lat"]=command["result"]["Lat"];
								Iottalk_devlist[k2+command["result"]["DeviceModel"]]["Lng"]=command["result"]["Lng"];
					else:
						if k not in Iottalk_devlist.keys():
							Iottalk_devlist[k]={"DeviceModel": v["DeviceModel"],"DeviceGroup": v["DeviceGroup"] ,"Iottalk_dev":None};
							Iottalk_devlist[k]["RegisterModel"] = v["RegisterModel"];
							Iottalk_devlist[k]["DeviceList"] = list(v['DeviceList']);
							Iottalk_devlist[k]["DfList"]= list(v['DfList']);
							Iottalk_devlist[k]["SIPDfList"]=list(v['SIPDfList']);
							Iottalk_devlist[k]["Lat"]=v['Lat'];
							Iottalk_devlist[k]["Lng"]=v['Lng'];
						else:
							Iottalk_devlist[k]["DeviceList"] = list(v['DeviceList']);
							Iottalk_devlist[k]["Lat"]=v['Lat'];
							Iottalk_devlist[k]["Lng"]=v['Lng'];
				
				#print ("Iottalk_devlist = ", Iottalk_devlist);
				#sys.stdout.flush();
				State = register();
				pipeinfo["result"] = State;
				print (json.dumps(pipeinfo))
				sys.stdout.flush()
			else:
				with open('debug.txt', "a+") as f:
					f.write("state is not on code. %s\n" % command['state'])
		except EOFError as e:
			#print(json.dumps(e), flush=True)
			time.sleep(1);
			traceback.print_exc(file=open('debug.txt','a+'))
			continue # no more input
		except Exception as e:
			#stre = str(e)
			traceback.print_exc(file=open('debug.txt','a+'))
			continue
			#print(json.dumps(e), flush=True)
			#print ("register_PIPE Error:", e);
			#sys.stdout.flush();		
		time.sleep(0.5);

def updatemodelname():
	global Iottalk_devlist
	global DeviceGroupList,DeviceModelList
	
	dbpath = "./sqlite/" + username + "_"+ Provider +".db";
	db = sqlite3.connect(dbpath);
	devicetypelist = db.execute("SELECT DeviceName,DeviceType FROM DeviceTypeMapping")
	devicetypelist = list(devicetypelist);
	db.close();
	oldmodelname = None;
	for devicetype in devicetypelist:
		if DeviceModelList.get(devicetype[1]) != None:
			oldmodelname = DeviceModelList[devicetype[1]];
			DeviceModelList[devicetype[1]]["DeviceModel"] = devicetype[0];
			#Iottalk_devlisttmp = dict(Iottalk_devlist);
			Iottalk_devlisttmp = Iottalk_devlist.copy();
			for k,v in Iottalk_devlisttmp.items():
				if(v["DeviceModel"] == oldmodelname):
					Iottalk_devlist[k]["DeviceModel"] = devicetype[0];
			
			#DeviceGroupListtmp = dict(DeviceGroupList);
			DeviceGroupListtmp = DeviceGroupList.copy();
			for k,v in DeviceGroupListtmp.items():
				if(v["DeviceModel"] == oldmodelname):
					DeviceGroupList[k]["DeviceModel"] = devicetype[0];
				
def updatefeaturename():
	global Iottalk_devlist;
	global DeviceGroupList,DeviceModelList;
	
	dbpath = "./sqlite/" + username + "_"+ Provider +".db";
	#print(json.dumps(dbpath), flush=True)
	#sys.stdout.flush()
	db = sqlite3.connect(dbpath);
	devicefeaturelist = db.execute("SELECT ServiceName, OldServiceName, Feature FROM DeviceFeatureMapping")
	devicefeaturelist = list(devicefeaturelist);
	db.close();
	oldfeaturename = None;
	for devicefeature in devicefeaturelist:
		oldfeaturename = devicefeature[1];
		if DeviceFeaturealaismap.get(devicefeature[2]) != None:
			DeviceFeaturealaismap[devicefeature[2]] = devicefeature[0];
		#print(json.dumps(oldfeaturename), flush=True)
		#sys.stdout.flush()
		#DeviceModelListtmp = dict(DeviceModelList);
		DeviceModelListtmp = DeviceModelList.copy();
		for k,v in DeviceModelListtmp.items():
			if(oldfeaturename in v["DfList"]):
				pos = v["DfList"].index(oldfeaturename);
				DeviceModelList[k]["DfList"][pos] = devicefeature[0];
				#print(json.dumps(DeviceModelList[k]["DfList"]), flush=True)
				#sys.stdout.flush()
		
		#DeviceGroupListtmp = dict(DeviceGroupList);
		DeviceGroupListtmp = DeviceGroupList.copy;
		for k,v in DeviceGroupListtmp.items():
			if(oldfeaturename in v["DfList"]):
				pos = v["DfList"].index(oldfeaturename);
				DeviceGroupList[k]["DfList"][pos] = devicefeature[0];
				#print(json.dumps(DeviceGroupList[k]["DfList"]), flush=True)
				#sys.stdout.flush()
		
		#Iottalk_devlisttmp = dict(Iottalk_devlist);
		Iottalk_devlisttmp = Iottalk_devlist.copy();
		for k,v in Iottalk_devlisttmp.items():
			if(oldfeaturename in v["DfList"]):
				pos = v["DfList"].index(oldfeaturename);
				Iottalk_devlist[k]["DfList"][pos] = devicefeature[0];
				#print(json.dumps(Iottalk_devlist[k]["DfList"]), flush=True)
				#sys.stdout.flush()

def register():
	#IoTtalk 的裝置註冊
	#registerSession = {"Session":requests.Session()}; 
	#registerSession = requests.Session();
	#registerSession.keep_alive = False
	global Iottalk_devlist;
	global Iottalk_featurelist;
	global Iottalk_dev_name;
	#print "IoTtalk register";
	#sys.stdout.flush();
	if(len(Iottalk_devlist) > 0):
		try:
			#Iottalk_devlisttmp = dict(Iottalk_devlist);
			Iottalk_devlisttmp = Iottalk_devlist.copy();
			for k,v in Iottalk_devlisttmp.items():  
				
				typestr = str(type(Iottalk_devlist[k]['Iottalk_dev']));
				#print "type(Iottalk_devlist[k]['Iottalk_dev']): %s" % typestr
				pos = typestr.find("DAI",0,100)
				if pos == -1:
					try:
						if Iottalk_devlist[k]["DeviceModel"] == "SIP":
							Iottalk_devlist[k]["Iottalk_dev"] = DAI(IoTtalkServer,Iottalk_devlist[k]["DeviceModel"]+"-"+Iottalk_devlist[k]["DeviceGroup"]);
							Iottalk_devlist[k]["Iottalk_dev"].register(Iottalk_devlist[k]["DeviceModel"], Iottalk_devlist[k]["DfList"], Iottalk_devlist[k]["DeviceGroup"]);
							#print("Iottalk_featurelist["+Iottalk_devlist[k]["DeviceGroup"]+"] = ", Iottalk_devlist[k]["SIPDfList"]);
							#sys.stdout.flush();
						else:
							Iottalk_devlist[k]["Iottalk_dev"] = DAI(IoTtalkServer,Iottalk_devlist[k]["RegisterModel"]+"-"+Iottalk_devlist[k]["DeviceGroup"]);
							Iottalk_devlist[k]["Iottalk_dev"].register(Iottalk_devlist[k]["RegisterModel"], Iottalk_devlist[k]["DfList"], Iottalk_devlist[k]["DeviceGroup"]);
							if Iottalk_devlist[k]["RegisterModel"] == "SIP":
								Iottalk_devlist[k]["Iottalk_dev"].set_SIPDfList(Iottalk_devlist[k]["DfList"],Iottalk_devlist[k]["SIPDfList"]);
								
					except Exception as e:
						traceback.print_exc(file=open('debug.txt','a+'))
						#sys.stdout.flush();
		except Exception as e:
			#print ("register Error:", e);
			#sys.stdout.flush();
			typestr = str(e); 
			traceback.print_exc(file=open('debug.txt','a+'))
			pos = typestr.find("dictionary changed size during",0,300)
			if pos != -1:
				time.sleep(5);
				register()
							 
	return "Success"

def exit_check():
	#隨時檢查是否有收到程式終止的要求，有就正常終止自己
	with open('print.txt', "a+") as f:
		f.write("exit_check start, can start to receive message\n")
	global exitbool;
	global starttime;
	while True:
		if(exitbool):
			with open('print.txt', "a+") as f:
				f.write("exit\n")
			exit();
			sys.exit();
		time.sleep(1);

def exit():
	#程式結束前去做Iottalk的反註冊，使用sys.exit()或是接到signal.SIGTERM都會觸發
	with open('print.txt', "a+") as f:
		f.write("exit start, deregister device from iottalk\n")
	global Iottalk_devlist;
	timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()));
	#Iottalk_devlisttmp = dict(Iottalk_devlist);
	Iottalk_devlisttmp = Iottalk_devlist.copy();
	for k,v in Iottalk_devlisttmp.items():  
		try:
			Iottalk_devlist[k]["Iottalk_dev"].deregister();
		except Exception as e:
			traceback.print_exc(file=open('debug.txt','a+'))
			with open('debug.txt', "a+") as f:
				f.write("why\n")
			continue;

#系統的signal handle
def handler(sig, frame):
	exit();  
	sys.exit()

#監聽系統的signal，一旦收到signal.SIGTERM就終止自己
signal.signal(signal.SIGTERM, handler)
signal.signal(signal.SIGINT, handler)
#偵測到使用者按ctrl+c，就終止自己		
#atexit.register(exit) 

if __name__ == "__main__":
	
	global username;
	global Provider;
	global SIPAccount, SIPPassword, Domain, SIPProxy, SIPProxyPort;

	global DeviceGroupList,DeviceModelList;
	global SIPdevicelist,SIPtopiclist;
	global Iottalk_devlist;
	global client;
	
	global Iottalk_featurelist;
	global exitbool;
	global starttime;
	global AllDeviceList;
	global DeviceFeaturealaismap;

	global regproxybool;
	regproxybool = False;

	global needsub;
	needsub = False;

	global i_attr
	i_attr = None

	global mtsize_count
	mtsize_count = 0

	DeviceFeaturealaismap = {};
	exitbool = False;
	Query_flag = False;
	Iottalk_featurelist = {};
	SIPdevicelist = {}
	SIPtopiclist = {}
	Iottalk_devlist = {};
	DeviceGroupList = {};
	DeviceModelList = {};
	AllDeviceList={};

	with open('print.txt', "a+") as f:
		f.write("SIP_IDA start\n")

	if(len(sys.argv) > 1):
		username = sys.argv[1];
	else:
		#print ("please enter username");
		#sys.stdout.flush();
		username = "jenny";
	
	Provider = "SIP";	
	
	starttime = time.asctime( time.localtime(time.time()));
	with open('print.txt', "a+") as f:
		f.write("Start time: %s\n" % starttime)
	
	#loadconfiguration()

	loadconf=threading.Thread(target = loadconfiguration)
	loadconf.daemon = True  # When main thread is stopped, child thread is also stopped.
	loadconf.start()

	time.sleep(2)
	loadDeviceProfile()
	
	register_PIPE=threading.Thread(target = register_PIPE)
	register_PIPE.daemon = True  # When main thread is stopped, child thread is also stopped.
	register_PIPE.start()
	
	time.sleep(3)

	#隨時檢查是否有收到程式終止的要求
	exit_check();

