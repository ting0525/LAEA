#!/usr/bin/python3

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

import queue
import multiprocessing

@implementer(IObserver)
class MessageSender(object):
    def __init__(self, account, target, message, routes=None):
        self.account = account
        self.target = target
        self.message = message
        self.routes = None
        self.notification_center = NotificationCenter()

    def start(self):
        if not self.target.startswith('sip:') and not self.target.startswith('sips:'):
            self.target = 'sip:' + self.target

        try:
            self.target = SIPURI.parse(self.target)
        except SIPCoreError:
            pass
            print('Illegal SIP URI: %s' % self.target)
            self.target_uri = None

        lookup = DNSLookup()
        self.notification_center.add_observer(self, sender=lookup)
        settings = SIPSimpleSettings()

        if isinstance(self.account, Account) and self.account.sip.outbound_proxy is not None:
            uri = SIPURI(host=self.account.sip.outbound_proxy.host, port=self.account.sip.outbound_proxy.port, parameters={'transport': self.account.sip.outbound_proxy.transport})
        elif isinstance(self.account, Account) and self.account.sip.always_use_my_proxy:
            uri = SIPURI(host=self.account.id.domain)
        else:
            uri = self.target
        lookup.lookup_sip_proxy(uri, settings.sip.transport_list, tls_name=self.account.sip.tls_name or uri.host)

    def _NH_DNSLookupDidSucceed(self, notification):
        self.notification_center.remove_observer(self, sender=notification.sender)
        
        self.routes = notification.data.result
        #print(self.routes)
        self._send_message()

    def _NH_DNSLookupDidFail(self, notification):
        self.notification_center.remove_observer(self, sender=notification.sender)
        self.start()

    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def _send_message(self):
        notification_center = NotificationCenter()
        #print(self.routes)
        if self.routes:
            route = self.routes.pop(0)
            identity = str(self.account.uri)
            if self.account.display_name:
                identity = '"%s" <%s>' % (self.account.display_name, identity)

            content_type = 'text/plain'

            #additional_cpim_headers = []
            additional_sip_headers = []

            payload = self.message
            settings = SIPSimpleSettings()
            from_uri = self.account.uri
            
            message_request = Message(FromHeader(from_uri, self.account.display_name), 
                                      ToHeader(self.target), 
                                      RouteHeader(route.uri), 
                                      content_type, 
                                      payload,
                                      credentials=self.account.credentials, 
                                      extra_headers=additional_sip_headers)
            
            notification_center.add_observer(self, sender=message_request)
            message_request.send()

    def _NH_SIPMessageDidSucceed(self, notification):
        data = notification.data
        #print(data.code)

    def _NH_SIPMessageDidFail(self, notification):
        #print(notification)
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)

@implementer(IObserver)
class MessageSession(object):
    def __init__(self, account, target, message, route=None):
        self.account = account
        self.target = target
        self.message = message
        self.routes = None
        self.route = None
        self.content_type = None

        if not self.target.startswith('sip:') and not self.target.startswith('sips:'):
            self.target = 'sip:' + self.target

        try:
            self.target = SIPURI.parse(self.target)
        except SIPCoreError:
            pass
            print('Illegal SIP URI: %s' % self.target)
            self.target_uri = None

        self.notification_center = NotificationCenter()

    def start(self):
        lookup = DNSLookup()
        self.notification_center.add_observer(self, sender=lookup)
        settings = SIPSimpleSettings()

        if isinstance(self.account, Account) and self.account.sip.outbound_proxy is not None:
            uri = SIPURI(host=self.account.sip.outbound_proxy.host, port=self.account.sip.outbound_proxy.port, parameters={'transport': self.account.sip.outbound_proxy.transport})
        elif isinstance(self.account, Account) and self.account.sip.always_use_my_proxy:
            uri = SIPURI(host=self.account.id.domain)
        else:
            uri = self.target
        lookup.lookup_sip_proxy(uri, settings.sip.transport_list, tls_name=self.account.sip.tls_name or uri.host)


    def _NH_DNSLookupDidSucceed(self, notification):
        self.notification_center.remove_observer(self, sender=notification.sender)

        self.routes = notification.data.result
        self._send_message()

    def _NH_DNSLookupDidFail(self, notification):
        self.notification_center.remove_observer(self, sender=notification.sender)
        self.start()

    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def send_message(self):
        if not self.routes:
            self.start()

    def _send_message(self):
        notification_center = NotificationCenter()
        print(self.routes)
        if self.routes:
            route = self.routes.pop(0)
            identity = str(self.account.uri)
            if self.account.display_name:
                identity = '"%s" <%s>' % (self.account.display_name, identity)

            content_type = self.content_type or 'text/plain'

            #additional_cpim_headers = []
            additional_sip_headers = []

            payload = self.message
            settings = SIPSimpleSettings()
            from_uri = self.account.uri
            
            message_request = Message(FromHeader(from_uri, self.account.display_name), 
                                      ToHeader(self.target), 
                                      RouteHeader(route.uri), 
                                      content_type, 
                                      payload,
                                      credentials=self.account.credentials, 
                                      extra_headers=additional_sip_headers)
            
            notification_center.add_observer(self, sender=message_request)
            message_request.send()

    def _NH_SIPMessageDidSucceed(self, notification):
        data = notification.data
        print(data.code)

    def _NH_SIPMessageDidFail(self, notification):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)


