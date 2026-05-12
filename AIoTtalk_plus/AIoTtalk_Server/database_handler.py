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


#webdbpath = "./ManagementWeb/sqlite/web.db"
#sipdbpath = "./ManagementWeb/sqlite/siptalk_SIP.db"
# devicedbpath = "./ManagementWeb2/sqlite/siptalk_SIP.db"
# webdbpath = "./ManagementWeb2/sqlite/web.db"
# dbpath = "./ManagementWeb2/sqlite/siptalk_SIP.db"


def lookupODGODF(dbpath, webdbpath):
    #global dbpath
    #global webdbpath

    ODGName = ""
    devicedb = sqlite3.connect(dbpath)
    dbcursor = devicedb.cursor()

    #get the count of tables with the name
    dbcursor.execute("SELECT count(*) FROM sqlite_master WHERE type = \'table\' AND name = \'GroupMapping\'")

    #if the count is 1, then table exists
    if dbcursor.fetchone()[0]!=1 :
        while True:
            print("Table GroupMapping doesn't exist")
            time.sleep(5)
            dbcursor.execute("SELECT count(*) FROM sqlite_master WHERE type = \'table\' AND name = \'GroupMapping\'")
            if dbcursor.fetchone()[0]==1 :
                break

    groupmappingList = devicedb.execute("SELECT DGName, DG FROM GroupMapping")
    groupmappingList = list(groupmappingList)
    devicedb.commit()

    for item in groupmappingList:
        if item[1] == "ODG":
            ODGName = item[0]
            devicegroup = item[0] + ","
    while ODGName == "":
        print("ODG doesn't exist")
        time.sleep(5)
        groupmappingList = devicedb.execute("SELECT DGName, DG FROM GroupMapping")
        groupmappingList = list(groupmappingList)
        devicedb.commit()

        for item in groupmappingList:
            if item[1] == "ODG":
                ODGName = item[0]
                devicegroup = item[0] + ","

    webdb = sqlite3.connect(webdbpath)
    deviceList = webdb.execute("SELECT devicemodel, devicegroup FROM Device")
    deviceList = list(deviceList)
    webdb.commit()

    for item in deviceList:
        if item[1] == devicegroup:
            devicemodel = item[0]
            break

    devicedb = sqlite3.connect(dbpath)
    deviceprofileList = devicedb.execute("SELECT devicemodel, devicefeature FROM DeviceProfile")
    deviceprofileList = list(deviceprofileList)
    devicedb.commit()

    for item in deviceprofileList:
        if item[0] == devicemodel:
            ODF = item[1]
            break

    return ODGName, ODF

# def lookupIDGIDF(target):
#     webdb = sqlite3.connect(webdbpath)
#     deviceList = webdb.execute("SELECT IMEI, devicegroup FROM Device")
#     deviceList = list(deviceList)
#     webdb.commit()
#     #print(deviceList)
#     for item in deviceList:
#         if item[0] == target:
#             group = item[1]
#             group = group.split(",")
#             group = group[0]
#     #print(group)
#     #exit()
#     devicedb = sqlite3.connect(dbpath)
#     deviceprofileList = devicedb.execute("SELECT IMEI, devicefeature FROM DeviceProfile")
#     deviceprofileList = list(deviceprofileList)
#     devicedb.commit()
#     #print(deviceprofileList)
#     for item in deviceprofileList:
#         if item[0] == target:
#             df = item[1]

#     return df, group

prefix = "./ManagementWeb/sqlite/"
class Database_Handler(object):
    def __init__(self, _webdbpath, _devicedbpath):
        self.webdbpath = prefix + _webdbpath
        self.devicedbpath = prefix + _devicedbpath
        self.webdb_connection = sqlite3.connect(self.webdbpath)
        self.devicedb_connection = sqlite3.connect(self.devicedbpath)
        self.webdb_cursor = self.webdb_connection.cursor()
        self.devicedb_cursor = self.devicedb_connection.cursor()

    def lookup_webdb(self, command):
        result = self.webdb_cursor.execute(command)
        self.webdb_connection.commit()
        return result
    
    def lookup_devicedb(self, command):
        result = self.devicedb_cursor.execute(command)
        self.devicedb_connection.commit()
        return result
    
    def get_ODG_ODF(self):
        return lookupODGODF(self.devicedbpath, self.webdbpath)
# if __name__ == "__main__":

#     db = Database_Handler("web.db", "siptalk_SIP.db")

#     a, b = db.get_odg_odf()
#     print(a, b)
#     a = db.lookup_webdb(
#         "SELECT IMEI, devicegroup FROM Device"
#     )
#     print(a)
#     a = list(a)
#     print(a)
    # b = db.lookup_devicedb(
    #     "SELECT IMEI, devicefeature FROM DeviceProfile"
    # )
    # b = list(b)
    # print(b)
    #a,b = lookupODGODF()
    #print(a, b)
    #webdb = sqlite3.connect(webdbpath)
    #dbODList = webdb.execute("SELECT IMEI, devicegroup FROM Device")
    #print(list(dbODList))
    #a, b = lookupIDGIDF("sensor1-devicetest1@140.114.77.83")
    #print(a, b)