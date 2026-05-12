#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
# coding: UTF-8	#兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯
"""Flask Login Example and instagram fallowing find"""
import json
import subprocess
import sys, traceback
import os
import time
import random
import threading
import time
import requests
import sqlite3
import chardet
from flask import Flask, jsonify, url_for, render_template, request, redirect, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc
import config

global Iottalksession

NBIoTtalkPort = config.NBIoTtalkPort
IoTtalkServer = config.IoTtalkServer
IoTtalkServerPort = config.IoTtalkServerPort

# 設定資料庫位置，並建立 app
# 是web.db資料庫，與SIP.db不一樣
app = Flask(__name__)
ctx = app.app_context()
ctx.push()

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////'+ os.path.join(basedir, "sqlite/web.db")
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////sqlite/web.db'
db = SQLAlchemy(app)


class DeviceTypeMapping(db.Model):
    # __table__name = 'user_table' 若不寫則看 class name
    id = db.Column(db.Integer, primary_key=True)
    DeviceName = db.Column(db.String(200), unique=True)
    SIP = db.Column(db.String(200))  # 20
    NHR = db.Column(db.String(200))  # 90
    username = db.Column(db.String(200))

    def __init__(self, DeviceName, SIP, NHR, username):
        self.DeviceName = DeviceName
        self.SIP = SIP
        self.NHR = NHR
        self.username = username


