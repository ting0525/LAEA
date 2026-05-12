#!/usr/bin/python3

import os
import signal
import sys

from time import sleep
# from twisted.internet import reactor

from application.notification import NotificationCenter, IObserver

from sipsimple.core import ToHeader

from zope.interface import implementer

# from mysession import Session
from provider_session import OFLSession
from rtpua_sip_application import RTPUA_SIPApplication, OutgoingCallInitializer

from sending_request import request_join


@implementer(IObserver)
class OFL_OutgoingCallInitializer(OutgoingCallInitializer):
    def __init__(self, account, target, client_id, weight_file, data_src):
        super().__init__(account, target)
        self.client_id = client_id
        self.weight_file = weight_file
        self.data_src = data_src
    
    def _NH_DNSLookupDidSucceed(self, notification):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)
        session = OFLSession(self.account, self.client_id, self.weight_file, self.data_src)
        notification_center.add_observer(self, sender=session)
        session.connect(ToHeader(self.target), routes=notification.data.result, streams=self.streams)
        
        application = OFL_RTPUA_SIPApplication(self.client_id, self.weight_file, self.data_src)
        application.outgoing_session = session

    def _NH_SIPSessionWillStart(self, notification):
        print("OutgoingCallInitializer SIPSessionWillStart")

        session = notification.sender
        # sleep(25500)
        sleep(115200) # 32 hours
        print("session will be stopped")
        session.stop_media_stream()
        session.end()


class OFL_RTPUA_SIPApplication(RTPUA_SIPApplication):
    def __init__(self, client_id, weight_file, data_src):
        super().__init__()
        self.client_id = client_id
        self.weight_file = weight_file
        self.data_src = data_src
        
    def call(self, target):
        call = OFL_OutgoingCallInitializer(self.account, target, self.client_id, self.weight_file, self.data_src)
        call.start()


if __name__ == "__main__":

    client_name = sys.argv[1] if len(sys.argv) > 1 else 'client1'
    model_name = sys.argv[2] if len(sys.argv) > 2 else 'yolo11n'
    # dataset_format = sys.argv[3] if len(sys.argv) > 3 else 'VisDrone_tt1'
    # data_src = sys.argv[4] if len(sys.argv) > 4 else '2000x1500'
    dataset_format = sys.argv[3] if len(sys.argv) > 3 else 'VisDrone_train1'
    data_src = sys.argv[4] if len(sys.argv) > 4 else '960x540'
    weight_file = sys.argv[5] if len(sys.argv) > 5 else f'{client_name}.pt'
    
    while True:
        client_id, sip_account = request_join(client_name, model_name, dataset_format)
        if '@' in sip_account:
            sip_account = sip_account.replace('\n', '').replace('"', '')
            break
        print("No SIP account received, retrying...")
        sleep(5)

    print(f"===================================================")
    print(f"Using SIP account: {sip_account}")
    print(f"===================================================")

    ofl_rtp_ua = OFL_RTPUA_SIPApplication(client_id, weight_file, data_src)
    ofl_rtp_ua.start(sip_account, True)