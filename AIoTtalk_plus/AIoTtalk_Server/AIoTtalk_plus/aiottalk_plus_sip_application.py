import urllib.request, urllib.parse, urllib.error
import os
import re
import signal
import sys

import random
import requests
import uuid

from collections import defaultdict
from datetime import datetime, timedelta
from dateutil.tz import tzlocal
from itertools import chain
from lxml import html
from optparse import OptionParser
from threading import Event, Thread
from time import sleep

from application import log
from application.notification import IObserver, NotificationCenter
from application.python.queue import EventQueue
from application.python import Null
from eventlib import api

from gnutls.errors import GNUTLSError
from gnutls.crypto import X509Certificate, X509PrivateKey

from twisted.internet import reactor
from zope.interface import implementer

from otr import OTRTransport, OTRState, SMPStatus
from otr.exceptions import IgnoreMessage, UnencryptedMessage, EncryptedMessageError, OTRError, OTRFinishedError

from sipsimple.core import Engine, FromHeader, Message, RouteHeader, SIPCoreError, SIPURI, ToHeader

from sipsimple.account import Account, AccountManager, BonjourAccount
from sipsimple.application import SIPApplication
from sipsimple.audio import WavePlayer
from sipsimple.configuration import ConfigurationError
from sipsimple.configuration.settings import SIPSimpleSettings
from sipsimple.core import Route
from sipsimple.core import CORE_REVISION, PJ_VERSION, PJ_SVN_REVISION
from sipsimple import __version__ as version
from sipsimple.lookup import DNSLookup
from sipsimple.payloads.iscomposing import IsComposingMessage, IsComposingDocument
from sipsimple.session import IllegalStateError, Session
from sipsimple.session import IllegalDirectionError
from sipsimple.streams import MediaStreamRegistry
from sipsimple.streams.msrp.filetransfer import FileSelector
from sipsimple.streams.msrp.chat import CPIMPayload, CPIMHeader, CPIMNamespace, SimplePayload, CPIMParserError, ChatIdentity, OTREncryption
from sipsimple.payloads.imdn import IMDNDocument, DisplayNotification, DeliveryNotification

from sipsimple.storage import FileStorage
from sipsimple.threading.green import run_in_green_thread
from sipsimple.util import ISOTimestamp

from sipclient.configuration import config_directory
from sipclient.configuration.account import AccountExtension, BonjourAccountExtension
from sipclient.configuration.datatypes import ResourcePath
from sipclient.configuration.settings import SIPSimpleSettingsExtension
from sipclient.log import Logger
from sipclient.system import IPAddressMonitor, copy_default_certificates
from sipclient.ui import Prompt, Question, RichText, UI

import requests, json
import queue
import multiprocessing
import threading
from sipsimple.threading import run_in_twisted_thread
from sipsimple.core import SDPMediaStream, SDPAttribute, SDPSession, SDPConnection
from utils.Thread import run_in_thread
from utils.sdp_process import parse_sdp

IoTtalkServer = "140.114.77.93"
IoTtalkServerPort = "9999"

sessions_list = {}
sessions_lock = threading.Lock()