class DeviceFeatureMapping(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ServiceName = db.Column(db.String(200), unique=True)
    Dimension = db.Column(db.Integer)
    DataType = db.Column(db.String(200))
    SIP = db.Column(db.String(200))
    NHR = db.Column(db.String(200))
    username = db.Column(db.String(200))

    def __init__(self, ServiceName, Dimension, DataType, SIP, NHR, username):
        self.ServiceName = ServiceName
        self.Dimension = Dimension
        self.DataType = DataType
        self.SIP = SIP
        self.NHR = NHR
        self.username = username


class ServiceProvider(db.Model):
    """ Create Service Provider table"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200))
    Provider = db.Column(db.String(200))
    SIPAccount = db.Column(db.String(200))
    SIPPassword = db.Column(db.String(200))
    Domain = db.Column(db.String(200))
    SIPProxy = db.Column(db.String(200))
    SIPProxyPort = db.Column(db.String(200))
    PSProxy = db.Column(db.String(200))
    PSProxyPort = db.Column(db.String(200))
    ExecutionState = db.Column(db.String(200))

    def __init__(self, username, Provider, SIPAccount, SIPPassword, Domain, SIPProxy, SIPProxyPort, PSProxy, PSProxyPort, ExecutionState):
        self.username = username
        self.Provider = Provider
        self.SIPAccount = SIPAccount
        self.SIPPassword = SIPPassword
        self.Domain = Domain
        self.SIPProxy = SIPProxy
        self.SIPProxyPort = SIPProxyPort
        self.PSProxy = PSProxy
        self.PSProxyPort = PSProxyPort
        self.ExecutionState = ExecutionState

class DeviceGroup(db.Model):
    """ Create Service Provider table"""
    id = db.Column(db.Integer, primary_key=True)
    devicemodel = db.Column(db.String(200))
    devicegroup = db.Column(db.String(200))
    Lat = db.Column(db.Float)
    Lng = db.Column(db.Float)
    username = db.Column(db.String(200))
    Provider = db.Column(db.String(200))

    def __init__(self, devicemodel, devicegroup, Lat, Lng, username, Provider):
        self.devicemodel = devicemodel
        self.devicegroup = devicegroup
        self.Lat = Lat
        self.Lng = Lng
        self.username = username
        self.Provider = Provider

class Device(db.Model):
    """ Create Service Provider table"""
    id = db.Column(db.Integer, primary_key=True)
    IMEI = db.Column(db.String(200))
    devicemodel = db.Column(db.String(200))
    devicegroup = db.Column(db.String(800))
    username = db.Column(db.String(200))
    Provider = db.Column(db.String(200))

    def __init__(self, IMEI, devicemodel, devicegroup, username, Provider):
        self.IMEI = IMEI
        self.devicemodel = devicemodel
        self.devicegroup = devicegroup
        self.username = username
        self.Provider = Provider


class User(db.Model):
    """ Create user table"""
    id = db.Column(db.Integer, primary_key=True)  # 不能重複，且不能null
    username = db.Column(db.String(200), unique=True)  # unique表示此欄位的值可以null但是不能重複
    password = db.Column(db.String(200))

    def __init__(self, username, password):
        self.username = username
        self.password = password


@app.route('/ServiceProviderSave')
def ServiceProviderSave():
    print("ServiceProviderSave")
    global childprocess
    global clearbufferflag
    executionstate = ""

    ## device profile start
    
    # 先匯入device profile，之後可以用一個web page讓user輸入
    try:
        Providerdbpath = "./sqlite/" + \
            session.get('logged_in') + "_" + session.get('provider') + ".db"
        Providerdb = sqlite3.connect(Providerdbpath)
        create_tb_cmd = "CREATE TABLE IF NOT EXISTS DeviceProfile (IMEI TEXT,devicemodeltype TEXT, devicemodel TEXT,devicefeaturetype TEXT, devicefeature TEXT, dim TEXT, datatype TEXT, attr TEXT)"
        Providerdb.execute(create_tb_cmd)
        devicetypelist = Providerdb.execute("SELECT IMEI,devicemodeltype,devicemodel,devicefeaturetype,devicefeature,dim,datatype,attr FROM DeviceProfile")
        devicetypelist = list(devicetypelist)
        # 若不是0則已經匯入過，不需要再匯
        if len(devicetypelist) == 0:
            # Scenario 1: Road condition monitoring
            # SUAs: 2個, each of them connects 3 roadSensors
            #Providerdb.execute("INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('sensor1-device1@192.168.122.165', '20','RoadSensor','0001', 'RoadAvgSpeed-I', '2', 'float', 'I')")
            #Providerdb.execute("INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('actuator1-devicea1@192.168.122.165', '30','ElecMap','0002', 'RoadAvgSpeed-O', '2', 'float', 'O')")
            #Providerdb.execute("INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('sensor2-device1@192.168.122.165', '40','FrontImage','0002', 'Image-I', '2', 'float', 'I')")
            #Providerdb.execute("INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('actuator2-devicea1@192.168.122.165', '50','PreImmage','0005', 'Image-O', '2', 'float', 'O')")
            #Providerdb.execute("INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('sensor3-device1@192.168.122.165', '60','AudioSession','0003', 'AudioSession-I', '2', 'float', 'I')")
            #Providerdb.execute("INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('sensor3-device2@192.168.122.165', '60','AudioSession','0003', 'AudioSession-I', '2', 'float', 'I')")
            #Providerdb.execute("INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('actuator3-devicea1@192.168.122.165', '70','ClipDetect','0006', 'ClipDetect-O', '2', 'float', 'O')")
            for i in  range(1,8):
                #dbcmd = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('sensor1-device" + str(i) + "@192.168.122.165', '20','RoadSensor','0001', 'RoadAvgSpeed-I', '2', 'float', 'I')"
                #dbcmd2 = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('actuator1-devicea" + str(i) + "@192.168.122.165', '30','ElecMap','0003', 'RoadAvgSpeed-O', '2', 'float', 'O')"
                dbcmd = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('sensor2-devicetest"+str(i)+"@140.114.77.83', '40','FrontImage','0002', 'Image-I', '2', 'float', 'I')"
                dbcmd2 = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('actuator2-deviceatest"+str(i)+"@140.114.77.83', '50','PreImage','0005', 'Image-O', '2', 'float', 'O')"
                #dbcmd = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('sensor1-devicetest"+str(i)+"@140.114.77.83', '20','RoadSensor','0001', 'RoadAvgSpeed-I', '2', 'float', 'I')"
                #dbcmd2 = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('actuator1-deviceatest"+str(i)+"@140.114.77.83', '30','ElecMap','0003', 'PredictedSpeed-O', '2', 'float', 'O')"
                #dbcmd2 = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('actuator1-deviceatest"+str(i)+"@140.114.77.83', '30','ElecMap','0003', 'RoadAvgSpeed-O', '2', 'float', 'O')"
                #dbcmd = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('sensor1-devicetest"+str(i)+"@140.114.77.83', '60','AudioSession','0003', 'AudioSession-I', '2', 'float', 'I')"
                #dbcmd2 = "INSERT INTO DeviceProfile (IMEI,devicemodeltype, devicemodel,devicefeaturetype, devicefeature, dim, datatype, attr) VALUES ('actuator1-deviceatest"+str(i)+"@140.114.77.83', '70','ClipDetect','0006', 'ClipDetect-O', '2', 'float', 'O')"
                Providerdb.execute(dbcmd)
                Providerdb.execute(dbcmd2)
                print("InsertDeviceList")

        ## 之後可以用一個web page讓user輸入: input device的屬性是message還是streaming
        input_ua_attr = "1" ## 0為SIoT, 1為MIoT
        with open('InputAttr.txt', "a+") as f:
            f.write(input_ua_attr)
        print("HelloWorld")
        Providerdb.commit()
        Providerdb.close()
    except Exception as e:
        traceback.print_exc(file=open('debug.txt','a+'))
        print("Create DeviceProfile table failed")
        print(e)
        Providerdb.close()
    ## device profile end


    #if request.method == 'POST':
    if True:
        session['provider'] = request.args.get('provider', "", type=str)
        SIPAccount = request.args.get('SIPAccount', "", type=str)
        SIPPassword = request.args.get('SIPPassword', "", type=str)
        Domain = request.args.get('Domain', "", type=str)
        SIPProxy = request.args.get('SIPProxy', "", type=str)
        SIPProxyPort = request.args.get(
            'SIPProxyPort', "", type=str)
        PSProxy = request.args.get('PSProxy', "", type=str)
        PSProxyPort = request.args.get(
            'PSProxyPort', "", type=str)
        username = session['logged_in']
        Provider = session['provider']

        provider = ServiceProvider.query.filter_by(
            username=session['logged_in'], Provider=session['provider']).first()
        print("Provider configuration")
        # 第一次登入
        if provider is None:
            new_ServiceProvider = ServiceProvider(
                username=username, Provider=Provider,
                SIPAccount=SIPAccount, SIPPassword=SIPPassword,
                Domain=Domain, SIPProxy=SIPProxy,
                SIPProxyPort=SIPProxyPort, PSProxy=PSProxy,
                PSProxyPort=PSProxyPort, ExecutionState="")
            db.session.add(new_ServiceProvider)
            db.session.commit()
            childprocess[username] = {}
            user = username
            # Python strip() 方法用于移除字符串头尾指定的字符（默认为空格或换行符）或字符序列。
            user.strip()

            clearbufferflag = False
            time.sleep(1)

            # 會由raw function轉換為原始字串
            filename = raw(session['provider']+'_IDA.py')

            # user應該是作為傳送到另外python的arg
            # sys.executable 加上filename表示，用python absolute path來執行.py file
            # 此處已更改寫法：改為用python2.7執行childprocess
            script = ["python3", filename, user]
            #script = ["python2.7", filename, user]
            childprocess[username][Provider] = subprocess.Popen(
                " ".join(script), shell=True, env={"PYTHONPATH": "."}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True, bufsize=65535)

            time.sleep(5)
            pipeinfo = {}
            pipeinfo["state"] = "ExecutionState"
            #print("xxxxxxxxxxx")
            try:
                # file -- 要写入的文件对象。
                # 應該是把pipeinfo以json格式寫入childprocess[username][Provider].stdin
                # 剛剛已經open過childprocess的pipe
                print(json.dumps(pipeinfo),
                      file=childprocess[username][Provider].stdin, flush=True)
                sys.stdout.flush()
                while True:
                    # 讀出stdout
                    content = childprocess[username][Provider].stdout.readline()
                    print("ServiceProviderSave: ", content)
                    print("type(content)", type(content))
                    # 如果找不到ExecutionState, state的值 (!=null)
                    # 只有在NHR_IDA之register_PIPE中有看到以下回傳的訊息，這邊可能是判斷是否有成功註冊到iottalk
                    print("ppppp")
                    if content.find("ExecutionState") != -1 and content.find("state") != -1:
                        content = json.loads(content)
                        executionstate = content["result"]
                        #print("IDA Execution State : ",executionstate)
                        #print("type(content)",type(content))
                        break
            except OSError as err:
                traceback.print_exc(file=open('debug.txt','a+'))
                sys.stdout.flush()
                while True:
                    content = childprocess[username][Provider].stdout.readline()
                    if content.find("ExecutionState") != -1 and content.find("state") != -1:
                        content = json.loads(content)
                        executionstate = content["result"]
                        #print("IDA Execution State : ",executionstate)
                        #print("type(content)",type(content))
                        break

            clearbufferflag = True

            provider = ServiceProvider.query.filter_by(
                username=session['logged_in'], Provider=session['provider']).first()
            provider.username = username
            provider.Provider = Provider
            provider.SIPAccount = SIPAccount
            provider.SIPPassword = SIPPassword
            provider.Domain = Domain
            provider.SIPProxy = SIPProxy
            provider.SIPProxyPort = SIPProxyPort
            provider.PSProxy = PSProxy
            provider.PSProxyPort = PSProxyPort
            provider.ExecutionState = executionstate
            db.session.commit()

        # Provider is not NONE (不是第一次登入)
        else:
            if True:
                provider.username = username
                provider.Provider = Provider
                provider.SIPAccount = SIPAccount
                provider.SIPPassword = SIPPassword
                provider.Domain = Domain
                provider.SIPProxy = SIPProxy
                provider.SIPProxyPort = SIPProxyPort
                provider.PSProxy = PSProxy
                provider.PSProxyPort = PSProxyPort
                provider.ExecutionState = executionstate
                db.session.commit()
                if username not in childprocess.keys():
                    # 見一個username key
                    childprocess[username] = {}
                else:
                    pipeinfo = {}
                    pipeinfo["state"] = "Exit"

                    clearbufferflag = False
                    time.sleep(1)

                    if childprocess[username].get(Provider) != None:
                        print(json.dumps(
                            pipeinfo), file=childprocess[username][Provider].stdin, flush=True)
                        sys.stdout.flush()
                        while True:
                            content = childprocess[username][Provider].stdout.readline()
                            if content.find("Exit") != -1 and content.find("state") != -1:
                                content = json.loads(content)
                                #print("Exit : ",content["result"])
                                sys.stdout.flush()
                                childprocess[username][Provider] = None
                                #print("type(content)",type(content))
                                break

                    clearbufferflag = True

                user = username
                user.strip()

                clearbufferflag = False

                # 感覺應該要加入device group判斷
                groups = DeviceGroup.query.filter_by(
                    username=session['logged_in'], Provider=session['provider']).order_by(DeviceGroup.devicegroup).all()
                if(len(groups) > 0):
                    DeviceGroup.query.filter_by(
                        username=session['logged_in'], Provider=session['provider']).delete()
                    Device.query.filter_by(
                        username=session['logged_in'], Provider=session['provider']).delete()

                time.sleep(1)
                filename = raw(session['provider']+'_IDA.py')
                script = ["python3", filename, user]
                #script = ["python2.7", filename, user]
                childprocess[username][Provider] = subprocess.Popen(
                    " ".join(script), shell=True, env={"PYTHONPATH": "."}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True, bufsize=65535)

                pipeinfo = {}
                pipeinfo["state"] = "ExecutionState"
                time.sleep(10)
                try:
                    print(json.dumps(pipeinfo),
                          file=childprocess[username][Provider].stdin, flush=True)
                    sys.stdout.flush()
                    while True:
                        content = childprocess[username][Provider].stdout.readline(
                        )
                        if content.find("ExecutionState") != -1 and content.find("state") != -1:
                            content = json.loads(content)
                            executionstate = content["result"]
                            #print("IDA Execution State : ",executionstate)
                            #print("type(content)",type(content))
                            break
                except OSError as err:
                    traceback.print_exc(file=open('debug.txt','a+'))
                    sys.stdout.flush()
                    while True:
                        content = childprocess[username][Provider].stdout.readline(
                        )
                        if content.find("ExecutionState") != -1 and content.find("state") != -1:
                            content = json.loads(content)
                            executionstate = content["result"]
                            #print("IDA Execution State : ",executionstate)
                            #print("type(content)",type(content))
                            break

                clearbufferflag = True

                provider.username = username
                provider.Provider = Provider
                provider.SIPAccount = SIPAccount
                provider.SIPPassword = SIPPassword
                provider.Domain = Domain
                provider.SIPProxy = SIPProxy
                provider.SIPProxyPort = SIPProxyPort
                provider.PSProxy = PSProxy
                provider.PSProxyPort = PSProxyPort
                provider.ExecutionState = executionstate
                db.session.commit()
                if executionstate != "Success":
                    del childprocess[username][Provider]
        print("executionstate : ", executionstate)
        session['IDAExecution'] = executionstate
        #if executionstate == "Success" :

        return jsonify(result=executionstate)


@app.route('/ServiceProviderGet')
def ServiceProviderGet():
    print("ServiceProviderGet")
    session['provider'] = request.args.get('provider', "", type=str)
    print("Select " + session['provider']);

    provider = ServiceProvider.query.filter_by(
        username=session['logged_in'], Provider=session['provider']).first()
    #print("QueryServiceProvider");
    if provider is None:
        result = {"type": 0}
        #print("type:0");
    else:
        result = {"type": 1,
                  "SIPAccount": provider.SIPAccount, "SIPPassword": provider.SIPPassword,
                  "Domain": provider.Domain,
                  "SIPProxy": provider.SIPProxy, "SIPProxyPort": provider.SIPProxyPort,
                  "PSProxy": provider.PSProxy, "PSProxyPort": provider.PSProxyPort,
                  "ExecutionState": provider.ExecutionState}
        if provider.ExecutionState == "Success":
            session['IDAExecution'] = provider.ExecutionState
        #print("type:1");
    return jsonify(result=result)

@app.route('/DeviceModelManagement', methods=['GET'])
def DeviceModelManagement():
    print("DeviceModelManagement start!")
    result = {}
    devicetypelist = None
    devicenamelist = []
    Providerdb = None
    
    try:
        Providerdbpath = "./sqlite/" + \
            session.get('logged_in') + "_" + session.get('provider') + ".db"
        Providerdb = sqlite3.connect(Providerdbpath)
        create_tb_cmd = "CREATE TABLE IF NOT EXISTS DeviceTypeMapping (DeviceName TEXT,DeviceType TEXT,FeatureCount INT,Feature TEXT)"
        #主要就是上面的语句
        Providerdb.execute(create_tb_cmd)
        Providerdb.commit()
        Providerdb.close()
    except Exception as e:
        traceback.print_exc(file=open('debug.txt','a+'))
        print("Create table failed")
        print(e)
        Providerdb.close()
    if session.get('provider'):
        Providerdbpath = "./sqlite/" + \
            session.get('logged_in') + "_" + session.get('provider') + ".db"
        Providerdb = sqlite3.connect(Providerdbpath)
        devicetypelist = Providerdb.execute("SELECT DeviceName,DeviceType,Feature FROM DeviceTypeMapping ORDER BY DeviceType")
        devicetypelist = list(devicetypelist)

        print("devicetypelist: %s" % str(devicetypelist))
        
        if len(devicetypelist) == 0:
            Providerdb.execute("INSERT INTO DeviceTypeMapping (DeviceName,DeviceType,FeatureCount,Feature) VALUES ('', '20', 1, '0001')")
            print("devicetypelist len = 0")
            Providerdb.commit()
        Providerdb.close()

        orderby = getattr(DeviceTypeMapping, session.get('provider'))
        # 以下是把devicemodel setting 存到web.db的device_type_mapping
        for devicetype in devicetypelist:
            DeviceTypeMappingQuery = DeviceTypeMapping.query.filter(getattr(DeviceTypeMapping, session.get(
                'provider')) == devicetype[1]).filter_by(username=session.get('logged_in')).order_by(orderby).all()
            print("DeviceTypeMappingQuery: ", str(DeviceTypeMappingQuery))
            if(len(DeviceTypeMappingQuery) == 0):
                DeviceNameMappingQuery = DeviceTypeMapping.query.filter_by(
                    DeviceName=devicetype[0], username=session.get('logged_in')).order_by(orderby).first();
                print("DeviceNameMappingQuery: ", str(DeviceNameMappingQuery))
                if DeviceNameMappingQuery is None:
                    new_deviceTypeMapping = DeviceTypeMapping(
                        DeviceName=devicetype[0], SIP="", NHR="", username=session.get('logged_in'));
                    setattr(new_deviceTypeMapping, session.get('provider'), devicetype[1])
                    db.session.add(new_deviceTypeMapping);
                    db.session.commit();
                else:
                    setattr(DeviceNameMappingQuery, session.get('provider'), devicetype[1])
                    db.session.commit();

        DeviceNameQuery = DeviceTypeMapping.query.filter_by(
            username=session.get('logged_in')).order_by(orderby).all();
        print("DeviceNameQuery: ", str(DeviceNameQuery))
        if(len(DeviceNameQuery) > 0):
            for devicename in DeviceNameQuery:
                devicenamelist.append(devicename.DeviceName);

    result["devicetypelist"] = list(devicetypelist);
    result["devicenamelist"] = list(devicenamelist);
    print("devicetypelist",str(list(devicetypelist)))
    print("devicenamelist",str(list(devicenamelist)))
    # 帶著result回到DeviceModelManagement.html
    return render_template('DeviceModelManagement.html', result=result)

# 0201 ADD
@app.route('/DeviceModelAdd')
def DeviceModelAdd():
    print("DeviceModelAdd")

    # 從html: AddModel()抓取devicetypeid
    devicetypeid = request.args.get('devicetypeid', type=str)
    print("devicetypeid: %s" % str(devicetypeid))

    if session.get('provider'):
        Providerdbpath = "./sqlite/" + \
        session.get('logged_in') + "_" + session.get('provider') + ".db"
        Providerdb = sqlite3.connect(Providerdbpath)

        DF_ID = "000" + str(devicetypeid[0])
        DM_name_default = str(devicetypeid)
        Providerdb.execute("INSERT INTO DeviceTypeMapping (DeviceName,DeviceType,FeatureCount,Feature) VALUES ('" + DM_name_default + "', '" + str(devicetypeid) + "', 1, '" + str(DF_ID) + "')")
        Providerdb.commit()
        
        devicetypelist = Providerdb.execute("SELECT DeviceName,DeviceType,Feature FROM DeviceTypeMapping ORDER BY DeviceType")
        devicetypelist = list(devicetypelist)

        Providerdb.close()

        print("devicetypelist: %s" % str(devicetypelist))
        ## devicetypelist: [('', '20', '0001'), ('', '30', '0003'), ('', '40', '0004')]

        orderby = getattr(DeviceTypeMapping, session.get('provider'))
        # 以下是把devicemodel setting 存到web.db的device_type_mapping
        for devicetype in devicetypelist:
            DeviceTypeMappingQuery = DeviceTypeMapping.query.filter(getattr(DeviceTypeMapping, session.get(
                'provider')) == devicetype[1]).filter_by(username=session.get('logged_in')).order_by(orderby).all()
            print(len(DeviceTypeMappingQuery))
            if(len(DeviceTypeMappingQuery) == 0):
                DeviceNameMappingQuery = DeviceTypeMapping.query.filter_by(
                    DeviceName=devicetype[0], username=session.get('logged_in')).order_by(orderby).first();
                print(DeviceNameMappingQuery)
                if DeviceNameMappingQuery is None:
                    new_deviceTypeMapping = DeviceTypeMapping(
                        DeviceName=devicetype[0], SIP="", NHR="", username=session.get('logged_in'));
                    setattr(new_deviceTypeMapping, session.get('provider'), devicetype[1])
                    db.session.add(new_deviceTypeMapping);
                    db.session.commit();
                else:
                    setattr(DeviceNameMappingQuery, session.get('provider'), devicetype[1])
                    db.session.commit();
    '''
        DeviceNameQuery = DeviceTypeMapping.query.filter_by(
            username=session.get('logged_in')).order_by(orderby).all();
        if(len(DeviceNameQuery) > 0):
            for devicename in DeviceNameQuery:
                devicenamelist.append(devicename.DeviceName);

    result["devicetypelist"] = list(devicetypelist);
    result["devicenamelist"] = list(devicenamelist);

    # 帶著result回到DeviceModelManagement.html
    return render_template('DeviceModelManagement.html', result=result)
    '''

    # 回報給html，不回報會出錯
    result = {}
    result["status"] = "Sucess"

    return jsonify(result=result)


@app.route('/DeviceModelSave')
def DeviceModelSave():
    print("DeviceModelSave")
    devicetypenamelist = request.args.get('devicetypenamelist', type=str)
    devicetypenamelist = json.loads(devicetypenamelist)

    devicetypeoldnamelist = request.args.get('devicetypeoldnamelist', type=str)
    devicetypeoldnamelist = json.loads(devicetypeoldnamelist)
    

    devicetypelist = request.args.get('devicetypelist', type=str)
    devicetypelist = json.loads(devicetypelist)

    s_checkbox = request.args.get('s_checkbox', type=str)
    s_checkbox = json.loads(s_checkbox)

    m_checkbox = request.args.get('m_checkbox', type=str)
    m_checkbox = json.loads(m_checkbox)

    print("SIOT: %s" % str(s_checkbox))
    print("MIOT: %s" % str(m_checkbox))
    print("devicetypelist: %s " % (str(devicetypelist)))
    
    devicetypelist_len = len(devicetypelist)
    devicetypelist = [] 
    for i in range(devicetypelist_len):
        devicetypelist.append('20')

    Providerdbpath = "./sqlite/" + \
        session.get('logged_in') + "_" + session.get('provider') + ".db"

    print("devicetypeoldnamelist: %s, devicetypenamelist: %s" % (str(devicetypeoldnamelist), str(devicetypenamelist)))
    print("devicetypelist_change: %s " % (str(devicetypelist)))
    for devicetype in devicetypelist:

        pos = devicetypelist.index(devicetype)
        # pos作為list的index
        oldmodelname = devicetypeoldnamelist[pos]
        newmodelname = devicetypenamelist[pos]
        print("oldmodelname: %s, newmodelname: %s" % (str(oldmodelname), str(newmodelname)))

        if(oldmodelname != newmodelname):
            modelold = None
            modelnew = None
            # query是取資料
            # first: Return the first result of this Query or None if the result doesn’t contain any row.
            modelold = DeviceTypeMapping.query.filter_by(
                DeviceName=oldmodelname).first()
            modelnew = DeviceTypeMapping.query.filter_by(
                DeviceName=newmodelname).first()
            print("oldmodel: %s, newmodel: %s" % (str(modelold), str(modelnew)))

            # 檢查是否有跟新的名字一樣的model name
            if(modelnew == None): ## LAI 
                # 沒有一樣
                modelold.DeviceName = newmodelname
                db.session.commit()
            elif(modelnew != None):  # 有一樣的
                if getattr(modelnew, session.get('provider')) == "" or getattr(modelnew, session.get('provider')) == None:
                    # 有點像是新增變數
                    # 例如：setattr(x,"test", abc) 相當於 x.test = abc
                    setattr(modelold, session.get('provider'), "")
                    setattr(modelnew, session.get('provider'), devicetype)
                    db.session.commit()
                elif getattr(modelnew, session.get('provider')) != devicetype:
                    # model name已被使用
                    result = {}
                    result["status"] = "The DeviceName(" + \
                        newmodelname + ") is already used."
                    return jsonify(result=result)

        # 更新新的modelname到資料庫
        Providerdb = sqlite3.connect(Providerdbpath)
        Providerdb.execute("UPDATE DeviceTypeMapping SET DeviceName = '" +
                           newmodelname + "' WHERE DeviceType = '" + devicetype + "'")
        Providerdb.commit()
        Providerdb.close()

        # 更新device group table裡面的modelname
        groups = None
        groups = DeviceGroup.query.filter_by(
            devicemodel=oldmodelname, username=session['logged_in'], Provider=session['provider']).order_by(DeviceGroup.devicegroup).all()
        for group in groups:
            group.devicemodel = newmodelname
            db.session.commit()

        # 更新device table裡面的modelname
        devicelistquery = Device.query.filter_by(
            devicemodel=oldmodelname, username=session['logged_in'], Provider=session['provider']).order_by(Device.IMEI).all()
        for device in devicelistquery:
            device.devicemodel = newmodelname
            db.session.commit()
    
    global childprocess
    #with open('debug.txt', "a+") as f:
    #	f.write("checkpoint1\n")
    try:
        pipeinfo = {}
        pipeinfo["state"] = "UpdateModelName"

        clearbufferflag = False
        time.sleep(1)
        
        
        # 將UpdateModelName傳至SIP_IDA 更新iottalk model name
        print(json.dumps(pipeinfo),
              file=childprocess[session['logged_in']][session['provider']].stdin, flush=True)
        sys.stdout.flush()
        
        while True:
            content = childprocess[session['logged_in']][session['provider']].stdout.readline()
            print("Updatemodelname: ", content)
            print("type(content)", type(content))
            if content.find("UpdateModelName") != -1 and content.find("state") != -1:
                #print("Updatemodelname:", content)
                content = json.loads(content)
                #print("DeviceList : ",content["result"])
                sys.stdout.flush()
                #print("type(content)",type(content))
                break
        
        time.sleep(1)
        clearbufferflag = True

    except Exception as e:
        traceback.print_exc(file=open('debug.txt','a+'))
        print("e: ", e)

    result = {}
    result["status"] = "Sucess"

    return jsonify(result=result)


@app.route('/DeviceFeatureManagement', methods=['GET'])
def DeviceFeatureManagement():
    print("DeviceFeatureManagement")
    result = {}
    devicefeaturelist = []
    devicefeaturenamelist = []
    Providerdb = None
    try:
        Providerdbpath = "./sqlite/" + \
            session.get('logged_in') + "_" + session.get('provider') + ".db"
        Providerdb = sqlite3.connect(Providerdbpath)
        create_tb_cmd = "CREATE TABLE IF NOT EXISTS DeviceFeatureMapping (Feature TEXT,ServiceName TEXT,Dimension INT,DataType TEXT)"
        #主要就是上面的语句
        Providerdb.execute(create_tb_cmd)
        Providerdb.commit()
        
        Providerdb.close()
    except Exception as e:
        traceback.print_exc(file=open('debug.txt','a+'))
        print("Create table failed")
        print(e)
        Providerdb.close()
    
    '''
    由device端送資料過來 且資料類型存於db（原程式碼是由mqtt送資料來 並存至db）
    device端資料存在SIP.db，在經過下面的程式碼，存到web.db
    '''
    if session.get('provider'):
        Providerdbpath = "./sqlite/" + \
            session.get('logged_in') + "_" + session.get('provider') + ".db"
        Providerdb = sqlite3.connect(Providerdbpath)
        devicefeaturelisttmp = Providerdb.execute(
            "SELECT ServiceName,Feature,Dimension,DataType FROM DeviceFeatureMapping ORDER BY Feature")
        devicefeaturelisttmp = list(devicefeaturelisttmp)
        
        if len(devicefeaturelisttmp) == 0:
            Providerdb.execute(
                "INSERT INTO DeviceFeatureMapping (Feature,ServiceName,Dimension,DataType,OldServiceName,DeviceName) VALUES ('0001', 'SIPGeoLocation', 2, 'float', '', '')")
            Providerdb.commit() #存資料才需要commit
            devicefeaturelisttmp = Providerdb.execute(
                "SELECT ServiceName,Feature,Dimension,DataType FROM DeviceFeatureMapping ORDER BY Feature")
            devicefeaturelisttmp = list(devicefeaturelisttmp)
        for devicefeaturetmp in devicefeaturelisttmp:
            devicefeaturelist.append(devicefeaturetmp)
            
        Providerdb.close()

        orderby = getattr(DeviceFeatureMapping, session.get('provider'))
        
        print("devicefeaturelist:", devicefeaturelist) # [('SIPGeoLocation', '0001', 1, 'int')]
        for devicefeature in devicefeaturelist:
            
            DeviceFeatureMappingQuery = DeviceFeatureMapping.query.filter(getattr(DeviceFeatureMapping, 
            session.get('provider')) == devicefeature[1]).filter_by(username=session.get('logged_in')).order_by(orderby).all()

            # 以下是把devicefeaturelsetting 存到“web.db”的device_feature_mapping
            if(len(DeviceFeatureMappingQuery) == 0):
                FeatureNameMappingQuery = DeviceFeatureMapping.query.filter_by(
                    ServiceName=devicefeature[0], username=session.get('logged_in')).order_by(orderby).first()
                if FeatureNameMappingQuery is None:
                    new_deviceFeatureMapping = DeviceFeatureMapping(
                        ServiceName=devicefeature[0], Dimension=devicefeature[2], DataType=devicefeature[3], SIP="", NHR="", username=session.get('logged_in'))
                    setattr(new_deviceFeatureMapping, session.get(
                        'provider'), devicefeature[1])
                    db.session.add(new_deviceFeatureMapping)
                    db.session.commit()
                else:
                    setattr(FeatureNameMappingQuery, session.get(
                        'provider'), devicefeature[1])
                    db.session.commit()

        DeviceFeatureQuery = DeviceFeatureMapping.query.filter_by(
            username=session.get('logged_in')).order_by(orderby).all()
        for featurename in DeviceFeatureQuery:
            devicefeaturenamelist.append(featurename.ServiceName)

    result["devicefeaturelist"] = list(devicefeaturelist)
    result["devicefeaturenamelist"] = list(devicefeaturenamelist)
    result["status"] = "Sucess"

    #return jsonify(result = result)
    return render_template('DeviceFeatureManagement.html', result=result)


@app.route('/DeviceFeatureSave')
def DeviceFeatureSave():
    print("DeviceFeatureSave")
    # 新名字
    devicefeaturenamelist = request.args.get('devicefeaturenamelist', type=str)
    devicefeaturenamelist = json.loads(devicefeaturenamelist)
    #print("dfnamelist:", devicefeaturenamelist)  # ['DeviceGPS-2']
    
    # 舊名字
    devicefeatureoldnamelist = request.args.get(
        'devicefeatureoldnamelist', type=str)
    devicefeatureoldnamelist = json.loads(devicefeatureoldnamelist)
    #print("dfoldnamelist:", devicefeatureoldnamelist)  # ['DeviceGPS']
    
    devicefeaturelist = request.args.get('devicefeaturelist', type=str)
    devicefeaturelist = json.loads(devicefeaturelist)
    #print("dflist:", devicefeaturelist)  # ['0001']

    Providerdbpath = "./sqlite/" + \
        session.get('logged_in') + "_" + session.get('provider') + ".db"

    for devicefeature in devicefeaturelist:
        pos = devicefeaturelist.index(devicefeature)
        oldfeaturename = devicefeatureoldnamelist[pos]
        newfeaturename = devicefeaturenamelist[pos]
        if(oldfeaturename != newfeaturename):
            featuresold = None
            featuresnew = None
            
            featuresold = DeviceFeatureMapping.query.filter_by(
                ServiceName=oldfeaturename, username=session.get('logged_in')).first()
            featuresnew = DeviceFeatureMapping.query.filter_by(
                ServiceName=newfeaturename, username=session.get('logged_in')).first()
            
            # 檢查是否有跟新的名字一樣的feature name
            if(featuresnew == None): # 沒有一樣的
                featuresold.ServiceName = newfeaturename
                db.session.commit()
            elif(featuresnew != None):  #有一樣的
                if getattr(featuresnew, session.get('provider')) == "" or getattr(featuresnew, session.get('provider')) == None:
                    # 如果df已經有了，判斷dim跟datatype對不對，
                    if(featuresold.Dimension == featuresnew.Dimension and featuresold.DataType == featuresnew.DataType):
                        # 全都一樣，更新變數
                        setattr(featuresold, session.get('provider'), "")
                        setattr(featuresnew, session.get(
                            'provider'), devicefeature)
                        db.session.commit()
                    elif featuresold.Dimension != featuresnew.Dimension:
                        result = {}
                        result["status"] = "Dimension Error: The ServiceName(" + newfeaturename + ") already exists, and its Dimension is " + str(
                            featuresnew.Dimension) + "."
                        return jsonify(result=result)
                    elif featuresold.DataType != featuresnew.DataType:
                        result = {}
                        result["status"] = "DataType Error: The ServiceName(" + newfeaturename + ") already exists, and its DataType is " + str(
                            featuresnew.DataType) + "."
                        return jsonify(result=result)
                elif getattr(featuresnew, session.get('provider')) != devicefeature: # 如果df一樣，且現在新的又不等於原本的df
                    result = {}
                    result["status"] = "The ServiceName(" + \
                        newfeaturename + ") is already used."
                    return jsonify(result=result)
            
            Providerdb = sqlite3.connect(Providerdbpath)
            Providerdb.execute("UPDATE DeviceFeatureMapping SET ServiceName = '" + newfeaturename +
                               "', OldServiceName = '" + oldfeaturename + "' WHERE Feature = '"+devicefeature+"'")
            Providerdb.commit()
            Providerdb.close()
    
    global childprocess

    try:
        pipeinfo = {}
        pipeinfo["state"] = "UpdateFeatureName"
        
        clearbufferflag = False
        time.sleep(1)
        
        print(json.dumps(pipeinfo),
              file=childprocess[session['logged_in']][session['provider']].stdin, flush=True)
        sys.stdout.flush()
        
        while True:
            content = childprocess[session['logged_in']][session['provider']].stdout.readline()
            print("UpdateFeatureName: ", content)
            print("type(content)", type(content))
            if content.find("UpdateFeatureName") != -1 and content.find("state") != -1:
                #print("UpdateFeaturename:", content)
                content = json.loads(content)
                #print("DeviceList : ",content["result"])
                sys.stdout.flush()
                #print("type(content)",type(content))
                break
        
        time.sleep(1)
        clearbufferflag = True
        
    except Exception as e:
        traceback.print_exc(file=open('debug.txt','a+'))
        print("e: ", e)

    result = {}
    result["status"] = "Sucess"

    return jsonify(result=result)

@app.route('/DeviceGroupManagement', methods=['GET', 'POST'])
def DeviceGroupManagement():
    print("DeviceGroupManagement")
    if session.get('provider'):
        return render_template('DeviceGroupManagement.html')
    else:
        return render_template('index.html')

@app.route('/AccountManagement', methods=['GET'])
def AccountManagement():
    print("AccountManagement")
    if session.get('provider') and session.get('logged_in'):
        provider = ServiceProvider.query.filter_by(
            username=session['logged_in'], Provider=session['provider']).first()
        if provider is None:
            result = {"type": 0,
                      "SIPAccount": "", "SIPPassword": "",
                      "Domain": "",
                      "SIPProxy": "", "SIPProxyPort": "",
                      "PSProxy": "", "PSProxyPort": "",
                      "ExecutionState": ""}
            #print("type:0");
        else:
            result = {"type": 1,
                      "SIPAccount": provider.SIPAccount, "SIPPassword": provider.SIPPassword,
                      "Domain": provider.Domain,
                      "SIPProxy": provider.SIPProxy, "SIPProxyPort": provider.SIPProxyPort,
                      "PSProxy": provider.PSProxy, "PSProxyPort": provider.PSProxyPort,
                      "ExecutionState": provider.ExecutionState}
            #print("type:1");
        #return jsonify(result = result)
        return render_template('AccountManagement.html', result=result)
    else:
        print("??")
        return render_template('index.html')

@app.route('/GroupAuto', methods=['GET', 'POST'])
def GroupAuto():
    return render_template('GroupAuto.html')

@app.route('/GroupManual', methods=['GET'])
def GroupManual():
    print("GroupManual")
    global childprocess
    username = session['logged_in']
    Provider = session['provider']
    
    
    groups = DeviceGroup.query.filter_by(username=username,Provider=Provider).order_by(DeviceGroup.devicegroup).all()
    devicegrouplist=[];
    if(len(groups) > 0):
        for group in groups:
            devicegrouplist.append({'DeviceGroup':group.devicegroup,'DeviceModel':group.devicemodel});
    result ={};
    devicemodellist=[];
    try:
        content ="";
        devicelist =[];
        pipeinfo ={};
        pipeinfo["state"] = "DeviceList";
        
        
        clearbufferflag = False;
        time.sleep(1);

        sys.stdout.flush()
        
        print(json.dumps(pipeinfo), file=childprocess[username][Provider].stdin, flush=True)
        sys.stdout.flush()
        
        while True:
            time.sleep(1)
            content = childprocess[username][Provider].stdout.readline()
            print("DeviceList in groupmanual: ", content)
            print("type(content)", type(content))
            if content.find("DeviceList") != -1 and content.find("state") != -1:
                #print("DeviceList in groupmanual:",content)
                content = json.loads(content);
                #print("DeviceList:",content["result"])
                sys.stdout.flush()
                #print("type(content)",type(content))
                break;
            
        #print("devicemodellist: ", content["result"])
        
        for k,v in content["result"].items():
            print("content(result) itmes:", k, v)
            if(v.get("DeviceModel") != None and len(v.get("DfList")) > 0):
                devicemodellist.append(v["DeviceModel"]);
        
        devicemodellist = sorted(devicemodellist);			
        clearbufferflag = True;
        
        result["type"] = "Sucess";
        result["devicegrouplist"] =list(devicegrouplist);
        result["devicemodellist"] = list(devicemodellist);
        #return jsonify(result = result)
    except Exception as e:
        print("e ", e)
        traceback.print_exc(file=open('debug.txt','a+'))
        result["type"] = "Error";
        result["devicegrouplist"] =list(devicegrouplist);
        #return jsonify(result = result)

    print("result:", result)
    # 當呼叫GroupManual.html 會在html呼叫IMEIListofModelGet
    # 自動將imei與model對應資訊，存入web.db 
    return render_template('GroupManual.html',result = result)

@app.route('/DeviceModelListGet')
def DeviceModelListGet():
    print("DeviceModelListGet")
    
    global childprocess

    try:
        content ="";
        pipeinfo ={};
        pipeinfo["state"] = "DeviceList";
        
        devicemodellist=[];
    
        clearbufferflag = False;
        time.sleep(1);

        print(json.dumps(pipeinfo), file=childprocess[session['logged_in']][session['provider']].stdin, flush=True)
        sys.stdout.flush()

        while True:
            time.sleep(1)
            content = childprocess[session['logged_in']][session['provider']].stdout.readline()
            print("DeviceList in devicemodellistget: ", content)
            print("type(content)", type(content))
            if content.find("DeviceList") != -1 and content.find("state") != -1:
                #print("DeviceList in devicemodellistget:",content)
                content = json.loads(content);
                print("DeviceList : ",content["result"])
                sys.stdout.flush()
                #print("type(content)",type(content))
                break;
        #print("DeviceModelListGet3")		
                
        for k,v in content["result"].items():
            #print("DeviceModelListGet3:",v.get("DeviceModel") ,len(v.get("DfList")))
            if(v.get("DeviceModel") != None and len(v.get("DfList")) > 0):
                devicemodellist.append(v["DeviceModel"]);
                        
        clearbufferflag = True;
        #print("devicemodellist: ",devicemodellist)
        
        
        result ={};
        result["type"] = "Sucess";
        result["devicemodellist"] = list(devicemodellist);
        return jsonify(result = result)
    except Exception as e:
        traceback.print_exc(file=open('debug.txt','a+'))
        #print("e: ",e)
        result ={};
        result["type"] = "Error";
        return jsonify(result = result)

@app.route('/IMEIListofModelGet')
def IMEIListofModelGet():
    #if request.method == 'POST':
    print("IMEIListofModelGet")
    username = session['logged_in']
    Provider = session['provider']

    global childprocess

    try:
        DeviceModel = request.args.get('DeviceModel', "", type=str);
        content ="";
        devicelist =[];
        pipeinfo ={};
        pipeinfo["state"] = "DeviceList";
        
        clearbufferflag = False;
        time.sleep(1);
        
        print(json.dumps(pipeinfo), file=childprocess[username][Provider].stdin, flush=True)
        sys.stdout.flush()

        while True:
            time.sleep(1)
            content = childprocess[username][Provider].stdout.readline()
            print("Devicelist in IMEIListofmodelget: ", content)
            print("type(content)", type(content))
            if content.find("DeviceList") != -1 and content.find("state") != -1:
                #print("Devicelist in IMEIListofmodelget", content)
                content = json.loads(content);
                #print("DeviceList : ",content["result"])
                sys.stdout.flush()
                #print("type(content)",type(content))
                break;
        
        if session['provider'] != None:
            #print("content: ",content["result"])
            for k,v in content["result"].items():
                if v.get("DeviceModel") != None and len(v.get("DfList")) > 0:
                    if DeviceModel in v["DeviceModel"]:
                        for device in v["DeviceList"]:
                            devicequery = Device.query.filter_by(IMEI = device,devicemodel= DeviceModel,username=session['logged_in'],Provider=session['provider']).order_by(Device.IMEI).all()
                            print("devicequery : ",devicequery)
                            if(len(devicequery) == 0):
                                print("AAAAAA new device")
                                print(device)
                                print(DeviceModel)
                                new_Device = Device(
                                    IMEI = device,
                                    devicemodel= DeviceModel, 
                                    devicegroup= "",
                                    username   = session['logged_in'],
                                    Provider   = session['provider'])
                                db.session.add(new_Device)
                                db.session.commit()
            
            clearbufferflag = True;
            
            devicelistquery = Device.query.filter_by(devicemodel= DeviceModel,username=session['logged_in'],Provider=session['provider']).order_by(Device.IMEI).all()
            #devicelist.append(device);			
            if(len(devicelistquery) > 0):
                for device in devicelistquery:
                    for k,v in content["result"].items():
                        if v.get("DeviceModel") != None and v.get("DeviceModel") == DeviceModel:
                            if(device.IMEI in v["DeviceList"]):
                                devicelist.append({"IMEI":device.IMEI,"devicegroup": device.devicegroup});
            #print("DeviceList : ",devicelist)

        result ={};
        result["devicelist"] = list(devicelist);
    except Exception as e:
        traceback.print_exc(file=open('debug.txt','a+'))
        #print("e: ",e)
        result ={};
        result["type"] = "Error";

    return jsonify(result = result)

# 取得使用者點選的device group的內容
@app.route('/DeviceGroupGet')
def DeviceGroupGet():
    print("DeviceGroupGet")
    #if request.method == 'POST':
    DeviceModelstr = request.args.get('DeviceModel', "", type=str);
    DeviceGroupstr = request.args.get('DeviceGroup', "", type=str);
    
    #print("DeviceModelstr : ",DeviceModelstr)
    #print("DeviceGroupstr : ",DeviceGroupstr)
    
    group = DeviceGroup.query.filter_by(devicemodel = DeviceModelstr,devicegroup = DeviceGroupstr,username=session['logged_in'],Provider=session['provider']).order_by(DeviceGroup.devicegroup).first()
    
    DeviceModelstr = group.devicemodel;
    DeviceGroupstr = group.devicegroup;
    Lat = group.Lat;
    Lng = group.Lng;
    
    result ={};
    result["DeviceModel"] = DeviceModelstr;
    result["DeviceGroup"] = DeviceGroupstr;
    result["Lat"] = Lat;
    result["Lng"] = Lng;
    
    return jsonify(result = result)

# 取得DeviceGroupList
@app.route('/DeviceGroupListGet')
def DeviceGroupListGet():
    print("Device Group List Get")
    #if request.method == 'POST':
    time.sleep(2);
    groups = DeviceGroup.query.filter_by(username=session['logged_in'],Provider=session['provider']).order_by(DeviceGroup.devicegroup).all()
    
    devicegrouplist=[];
    
    if(len(groups) > 0):
        for group in groups:
            devicegrouplist.append({'DeviceGroup':group.devicegroup,'DeviceModel':group.devicemodel});
    
    result ={};
    result["devicegrouplist"] = list(devicegrouplist);
    return jsonify(result = result)

@app.route('/DeviceGroupSave')
def DeviceGroupSave():
    print("DeviceGroupSave")
    global clearbufferflag;
    global childprocess
    #if request.method == 'POST':
    DeviceModelstr = request.args.get('DeviceModel', "", type=str);
    DeviceGroupstr = request.args.get('DeviceGroup', "", type=str);
    Lat = request.args.get('Lat', "", type=float);
    Lng = request.args.get('Lng', "", type=float);
    IMEIList = request.args.get('IMEIList', type=str);
    IMEIList = json.loads(IMEIList);
    oldDeviceModelstr = request.args.get('oldDeviceModel', "", type=str);
    oldDeviceGroupstr = request.args.get('oldDeviceGroup', "", type=str);
    
    group =None;
    if oldDeviceModelstr == "" and oldDeviceGroupstr == "":
        group = DeviceGroup.query.filter_by(devicemodel = DeviceModelstr,devicegroup = DeviceGroupstr,username=session['logged_in'],Provider=session['provider']).order_by(DeviceGroup.devicegroup).first()
    elif oldDeviceModelstr != "" and oldDeviceGroupstr != "":
        print("oldDeviceModelstr: ",oldDeviceModelstr)
        print("oldDeviceGroupstr: ",oldDeviceGroupstr)
        group = DeviceGroup.query.filter_by(devicemodel = oldDeviceModelstr,devicegroup = oldDeviceGroupstr,username=session['logged_in'],Provider=session['provider']).order_by(DeviceGroup.devicegroup).first()
    
    #group = DeviceGroup.query.filter_by(devicemodel = DeviceModelstr,devicegroup = DeviceGroupstr,username=session['logged_in'],Provider=session['provider']).order_by(DeviceGroup.devicegroup).first()
    
    if group is None:
        new_DeviceGroup = DeviceGroup(
            devicemodel=DeviceModelstr,
            devicegroup=DeviceGroupstr,
            Lat=Lat,
            Lng=Lng, 
            username=session['logged_in'], 
            Provider=session['provider'])
        db.session.add(new_DeviceGroup);
        db.session.commit()
    else:
        # 表示資料庫有old model, old group pair 
        if(oldDeviceGroupstr != ""):
            
            groupold = DeviceGroup.query.filter_by(devicemodel = DeviceModelstr,devicegroup = DeviceGroupstr,username=session['logged_in'],Provider=session['provider']).order_by(DeviceGroup.devicegroup).first()
            # 這時，用new model, new group pair也在資料庫找到(is not none) 並且 
            # 表示
            # 待測試!= 或 ==
            if groupold is not None and DeviceGroupstr == oldDeviceGroupstr:	 
                print("The group name already exists in this model")
                result ={};
                result["status"] = "The group name already exists in this model";
                return jsonify(result = result)
        
        group.devicemodel=DeviceModelstr;
        group.devicegroup=DeviceGroupstr; 
        group.Lat=Lat;
        group.Lng=Lng;
        group.username=session['logged_in'];
        group.Provider=session['provider'];
        db.session.commit();
    
    if(oldDeviceGroupstr != ""):
        devicelistquery = Device.query.filter(Device.devicegroup.like('%'+oldDeviceGroupstr+'%')).filter_by(devicemodel= DeviceModelstr,username=session['logged_in'],Provider=session['provider']).order_by(Device.IMEI).all()
        if(len(devicelistquery) > 0):
            # 更新web.db裡的group name
            for device in devicelistquery:
                #print("Device.IMEI",device.IMEI)
                devicequerygroupstrold = device.devicegroup;
                devicequerygroupstrnew = devicequerygroupstrold.replace(oldDeviceGroupstr+",", "");
                device.devicegroup = devicequerygroupstrnew;
                db.session.commit();
                
                #print("devicequerygroupstrold",devicequerygroupstrold)
                #print("devicequerygroupstrnew",devicequerygroupstrnew) 
    
    # 遍歷所勾選的imei
    #print
    IMEIList = []
    if DeviceModelstr == "RoadSensor":
        for i in range(1,8):
            tmp = 'sensor1-devicetest' + str(i) + '@140.114.77.83'
            IMEIList.append(tmp)
    if DeviceModelstr == "ElecMap":
        for i in range(1,8):
            tmp2 = 'actuator1-deviceatest' + str(i) + '@140.114.77.83'
            IMEIList.append(tmp2)
    if DeviceModelstr == "FrontImage":
        for i in range(1,8):
            tmp = 'sensor2-devicetest' + str(i) + '@140.114.77.83'
            IMEIList.append(tmp)
    if DeviceModelstr == "PreImage":
        for i in range(1,8):
            tmp2 = 'actuator2-deviceatest' + str(i) + '@140.114.77.83'
            IMEIList.append(tmp2)
    if DeviceModelstr == "AudioSession":
        print("---------------------------")
        print("this is device audio session i")
        for i in range(1, 8):
            tmp = 'sensor1-devicetest' + str(i) + '@140.114.77.83'
            IMEIList.append(tmp)
    if DeviceModelstr == "ClipDetect":
        print("---------------------------")
        print("this is device audio session o")
        for i in range(1, 8):
            tmp2 = 'actuator1-deviceatest' + str(i) + '@140.114.77.83'
            IMEIList.append(tmp2)

    print("IMEIList=")
    print(IMEIList)
    for IMEI in IMEIList:
        devicequery = Device.query.filter_by(IMEI = IMEI,devicemodel= DeviceModelstr,username=session['logged_in'],Provider=session['provider']).order_by(Device.IMEI).first()
        print("devicequery : ",devicequery)
        # 如果不在group中，就加入（存web.db）
        if(DeviceGroupstr not in devicequery.devicegroup):
            #print("devicequery.devicegroup + DeviceGroupstr +','",devicequery.devicegroup + DeviceGroupstr +",")
            devicequery.devicegroup = devicequery.devicegroup + DeviceGroupstr +",";
            db.session.commit()	  
    
    print("oldDeviceGroupstr: ",oldDeviceGroupstr);
    print("DeviceGroupstr: ",DeviceGroupstr);
    print("oldDeviceModelstr: ",oldDeviceModelstr);
    print("DeviceModelstr: ",DeviceModelstr);

    ## save IDG/ODG mapping for the user
    global group_count
    group_count = group_count + 1
    try:
        Providerdbpath = "./sqlite/" + \
            session.get('logged_in') + "_" + session.get('provider') + ".db"
        Providerdb = sqlite3.connect(Providerdbpath)
        create_tb_cmd = "CREATE TABLE IF NOT EXISTS GroupMapping (ID TEXT,DGName TEXT,DG TEXT)"
        Providerdb.execute(create_tb_cmd)
        if (group_count % 2) == 1: 
            IDG_ODG = "IDG"
        else:
            IDG_ODG = "ODG"
        Providerdb.execute("INSERT INTO GroupMapping (ID,DGName,DG) VALUES ('" + str(group_count) + "','" + str(DeviceGroupstr) + "','" + str(IDG_ODG) + "')")
        Providerdb.commit()
        Providerdb.close()
    except Exception as e:
        traceback.print_exc(file=open('debug.txt','a+'))
        print("Handle GroupMapping table failed")
        print(e)
        Providerdb.close()
    
    # 如果有舊的跟新的資料不同，則反註冊
    if DeviceModelstr != oldDeviceModelstr or DeviceGroupstr != oldDeviceGroupstr:
        pipeinfo ={};	
        pipeinfo["state"] = "Deregister";
        pipeinfo["result"] = {"DeviceModel": oldDeviceModelstr,"DeviceGroup": oldDeviceGroupstr};
        #print("Deregister:")
        #print("pipeinfo:",pipeinfo)
        
        clearbufferflag = False;
        time.sleep(1);
        
        print(json.dumps(pipeinfo), file=childprocess[session['logged_in']][session['provider']].stdin, flush=True);
        sys.stdout.flush()
        while True:
            content = childprocess[session['logged_in']][session['provider']].stdout.readline()
            print("Deregister in devicegroupsave: ", content)
            print("type(content)", type(content))
            if content.find("Deregister") != -1 and content.find("state") != -1:
                #print("Deregister in devicegroupsave:", content)
                content = json.loads(content);
                #print("DA Deregister State : ",content["result"])
                sys.stdout.flush()
                #print("type(content)",type(content))
                break
            
        clearbufferflag = True;
             
    time.sleep(3);
    
    pipeinfo ={};
    pipeinfo["state"] = "Register";
    DeviceList = list(IMEIList);
    #if session['provider']=="NHR":
    if session['provider'] != None:
        DeviceGroupinfo ={"DeviceModel": DeviceModelstr,"DeviceGroup": DeviceGroupstr ,"DeviceList":None};
        DeviceGroupinfo["RegisterModel"] = "SIP";
        DeviceGroupinfo["DeviceList"] = list(DeviceList);
    
    DeviceGroupinfo["Lat"] = Lat;
    DeviceGroupinfo["Lng"] = Lng;			
    
    #pipeinfo["result"] = dict(DeviceGroupinfo)
    pipeinfo["result"] = DeviceGroupinfo.copy();
    #print("Register:")
    #print("pipeinfo:",pipeinfo)
    
    clearbufferflag = False;
    time.sleep(1);
    #print("Register1")
    print(json.dumps(pipeinfo), file=childprocess[session['logged_in']][session['provider']].stdin, flush=True);
    sys.stdout.flush()
    while True:
        content = childprocess[session['logged_in']][session['provider']].stdout.readline()
        print("register in devicegroupsave: ", content)
        print("type(content)", type(content))
        #print("DA Register State : ",content)
        if content.find("Register") != -1 and content.find("state") != -1:
            #print("register in devicegroupsave:", content)
            content = json.loads(content);
            sys.stdout.flush()
            break	
    #print("Register2")	
    clearbufferflag = True;
    
    result ={};
    result["status"] = "Sucess";
    # 回傳sucess到groupmanual，會再執行一次group get 更新看到的畫面
    return jsonify(result = result)

@app.route('/DeviceGroupPush')
def DeviceGroupPush():
    print("DeviceGroupPush")

    webdbpath = "./sqlite/web.db"
    dbpath = "./sqlite/siptalk_SIP.db"
    webdb = sqlite3.connect(webdbpath)
    deviceList = webdb.execute("SELECT IMEI, devicegroup FROM Device")
    deviceList = list(deviceList)
    print("deviceList: ")
    print(deviceList)
    webdb.commit()

    devicedb = sqlite3.connect(dbpath)
    deviceprofileList = devicedb.execute("SELECT IMEI, devicefeature FROM DeviceProfile")
    deviceprofileList = list(deviceprofileList)
    devicedb.commit()

    for item in deviceprofileList:
        print(item)
        if(str(item[1])=="AudioSession-I"):
            df = item[1]
            for item2 in deviceList:
                if item[0] in item2[0]:  
                    group = item2[1]
                    group = group.split(",")
                    group = group[0]
                    mac = "SIP-" + group
            data_array = ["7001@140.114.77.83","123123","140.114.77.84:5566",str(group)]
            params={"data": data_array}
            body=json.dumps(params)
            headers={"Content-Type": "application/json"}
            r = requests.put("http://" + IoTtalkServer + ":" + IoTtalkServerPort +"/" +mac+"/"+df, headers = headers, data = body)
            print("mac:" + mac)
            print(r)
    

    result ={};
    result["status"] = "Sucess";
    return jsonify(result = result)

@app.route('/DeviceGroupDelete')
def DeviceGroupDelete():
    print("DeviceGroupDelete")
    global clearbufferflag;
    global childprocess
    #if request.method == 'POST':
    DeviceModelstr = request.args.get('DeviceModel', "", type=str);
    DeviceGroupstr = request.args.get('DeviceGroup', "", type=str);
    IMEIList = request.args.get('IMEIList', type=str);
    IMEIList = json.loads(IMEIList);
    
    DeviceGroup.query.filter_by(devicemodel = DeviceModelstr,devicegroup = DeviceGroupstr,username=session['logged_in'],Provider=session['provider']).delete()
    db.session.commit()
    
    for IMEI in IMEIList:
        devicequery = Device.query.filter(Device.devicegroup.like('%'+DeviceGroupstr+'%')).filter_by(devicemodel = DeviceModelstr,IMEI = IMEI,username=session['logged_in'],Provider=session['provider']).order_by(Device.IMEI).first()
        
        devicequerygroupstrold = devicequery.devicegroup;
        devicequerygroupstrnew = devicequerygroupstrold.replace(DeviceGroupstr+",", "");
        devicequery.devicegroup = devicequerygroupstrnew;
        db.session.commit();
        #print("devicequerygroupstrold",devicequerygroupstrold)
        #print("devicequerygroupstrnew",devicequerygroupstrnew)   
    
    pipeinfo ={};	
    pipeinfo["state"] = "Deregister";
    pipeinfo["result"] = {"DeviceModel": DeviceModelstr,"DeviceGroup": DeviceGroupstr}
    
    clearbufferflag = False;
    time.sleep(1);
    
    print(json.dumps(pipeinfo), file=childprocess[session['logged_in']][session['provider']].stdin, flush=True);
    sys.stdout.flush()
    while True:
        content = childprocess[session['logged_in']][session['provider']].stdout.readline()
        print("Deregister in devicegroupdelete: ", content)
        print("type(content)", type(content))
        if content.find("Deregister") != -1 and content.find("state") != -1:
            #print("Deregister in devicegroupdelete", content)
            content = json.loads(content);
            #print("DA Deregister State : ",content["result"])
            sys.stdout.flush()
            #print("type(content)",type(content))
            break
    
    clearbufferflag = True;
    
    result ={};
    result["status"] = "Sucess";
    return jsonify(result = result)
    
# methods 可能是get, post
@app.route('/', methods=['GET', 'POST'])
def home():
    """ Session control"""
    if session.get('logged_in'):
        if 'IDAExecution' in session:
            del session['IDAExecution']
        if 'provider' in session:
            del session['provider']
        
        return render_template('index.html')
        
    else:
        return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login Form"""
    if request.method == 'GET':
        print("login by GET method!")
        if session.get('logged_in'):
            return redirect(url_for('hello', username=session['logged_in']))
        #else:
        #	return render_template('login.html')
    else:
        # post表示請求 此處表示請求登入
        name = request.form['username'] # html post form
        passwd = request.form['password']
        # 檢查帳號
        data = User.query.filter_by(username=name).first()
        if data is None:
            return 'User does not exist'

        try:
            # 進一步檢查密碼
            data = User.query.filter_by(username=name, password=passwd).first()
            if data is not None:
                session['logged_in'] = name
                return redirect(url_for('home'))
            else:
                return 'Wrong Password'
        except:
            return "Dont Login"


@app.route('/register', methods=['GET', 'POST'])
def register():
    # 網站註冊
    """Register Form"""
    if request.method == 'POST':
        name = request.form['username']
        if not name:
            # check if string is empty
            # 這些return都是網頁呈現，所以 單純return文字的話，就是畫面顯示文字而已
            return 'username is empty'

        data = User.query.filter_by(username=name).first()
        if data is not None:
            return 'User exists!'

        #usr_passwd = generate_password_hash(request.form['password'])
        usr_passwd = request.form['password']
        new_user = User(username=name, password=usr_passwd)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('home'))
        #return render_template('index.html')

    return render_template('register.html')
    #return render_template('index.html')


