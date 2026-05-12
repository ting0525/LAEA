#!/usr/bin/python3

import atexit
import os
import select
import signal
import sys
import termios
import uuid
import requests
import json

from datetime import datetime
from optparse import OptionParser
from threading import Thread
from time import sleep
# from twisted.internet import reactor

from application import log
from application.notification import NotificationCenter, NotificationData, IObserver
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

from zope.interface import implementer
import re
import threading
from queue import Queue
from mysession import Session

@implementer(IObserver)
class OutgoingCallInitializer(object):
    def __init__(self, account, target):
        self.account = account
        self.target = target
        self.streams = []
        
        notification_center = NotificationCenter()
        notification_center.add_observer(self, name='SIPSessionWillEnd')
        notification_center.add_observer(self, name='SIPSessionDidEnd')

        self.wave_ringtone = None
    
    def start(self):
        if isinstance(self.account, BonjourAccount) and '@' not in self.target:
            print('Bonjour mode requires a host in the destination address')
            return
        if '@' not in self.target:
            self.target = '%s@%s' % (self.target, self.account.id.domain)
        if not self.target.startswith('sip:') and not self.target.startswith('sips:'):
            self.target = 'sip:' + self.target

        try:
            self.target = SIPURI.parse(self.target)
        except SIPCoreError:
            print('Illegal SIP URI: %s' % self.target)
            return
        
        else:
            if '.' not in self.target.host.decode() and not isinstance(self.account, BonjourAccount):
                self.target.host = '%s.%s' % (self.target.host, self.account.id.domain)
            lookup = DNSLookup()
            notification_center = NotificationCenter()
            notification_center.add_observer(self, sender=lookup)
            settings = SIPSimpleSettings()

            if isinstance(self.account, Account) and self.account.sip.outbound_proxy is not None:
                uri = SIPURI(host=self.account.sip.outbound_proxy.host, port=self.account.sip.outbound_proxy.port, parameters={'transport': self.account.sip.outbound_proxy.transport})
                tls_name = self.account.sip.tls_name or self.account.sip.outbound_proxy.host
            elif isinstance(self.account, Account) and self.account.sip.always_use_my_proxy:
                uri = SIPURI(host=self.account.id.domain)
                tls_name = self.account.sip.tls_name or self.account.id.domain
            else:
                uri = self.target
                tls_name = uri.host
                if self.account is not BonjourAccount():
                    if self.account.id.domain == uri.host.decode():
                        tls_name = self.account.sip.tls_name or self.account.id.domain
                    elif "isfocus" in str(uri) and uri.host.decode().endswith(self.account.id.domain):
                        tls_name = self.account.conference.tls_name or self.account.sip.tls_name or self.account.id.domain
                else:
                    is_ip_address = re.match("^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", uri.host.decode()) or ":" in uri.host.decode()
                    if "isfocus" in str(uri) and self.account.conference.tls_name:
                        tls_name = self.account.conference.tls_name
                    elif  is_ip_address and  self.account.sip.tls_name:
                        tls_name = self.account.sip.tls_name
                
            print('DNS lookup for %s' % uri)
            lookup.lookup_sip_proxy(uri, settings.sip.transport_list, tls_name=tls_name)
    
    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def _NH_DNSLookupDidSucceed(self, notification):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)
        session = Session(self.account)
        notification_center.add_observer(self, sender=session)
        session.connect(ToHeader(self.target), routes=notification.data.result, streams=self.streams)
        
        application = RTPUA_SIPApplication()
        application.outgoing_session = session

    def _NH_DNSLookupDidFail(self, notification):
        print('Call to %s failed: DNS lookup error: %s' % (self.target, notification.data.error))
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)
    
    def _NH_SIPSessionWillStart(self, notification):
        print("OutgoingCallInitializer SIPSessionWillStart")

        session = notification.sender
        sleep(100)
        session.stop_media_stream()
        session.end()
        # application = RTPUA_SIPApplication()
        # application.outgoing_session.end()
    
    def _NH_SIPSessionDidStart(self, notification):
        notification_center = NotificationCenter()
        session = notification.sender
        notification_center.remove_observer(self, sender=session)

        if session.remote_user_agent is not None:
            print('Remote SIP User Agent is: {}'.format(session.remote_user_agent))
    
    def _NH_SIPSessionDidFail(self, notification):
        notification_center = NotificationCenter()
        session = notification.sender
        notification_center.remove_observer(self, sender=session)

        if notification.data.failure_reason == 'user request' and notification.data.code == 487:
            print('SIP session cancelled')
        elif notification.data.failure_reason == 'user request':
            print('SIP session rejected by user (%d %s)' % (notification.data.code, notification.data.reason))
        else:
            print('SIP session failed: %s' % notification.data.failure_reason)
    
    def _NH_SIPSessionWillEnd(self, notification):
        print("OutgoingCallInitializer SIPSessionWillEnd")
        notification_center = NotificationCenter()
        session = notification.sender

    def _NH_SIPSessionDidEnd(self, notification):
        print("OutgoingCallInitializer SIPSessionDidEnd")
        notification_center = NotificationCenter()
        session = notification.sender
        
        print("Terminating RTPUA_SIPApplication")
        # reactor.stop()
        # os._exit(0)
        
        os.kill(os.getpid(), signal.SIGKILL)