class AIoTtalk_plus_SIPApplication(SIPApplication):
    def __init__(self):
        self.account = None
        self.sessions = {}
        self.sessions_lock = threading.Lock()
        self.config_directory = None
        self.registration_succeeded = False
    
    def start(self, register=False):
        self.register = register

        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=self)

        notification_center.add_observer(self, name='SIPSessionNewIncoming')
        notification_center.add_observer(self, name='SIPSessionDidStart')
        notification_center.add_observer(self, name='SIPSessionDidEnd')
        Account.register_extension(AccountExtension)
        BonjourAccount.register_extension(BonjourAccountExtension)
        SIPSimpleSettings.register_extension(SIPSimpleSettingsExtension)
        
        try:
            SIPApplication.start(self, FileStorage("./sip_accounts"))
        except ConfigurationError as e:
            print("Failed to load sipclient's configuration: %s\n" % str(e))


    #---- notification handlers ----#
    def _NH_SIPApplicationWillStart(self, notification):
        print('notification handler: SIPApplicationWillStart')

        account_manager = AccountManager()
        notification_center = NotificationCenter()
        settings = SIPSimpleSettings()

        for account in account_manager.iter_accounts():
            if isinstance(account, Account):
                account.sip.register = False
                account.presence.enabled = False
                account.xcap.enabled = False
                account.message_summary.enabled = False
            notification_center.add_observer(self, sender=account)
             
        possible_accounts = [account for account in account_manager.iter_accounts() if self.account in account.id and account.enabled]
        if len(possible_accounts) > 1:
            print('More than one account exists which matches %s: %s' % (self.account, ', '.join(sorted(account.id for account in possible_accounts))))
            self.stop()
            return
        elif len(possible_accounts) == 0:
            print('No enabled account which matches %s was found. Available and enabled accounts: %s' % (self.options.account, ', '.join(sorted(account.id for account in account_manager.get_accounts() if account.enabled))))
            self.stop()
            return
        else:
            self.account = possible_accounts[0]
        
        
        if self.register == True:
            if isinstance(self.account, Account):
                self.account.sip.register = True
        print('Using account %s' % self.account.id)
        
    def _NH_SIPApplicationDidStart(self, notification):
        print("notification handler: SIPApplicationDidStart!")
        #sleep(2)
        self.get_sdp_answer_thread("SIPSignalingHandler", "SDPAnswer-O")

    def _NH_SIPAccountRegistrationDidSucceed(self, notification):
        print("notification handler: SIPAccountRegistrationDidSucceed!")
        
        if self.registration_succeeded:
            return
        contact_header = notification.data.contact_header
        contact_header_list = notification.data.contact_header_list
        expires = notification.data.expires
        registrar = notification.data.registrar

    def _NH_SIPAccountRegistrationDidFail(self, notification):
        print("notification handler: SIPAccountRegistrationDidFail!")
        print("SIP account registration failed")
        pass
    
    def _NH_SIPAccountRegistrationDidEnd(self, notification):
        print("notification handler: SIPAccountRegistrationDidEnd!")
        pass
    
    def _NH_SIPSessionNewIncoming(self, notification):
        
        notification_center = NotificationCenter()
        print("notification handler: SIPSessionNewIncoming!")
        
        ''' Extract the session and the sip account '''
        session = notification.sender
        sip_header = session._invitation.from_header
        sip_device_id  = re.search(r'([\w.-]+@[\w.-]+)', str(sip_header))
        sip_device_id  = sip_device_id.group(0)
        
        session.sip_device_id = sip_device_id
        # device_sip_account = str(session._invitation.from_header)
        # device_sip_account = re.split('[<,>]', device_sip_account)[1]
        
        try:
            sessions_lock.acquire()
            self.sessions[sip_device_id] = session
            print(self.sessions)
        finally:
            sessions_lock.release()
        
        notification_center.add_observer(self, sender=session)
        print("Entering SIPSessionNewIncoming handler for session: {}".format(sip_device_id))
        session.my_accept("SIPSignalingHandler", "SDPOffer-I")
        pass
    
    def _NH_SIPSessionWillStart(self, notification):
        print("notification handler: SIPSessionWillStart!")
        pass

    def _NH_SIPSessionDidStart(self, notification):
        print("notification handler: SIPSessionDidStart")
        session = notification.sender
        pass

    def _NH_SIPSessionWillEnd(self, notification):
        print('notification handler: SIPSessionWillEnd')
        session = notification.sender
        session.terminate_session("SIPSignalingHandler", "SDPOffer-I")

    def _NH_SIPSessionDidEnd(self, notification):
        print('notification handler: SIPSessionDidEnd')
        notification_center = NotificationCenter()
        session = notification.sender
        sip_device_id = session.sip_device_id
        # device_sip_account = str(session._invitation.from_header)
        # device_sip_account = re.split('[<,>]', device_sip_account)[1]
        print("Disconnect Session Device: {}".format(sip_device_id))
        
        # session = notification.sender
        notification_center.discard_observer(self, sender=session)
        
        try:
            self.sessions_lock.acquire()
            print("sessions: {}".format(str(self.sessions)))
            del(self.sessions[sip_device_id])
            del(session)
            print("sessions: {}".format(str(self.sessions)))
            #self.sessions[] = session
        finally:
            self.sessions_lock.release()
    
    
    @run_in_thread
    def get_sdp_answer_thread(self, mac, device_feature):    
        print("Start get_sdp_answer_thread")

        pre_message = []
        while(True):
            response = requests.get(
                "http://" + IoTtalkServer + ":" + IoTtalkServerPort + "/" + mac + "/" +device_feature
            )
            if(response.status_code != 200):
                print("IoTtalk get_sdp_response thread failed, code: {}, reason: {}".format(response.status_code, response.text))
            else:
                content = eval(response.text)
                if(len(content['samples']) > 0):
                    message = content['samples'][0][1]
                    if(message != pre_message):
                        pre_message = message
                        try:
                            sip_device_id= message[0]
                            device_sdp = message[1]

                            print(sip_device_id)
                            print(device_sdp)
                            self.sessions_lock.acquire()
                            session = self.sessions.get(sip_device_id)
                        finally:
                            self.sessions_lock.release()

                        if session:
                            _, device_sdp = parse_sdp(device_sdp)
                            # device_sdp = self.process_sdp(device_sdp)
                            #print("device_sdp------=============================-----")
                            #print(device_sdp)
                            #print("device_sdp------=============================-----")
                            #print(device_sdp)
                            if(session.is_connected != True):
                                print("Init Session for SIP device: {}".format(sip_device_id))
                                session.init_session(device_sdp)
                            else:
                                #session.update_sdp(session_sdp)
                                session.update_sdp(device_sdp)

            sleep(0.05)
    
    # def process_sdp(self, sdp):
    #     parse_sdp = sdp.split("m=")
    #     #print(parse_sdp)
    #     parse_sdp[0] = parse_sdp[0].splitlines()
    #     #print(parse_sdp[1])
    #     media_streams = [parse_sdp[index] for index in range(1, len(parse_sdp))]
    #     for line in parse_sdp[0]:
    #         param, value = line.split("=")
    #         if param == "v":
    #             sdp_version = value
    #         elif param == "o":
    #             origin_identifier = value
    #             sdp_name = value.split(' ')[0]
    #             sdp_local_ip = value.split(' ')[5]
    #         elif param == "s":
    #             session_name = value
    #         elif param == "t":
    #             session_time = value
    #         elif param == "c":
    #             sdp_conn = value
        
    #     session_sdp = SDPSession(sdp_local_ip.encode(), name=session_name.encode())
    #     for media_stream in media_streams:
    #         media_info = media_stream.splitlines()
    #         attr_m = media_info[0].split(' ')
    #         attr_c = media_info[1].split('c=')[1].split(' ')
    #         attr_a = [media_info[index].split('a=')[1].split(':') for index in range(2, len(media_info))]
    #         sdp_media = SDPMediaStream(attr_m[0].encode(), int(attr_m[1]), attr_m[2].encode())
    #         sdp_media.formats = [attr_m[3].encode()]
    #         connection = SDPConnection(attr_c[2].encode())
    #         sdp_media.connection = connection
    #         attribute_list = []
    #         for attribute in attr_a:
    #             if len(attribute) == 1:
    #                 param, value = attribute[0], ''
    #                 #print(attribute[0])
    #             else:
    #                 param, value = attribute[0], attribute[1]
    #             attribute_list.append(SDPAttribute(param.encode(), value.encode()))
    #         sdp_media.attributes = attribute_list    
    #         session_sdp.media.append(sdp_media)
        
        return session_sdp

# if __name__ == '__main__':
#     sip_session_application = AIoTtalk_plus_SIPApplication()
#     sip_session_application.start("siptalktest@127.0.0.1", True)