@app.route("/logout")
def logout():
    """Logout Form"""
    if 'logged_in' in session:
        # 使用del可以删除一个元素，当元素删除之后，位于它后面的元素会自动移动填补空出来的位置。
        del session['logged_in']
    if 'provider' in session:
        del session['provider']
    if 'IDAExecution' in session:
        del session['IDAExecution']

    return redirect(url_for('home'))


def raw(text):
    """Returns a raw string representation of text"""
    escape_dict={'\a':r'\a',
             '\b':r'\b',
           '\c':r'\c',
           '\f':r'\f',
           '\n':r'\n',
           '\r':r'\r',
           '\t':r'\t',
           '\v':r'\v',
           '\'':r'\'',
           '\"':r'\"',
           '\0':r'\0',
           '\1':r'\1',
           '\2':r'\2',
           '\3':r'\3',
           '\4':r'\4',
           '\5':r'\5',
           '\6':r'\6',
           '\7':r'\7',
           '\8':r'\8',
           '\9':r'\9'}
    new_string=''
    for char in text:
        try: 
            new_string+=escape_dict[char]
        except KeyError: 
            #traceback.print_exc(file=open('debug.txt','a+'))
            new_string+=char
    return new_string

'''
def clear_buffer():
    from nbstreamreader import NonBlockingStreamReader as NBSR
    global childprocess
    global clearbufferflag

    while True:
        providers = ServiceProvider.query.all()
        for provider in providers:
            index = 0
            while True:
                time.sleep(1)
                index = index + 1
                if(clearbufferflag):
                    # clearbufferflag
                    if provider.username in childprocess.keys():
                        if provider.Provider in childprocess[provider.username].keys():
                            #print("provider.Provider : ",provider.Provider)
                            if childprocess[provider.username][provider.Provider].poll() is not None:
                                content = childprocess[provider.username][provider.Provider].stdout.readline()
                                print("provider.Provider : ",provider.Provider)
                                print("content : ", content)
                            else:
                                print('[No more data]');
                                break
                    #print(output)

                    #print("IDA Execution State : ",content)
                    #if content.find("ExecutionState") != -1:
                    if index > 10:
                        #content = json.loads(content);
                        #print(content)
                        #time.sleep(1);
                        #print("type(content)",type(content))
                        break
                else:
                    time.sleep(1)
                    continue

            time.sleep(1)
        time.sleep(60)
'''

