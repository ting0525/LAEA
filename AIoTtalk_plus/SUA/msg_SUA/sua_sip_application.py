#!/usr/bin/python3

import atexit
import os
import select
import signal
import sys
import termios
import uuid

from datetime import datetime
from optparse import OptionParser
from threading import Thread
from time import sleep

from application import log
from application.notification import NotificationCenter, NotificationData
from application.python.queue import EventQueue
from application.python import Null

from sipsimple.core import FromHeader, Message, RouteHeader, SIPCoreError, SIPURI, ToHeader

from sipsimple.account import Account, AccountManager, BonjourAccount
from sipsimple.application import SIPApplication
from sipsimple.configuration import ConfigurationError
from sipsimple.configuration.settings import SIPSimpleSettings
from sipsimple.core import Engine
from sipsimple.lookup import DNSLookup, DNSLookupError
from sipsimple.storage import FileStorage
from sipsimple.streams.msrp.chat import CPIMPayload, SimplePayload, CPIMParserError, CPIMHeader, ChatIdentity, CPIMNamespace
from sipsimple.payloads.imdn import IMDNDocument, DisplayNotification, DeliveryNotification

from sipclient.configuration import config_directory
from sipclient.configuration.account import AccountExtension, BonjourAccountExtension
from sipclient.configuration.settings import SIPSimpleSettingsExtension
from sipclient.log import Logger
from sipclient.system import IPAddressMonitor
from sipsimple.util import ISOTimestamp
from sipsimple.threading.green import run_in_green_thread

import threading
from queue import Queue