@implementer(IObserver)
class IncomingCallInitializer(object):

    sessions = 0
    tone_ringtone = None

    def __init__(self, session, auto_answer_interval=None):
        self.session = session
        self.auto_answer_interval = auto_answer_interval
        self.question = None

    def start(self):
        IncomingCallInitializer.sessions += 1
        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=self.session)        
        self.session.accept(self.session.proposed_streams)

    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def _NH_SIPSessionWillStart(self, notification):
        print("SIPSessionWillStart!")

    def _NH_SIPSessionDidStart(self, notification):
        print("SIPSessionDidStart!")
        notification_center = NotificationCenter()
        session = notification.sender
        notification_center.remove_observer(self, sender=session)
        IncomingCallInitializer.sessions -= 1

        identity = str(session.remote_identity.uri)
        if session.remote_identity.display_name:
            identity = '"%s" <%s>' % (session.remote_identity.display_name, identity)
        print('SIP session with %s established' % identity)

        for stream in notification.data.streams:
            if stream.type in ('audio', 'video'):
                print('%s stream using %s codec at %sHz' % (stream.type.title(), stream.codec.capitalize(), stream.sample_rate))
                if stream.ice_active:
                    print('%s RTP endpoints %s:%d (ICE type %s) <-> %s:%d (ICE type %s)\n' % (stream.type.title(), stream.local_rtp_address,
                                                                                              stream.local_rtp_port,
                                                                                              stream.local_rtp_candidate.type.lower(),
                                                                                              stream.remote_rtp_address,
                                                                                              stream.remote_rtp_port,
                                                                                              stream.remote_rtp_candidate.type.lower()))
                    pass
                else:
                    print('%s RTP endpoints %s:%d <-> %s:%d\n' % (stream.type.title(), 
                                                                  stream.local_rtp_address, 
                                                                  stream.local_rtp_port, 
                                                                  stream.remote_rtp_address, 
                                                                  stream.remote_rtp_port))
                    pass
                if stream.encryption.active:
                    print('%s RTP stream is encrypted using %s (%s)\n' % (stream.type.title(), stream.encryption.type, stream.encryption.cipher.decode()))
                    pass

        if session.remote_user_agent is not None:
            print('Remote SIP User Agent is "%s"' % session.remote_user_agent)
            pass
    
    def _NH_SIPSessionDidFail(self, notification):
        notification_center = NotificationCenter()
        session = notification.sender
        notification_center.remove_observer(self, sender=session)

        IncomingCallInitializer.sessions -= 1

        if notification.data.failure_reason == 'user request' and notification.data.code == 487:
            print('SIP session cancelled by user')
            pass
        if notification.data.failure_reason == 'Call completed elsewhere' and notification.data.code == 487:
            print('SIP session cancelled, call was answered elsewhere')
            pass
        elif notification.data.failure_reason == 'user request':
            print('SIP session rejected (%d %s)' % (notification.data.code, notification.data.reason))
            pass
        else:
            print('SIP session failed: %s' % notification.data.failure_reason)
            pass