if __name__ == '__main__':
    global childprocess
    global clearbufferflag
    childprocess = {}
    #with app.app_context():
        #print("lol")
        #exit()
    db.create_all()

    global group_count
    group_count = 0

    providers = ServiceProvider.query.all()

    clearbufferflag = False
    time.sleep(1)
    for provider in providers:
        if(provider.Provider != None):
            if provider.ExecutionState != "Success":
                continue
            if provider.username not in childprocess.keys():
                childprocess[provider.username] = {}
            if provider.Provider not in childprocess[provider.username].keys():
                print("provider.Provider:"+provider.Provider)
                user = provider.username
                user.strip()
                filename = raw(provider.Provider+'_IDA.py')
                script = ["python3", filename, user]
                #script = ["python2.7", filename, user]
                childprocess[provider.username][provider.Provider] = subprocess.Popen(" ".join(script), shell=True, env={"PYTHONPATH": "."}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True, bufsize=65535)

                executionstate = ""
                
                time.sleep(5)
                pipeinfo = {}
                pipeinfo["state"] = "ExecutionState"
                try:
                    print(json.dumps(pipeinfo), file=childprocess[provider.username][provider.Provider].stdin, flush=True)
                    sys.stdout.flush()
                except OSError as e:
                    traceback.print_exc(file=open('debug.txt','a+'))
                    stre = str(e)
                    print("OSError")
                    sys.stdout.flush()
                    while True:
                        content = childprocess[provider.username][provider.Provider].stdout.readline(
                        )
                        if content.find("ExecutionState") != -1 and content.find("state") != -1:
                            content = json.loads(content)
                            executionstate = content["result"]
                            break
                        provider.ExecutionState = executionstate  # provider是資料庫的部分
                        db.session.commit()
                    del childprocess[provider.username][provider.Provider]
                    continue
                
                while True:
                    content = childprocess[provider.username][provider.Provider].stdout.readline()
                    if content.find("ExecutionState") != -1 and content.find("state") != -1:
                        print("Executionstate in main:", content)
                        content = json.loads(content)
                        break
                
                time.sleep(5)
                

    clearbufferflag = True
    
    
    print("Main Web Start");
    # 加密
    app.secret_key="123"
    # 網頁開啟
    app.run('0.0.0.0', port=int("11100"),debug=False, threaded=True)
    #app.run('0.0.0.0', port=int(NBIoTtalkPort), debug=False, threaded=True)