class SUA_SIPApplication(SIPApplication):
    def __init__(self):
        self.account = None
        self.options = None
        self.target = None
        
        self.routes = []
        self.registration_succeeded = False

        self.ip_address_monitor = IPAddressMonitor()
        self.logger = None
        
        self.initialize_finish = threading.Event()
        self.register_finish = threading.Event()
        self.lookup_finish = threading.Event()

    def start(self, sip_account, _config_directory):
        notification_center = NotificationCenter()
        
        self.sip_account = sip_account
        self.sip_message_queue = Queue()
        self.sip_send_message_queue = Queue()
        #self.options = options
        #self.target = target
        
        notification_center.add_observer(self, sender=self)
        notification_center.add_observer(self, name='SIPEngineGotMessage')
        print("Start Receiving Message")

        log.level.current = log.level.WARNING # get rid of twisted messages

        Account.register_extension(AccountExtension)
        BonjourAccount.register_extension(BonjourAccountExtension)
        SIPSimpleSettings.register_extension(SIPSimpleSettingsExtension)
        try:
            SIPApplication.start(self, FileStorage(_config_directory or config_directory))
            print("start SIPApplication")
        except ConfigurationError as e:
            print("start SIPApplication Error")

    def _NH_SIPApplicationWillStart(self, notification):
        account_manager = AccountManager()
        notification_center = NotificationCenter()
        settings = SIPSimpleSettings()
    
        if self.sip_account is None:
            print("Please Specify sip account to send the message")
            return
        else:
            possible_accounts = [account for account in account_manager.iter_accounts() if self.sip_account in account.id and account.enabled]
            if len(possible_accounts) > 1:
                print('More than one account exists which matches %s: %s\n' % (self.sip_account, ', '.join(sorted(account.id for account in possible_accounts))))
                return
            elif len(possible_accounts) == 0:
                print('No enabled account that matches %s was found. Available and enabled accounts: %s\n' % (self.sip_account, ', '.join(sorted(account.id for account in account_manager.get_accounts() if account.enabled))))
            else:
                self.account = possible_accounts[0]
            
        for account in account_manager.iter_accounts():
            if isinstance(account, Account):
                account.sip.register = False
                account.presence.enabled = False
                account.xcap.enabled = False
                account.message_summary.enabled = False

        if self.sip_account is None:
            self.account = account_manager.default_account
        else:
            possible_accounts = [account for account in account_manager.iter_accounts() if self.sip_account in account.id and account.enabled]
            if len(possible_accounts) > 1:
                print("More than one account exists")
                return

            elif len(possible_accounts) == 0:
                print("No enabled account that matches")
                return

            else:
                self.account = possible_accounts[0]
                self.account.sip.register = True
                self.account.presence.enabled = False
                self.account.xcap.enabled = False
                self.account.message_summary.enabled = False                
                notification_center.add_observer(self, sender=self.account)

    def _NH_SIPApplicationDidStart(self, notification):
        print("SIPApplicationDidStart!")
        self.initialize_finish.set()

    def _NH_SIPApplicationWillEnd(self, notification):
        self.ip_address_monitor.stop()

    def _NH_SIPApplicationDidEnd(self, notification):
        print("SIPApplication Ended")

    def _NH_SIPEngineGotException(self, notification):
        self.output.put('An exception occured within the SIP core:\n%s\n' % notification.data.traceback)

    def _NH_SIPAccountRegistrationDidSucceed(self, notification):
        if self.registration_succeeded:
            return
        contact_header = notification.data.contact_header
        contact_header_list = notification.data.contact_header_list
        expires = notification.data.expires
        registrar = notification.data.registrar
        message = '%s Registered contact "%s" for sip:%s at %s:%d;transport=%s (expires in %d seconds).\n' % (datetime.now().replace(microsecond=0), contact_header.uri, self.account.id, registrar.address, registrar.port, registrar.transport, expires)
        if len(contact_header_list) > 1:
            message += 'Other registered contacts:\n%s\n' % '\n'.join(['  %s (expires in %s seconds)' % (str(other_contact_header.uri), other_contact_header.expires) for other_contact_header in contact_header_list if other_contact_header.uri != notification.data.contact_header.uri])
        print(message)
        self.register_finish.set()
        
        self.registration_succeeded = True

    def _NH_SIPAccountRegistrationDidFail(self, notification):
        print('%s Failed to register contact for sip:%s: %s (retrying in %.2f seconds)\n' % (datetime.now().replace(microsecond=0), self.account.id, notification.data.error, notification.data.retry_after))

    def _NH_SIPAccountRegistrationDidEnd(self, notification):
        print('%s Registration ended.\n' % datetime.now().replace(microsecond=0))

    def _NH_DNSLookupDidSucceed(self, notification):
        self.routes = notification.data.result
        self.lookup_finish.set()
        #self._send_message()

    def _NH_DNSLookupDidFail(self, notification):
        print('DNS lookup failed: %s\n' % notification.data.error) 
        self.stop()

    def _NH_SIPEngineGotMessage(self, notification):
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

        print("Got %s MESSAGE from %s: \n%s\n" % (content_type, identity, content.decode()))
        self.sip_message_queue.put(content.decode())

    def _NH_SIPMessageDidSucceed(self, notification):
        data = notification.data
        user_agent = data.headers.get('User-Agent', Null).body
        client = data.headers.get('Client', Null).body
        server = data.headers.get('Server', Null).body
        entity = user_agent or server or client
        
        print('MESSAGE was accepted by %s\n' % entity)
        #self.output.put('MESSAGE was accepted by %s\n' % entity)
        #self.stop()

    def _NH_SIPMessageDidFail(self, notification):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)
        #print('Could not deliver MESSAGE: %d %s\n' % (notification.data.code, notification.data.reason))
        #print(notification.data.code)
        #self._send_message()
    
    def wait_for_initialization(self):
        print("Wait For Initialization Finish...")
        self.initialize_finish.wait()
        print("Initialization Finish!")
    
    def wait_for_account_registration(self):
        print("Wait For Registration Finish...")
        self.register_finish.wait()
        print("Registration Finish!")
    
    def start_send_message(self, target, message, content_type):
        
        notification_center = NotificationCenter()
        settings = SIPSimpleSettings()
        self.ip_address_monitor.start()
        self.target = target
        self.message = message
        self.content_type = content_type

        if self.target is not None:
            if '@' not in self.target:
                self.target = '%s@%s' % (self.target, self.account.id.domain)
            if not self.target.startswith('sip:') and not self.target.startswith('sips:'):
                self.target = 'sip:' + self.target
            try:
                self.target = SIPURI.parse(self.target)
            except SIPCoreError:
                print('Illegal SIP URI: %s\n' % self.target)
                self.stop()

            if self.message is None:
                print("Please Specify the message to send!")
            else:
                settings = SIPSimpleSettings()
                lookup = DNSLookup()
                notification_center.add_observer(self, sender=lookup)
                if isinstance(self.account, Account) and self.account.sip.outbound_proxy is not None:
                    uri = SIPURI(host=self.account.sip.outbound_proxy.host, port=self.account.sip.outbound_proxy.port, parameters={'transport': self.account.sip.outbound_proxy.transport})
                elif isinstance(self.account, Account) and self.account.sip.always_use_my_proxy:
                    uri = SIPURI(host=self.account.id.domain)
                else:
                    uri = self.target
                lookup.lookup_sip_proxy(uri, settings.sip.transport_list, tls_name=self.account.sip.tls_name or uri.host)
        else:
            print("Please Specify the target URI to send the message")

        print("Wait For Routes lookup Finish...")
        self.lookup_finish.wait()
        print("Routes lookup Finish!")
        self._send_message()
        self.lookup_finish.clear()

    def _send_message(self):
        notification_center = NotificationCenter()
        if self.routes:
            route = self.routes.pop(0)
            identity = str(self.account.uri)
            if self.account.display_name:
                identity = '"%s" <%s>' % (self.account.display_name, identity)

            content_type = self.content_type or 'text/plain'

            additional_cpim_headers = []
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
        else:
            print('No more routes to try. Aborting.\n')
            self.output.put('No more routes to try. Aborting.\n')
            #self.stop()
    #sleep(0.1)

if __name__ == "__main__":
    pass
   