class AIoTtalk_SIPApplication(SIPApplication):

    def __init__(self):
        self.account = None
        self.active_session = None
        self.sessions = []
        self.config_directory = None
        self.registration_succeeded = False

        self.receive_message_queue = multiprocessing.Queue()
        self.send_message_queue = multiprocessing.Queue()
        self.message_sender = None

    def start(self, register=False):
        self.register = register
        
        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=self)

        notification_center.add_observer(self, name='SIPSessionNewIncoming')
        notification_center.add_observer(self, name='SIPSessionNewOutgoing')
        notification_center.add_observer(self, name='SIPEngineGotMessage')
        notification_center.add_observer(self, name='SIPSessionDidEnd')
        notification_center.add_observer(self, name='SIPSessionTransferNewOutgoing')
        notification_center.add_observer(self, name='SIPSessionTransferDidStart')
        notification_center.add_observer(self, name='SIPSessionTransferGotProgress')
        notification_center.add_observer(self, name='SIPSessionTransferDidEnd')
        notification_center.add_observer(self, name='SIPSessionTransferDidFail')

        notification_center.add_observer(self, sender='Session')
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
        
    def _NH_SIPAccountRegistrationDidSucceed(self, notification):
        print("notification handler: SIPAccountRegistrationDidSucceed!")
        
        if self.registration_succeeded:
            return
        contact_header = notification.data.contact_header
        contact_header_list = notification.data.contact_header_list
        expires = notification.data.expires
        registrar = notification.data.registrar

    def _NH_SIPAccountRegistrationDidFail(self, notification):
        pass
    
    def _NH_SIPAccountRegistrationDidEnd(self, notification):
        print("notification handler: SIPAccountRegistrationDidEnd!")
        pass

    def _NH_SIPEngineGotMessage(self, notification):
        print("notification handler: SIPEngineGotMessage!")

        content_type = notification.data.content_type
        data = notification.data
        
        from_header = FromHeader.new(notification.data.from_header)
        from_header.parameters = {}
        from_header.uri.parameters = {}
        identity = str(from_header.uri)

        if from_header.display_name:
            identity = '"%s" <%s>' % (from_header.display_name, identity)
        body = notification.data.body
        content = data.body
        content_type = data.content_type
        sender_identity = data.from_header
        #print(content)
        message = content.decode()
        #print("content: %s" %content.decode())
        
        #print("Got %s MESSAGE from %s: \n%s" % (content_type, identity, content.decode()))
        self.receive_message_queue.put(message)

        #self.receive_message_queue.put(content.decode())
        pass
    
    def _NH_SIPMessageDidSucceed(self, notification):
        data = notification.data
        user_agent = data.headers.get('User-Agent', Null).body
        client = data.headers.get('Client', Null).body
        server = data.headers.get('Server', Null).body
        entity = user_agent or server or client
    
    def _NH_SIPMessageDidFail(self, notification):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)

    def _NH_SIPSessionNewIncoming(self, notification):
        notification_center = NotificationCenter()
        #print(notification)
        #print(notification.data)
        print("notification handler: SIPSessionNewIncoming!")
        session = notification.sender
        print(session._invitation.sdp.proposed_remote)
        session.accept(session.proposed_streams)
        #incoming_call_initializer = IncomingCallInitializer(session=session)
        #incoming_call_initializer.start()
        notification_center.add_observer(self, sender=session)
        pass
    
    def _NH_SIPSessionWillStart(self, notification):
        print("notification handler: SIPSessionWillStart!")
        pass

    def _NH_SIPSessionDidStart(self, notification):
        print("notification handler: SIPSessionDidStart")
        session = notification.sender
        self.sessions.append(session)
        print("Start Transfer to 7001@140.114.77.83")
        self._CH_transfer("7001@140.117.77.83", session)
        pass
    
    def _NH_SIPSessionTransferNewOutgoing(self, notification):
        print('notification handler: SIPSessionTransferNewOutgoing')

    def _NH_SIPSessionTransferDidStart(self, notification):
        print('notification handler: SIPSessionTransferDidStart')
    
    def _NH_SIPSessionTransferGotProgress(self, notification):
        print('notification handler: SIPSessionTransferGotProgress')

    def _NH_SIPSessionTransferDidEnd(self, notification):
        print('notification handler: SIPSessionTransferDidEnd')

    def _NH_SIPSessionTransferDidFail(self, notification):
        print('notification handler: SIPSessionTransferDidFail')

    def _CH_transfer(self, uri, session):
        if re.match('^(sip:|sips:)', uri) is None:
            uri = 'sip:%s' % uri
            
        if '@' not in uri:
            uri = '%s@%s' % (uri, self.account.id.domain)

        try:
            uri = SIPURI.parse(uri)
        except SIPCoreError:
            print('Invalid SIP URI')
        else:
            session.transfer(uri)

if __name__ == "__main__":
    pass