class RTPUA_SIPApplication(SIPApplication):
    def __init__(self):
        self.account = None
        self.options = None
        self.target = None
        
        self.routes = []
        self.registration_succeeded = False

        self.ip_address_monitor = IPAddressMonitor()
        self.logger = None
        self.outgoing_session = None

        self.initialize_finish = threading.Event()
        self.register_finish = threading.Event()
        self.lookup_finish = threading.Event()
        
    def start(self, sip_account, _config_directory, target=None):
        notification_center = NotificationCenter()
        
        self.sip_account = sip_account
        self.target = target
        self.sip_message_queue = Queue()
        self.sip_send_message_queue = Queue()
        #self.options = options
        #self.target = target
        
        notification_center.add_observer(self, sender=self)

        notification_center.add_observer(self, name='SIPSessionNewIncoming')
        notification_center.add_observer(self, name='SIPSessionNewOutgoing')
        notification_center.add_observer(self, name='SIPSessionWillEnd')
        notification_center.add_observer(self, name='SIPSessionDidEnd')

        log.level.current = log.level.WARNING # get rid of twisted messages

        Account.register_extension(AccountExtension)
        BonjourAccount.register_extension(BonjourAccountExtension)
        SIPSimpleSettings.register_extension(SIPSimpleSettingsExtension)
        try:
            SIPApplication.start(self, FileStorage("./sip_accounts"))
            print("start SIPApplication")
        except ConfigurationError as e:
            print("start SIPApplication Error")

    def _NH_SIPApplicationWillStart(self, notification):
        print('notification handler: SIPApplicationWillStart')
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
        print('notification handler: SIPApplicationDidStart')
        self.initialize_finish.set()

    def _NH_SIPApplicationWillEnd(self, notification):
        self.ip_address_monitor.stop()

    def _NH_SIPApplicationDidEnd(self, notification):
        print('notification handler: SIPApplicationDidEnd')

    def _NH_SIPEngineGotException(self, notification):
        print('An exception occured within the SIP core:\n%s\n' % notification.data.traceback)

    def _NH_SIPAccountRegistrationDidSucceed(self, notification):
        print('notification handler: SIPAccountRegistrationDidSucceed')
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
        call_target = self.target or "siptalktest@140.114.77.72"
        self.call(call_target)

    def _NH_SIPAccountRegistrationDidFail(self, notification):
        print('notification handler: SIPAccountRegistrationDidFail')
        print('%s Failed to register contact for sip:%s: %s (retrying in %.2f seconds)\n' % (datetime.now().replace(microsecond=0), self.account.id, notification.data.error, notification.data.retry_after))

    def _NH_SIPAccountRegistrationDidEnd(self, notification):
        print('notification handler: SIPAccountRegistrationDidEnd')
        print('%s Registration ended.\n' % datetime.now().replace(microsecond=0))

    def _NH_DNSLookupDidSucceed(self, notification):
        self.routes = notification.data.result
        self.lookup_finish.set()
        #self._send_message()

    def _NH_DNSLookupDidFail(self, notification):
        print('DNS lookup failed: %s\n' % notification.data.error) 
        self.stop()
    
    def wait_for_initialization(self):
        print("Wait For Initialization Finish...")
        self.initialize_finish.wait()
        print("Initialization Finish!")
    
    def wait_for_account_registration(self):
        print("Wait For Registration Finish...")
        self.register_finish.wait()
        print("Registration Finish!")
    
    def call(self, target):
        call = OutgoingCallInitializer(self.account, target)
        call.start()

OFLServer = "140.114.77.72"
OFLServerPort = "3002"

def request_join(client_name, model_name, dataset_format):
    url = f'http://{OFLServer}:{OFLServerPort}/OFL_server/join_request'
    headers = {'Content-Type': 'application/json'}
    post_data = {'NAME': client_name, 'EDGE_SITE': 'site-hsinchu', 'MODEL_NAME': model_name, 'DATASET_FORMAT': dataset_format}
    try:
        response = requests.post(url, json = post_data, headers=headers)
        if response.status_code == 200:
            print("Join request successful")
            response_data = json.loads(response.text)
            client_id = response_data.get("client_id")
            sip_account = response_data.get("sip_account")
            print(f"Client ID: {client_id}, SIP Account: {sip_account}")
            return client_id, sip_account
        else:
            print(f"Join request failed: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"request_join error: {e}")
        return None

def request_delete(client_id, sip_account):
    url = f'http://{OFLServer}:{OFLServerPort}/OFL_server/terminate_request'
    headers = {'Content-Type': 'application/json', 'Client-ID': client_id}
    post_data = {'SIP_ACCOUNT': sip_account}
    try:
        response = requests.post(url, json=post_data, headers=headers)
        if response.status_code == 200:
            print("Delete request successful")
            # print(response.text)
        else:
            print(f"Delete request failed: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"request_delete error: {e}")


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("--sip-account", dest="sip_account", help="Use a fixed SIP account instead of requesting one from OFL server")
    parser.add_option("--target", dest="target", help="Call target SIP URI or account")
    parser.add_option("--client-name", dest="client_name", default="client1")
    parser.add_option("--model-name", dest="model_name", default="yolov9t")
    parser.add_option("--dataset-format", dest="dataset_format", default="VisDrone_t1")
    parser.add_option(
        "--use-ofl-join",
        action="store_true",
        dest="use_ofl_join",
        default=False,
        help="Request SIP account from OFL server instead of using --sip-account",
    )
    options, _args = parser.parse_args()

    if not options.use_ofl_join and not options.sip_account:
        parser.error("either specify --sip-account or use --use-ofl-join")
    if not options.target:
        parser.error("missing --target")

    client_id = None
    sip_account = options.sip_account

    if options.use_ofl_join:
        while True:
            join_result = request_join(options.client_name, options.model_name, options.dataset_format)
            if join_result is None:
                print("No SIP account received, retrying...")
                sleep(5)
                continue
            client_id, sip_account = join_result
            if sip_account and '@' in sip_account:
                sip_account = sip_account.replace('\n', '').replace('"', '')
                break
            print("No SIP account received, retrying...")
            sleep(5)

    print("===================================================")
    print("Using SIP account: {}".format(sip_account))
    print("Calling target: {}".format(options.target))
    print("===================================================")

    rtp_ua = RTPUA_SIPApplication()
    rtp_ua.start(sip_account, True, target=options.target)

    if client_id is not None:
        request_delete(client_id, sip_account)
