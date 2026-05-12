
"""
Implements an asynchronous notification based mechanism for
establishment, modification and termination of sessions using Session
Initiation Protocol (SIP) standardized in RFC3261.
"""



__all__ = ['Session', 'SessionManager']

import random

from threading import RLock
from time import time, sleep

from application.notification import IObserver, Notification, NotificationCenter, NotificationData
from application.python import Null, limit
from application.python.decorator import decorator, preserve_signature
from application.python.types import Singleton
from application.system import host
from eventlib import api, coros, proc
from twisted.internet import reactor
from zope.interface import implementer

from sipsimple import log
from sipsimple.account import AccountManager, BonjourAccount
from sipsimple.configuration.settings import SIPSimpleSettings
from sipsimple.core import DialogID, Engine, Invitation, Referral, Subscription, PJSIPError, SIPCoreError, SIPCoreInvalidStateError, SIPURI, sip_status_messages, sipfrag_re
from sipsimple.core import ContactHeader, FromHeader, Header, ReasonHeader, ReferToHeader, ReplacesHeader, RouteHeader, ToHeader, WarningHeader
from sipsimple.core import SDPConnection, SDPMediaStream, SDPSession, SDPAttribute
from sipsimple.core import PublicGRUU, PublicGRUUIfAvailable, NoGRUU
from sipsimple.lookup import DNSLookup, DNSLookupError
from sipsimple.payloads import ParserError
from sipsimple.payloads.conference import ConferenceDocument
from sipsimple.streams import MediaStreamRegistry, InvalidStreamError, UnknownStreamError
from sipsimple.threading import run_in_twisted_thread
from sipsimple.threading.green import Command, run_in_green_thread
from sipsimple.util import ISOTimestamp

import subprocess
import time
import json
from sdp_process import parse_sdp
import socket

from mysession import *

import os
import signal


def find_free_udp_port(start_port=10000, max_port=11000):
    for port in range(start_port, max_port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(('', port))
            s.close()  # release immediately
            return port
        except OSError:
            s.close()
            continue
    raise RuntimeError("No free UDP port found")

class InvitationDisconnectedError(Exception):
    def __init__(self, invitation, data):
        self.invitation = invitation
        self.data = data


class MediaStreamDidNotInitializeError(Exception):
    def __init__(self, stream, data):
        self.stream = stream
        self.data = data


class MediaStreamDidFailError(Exception):
    def __init__(self, stream, data):
        self.stream = stream
        self.data = data


class SubscriptionError(Exception):
    def __init__(self, error, timeout, **attributes):
        self.error = error
        self.timeout = timeout
        self.attributes = attributes


class SIPSubscriptionDidFail(Exception):
    def __init__(self, data):
        self.data = data


class InterruptSubscription(Exception):
    pass


class TerminateSubscription(Exception):
    pass


class ReferralError(Exception):
    def __init__(self, error, code=0):
        self.error = error
        self.code = code


class TerminateReferral(Exception):
    pass


class SIPReferralDidFail(Exception):
    def __init__(self, data):
        self.data = data


class IllegalStateError(RuntimeError):
    pass


class IllegalDirectionError(RuntimeError):
    pass


class SIPInvitationTransferDidFail(Exception):
    def __init__(self, data):
        self.data = data


@decorator
def transition_state(required_state, new_state):
    def state_transitioner(func):
        @preserve_signature(func)
        def wrapper(obj, *args, **kwargs):
            with obj._lock:
                if obj.state != required_state:
                    raise IllegalStateError('cannot call %s in %s state' % (func.__name__, obj.state))
                obj.state = new_state
            return func(obj, *args, **kwargs)
        return wrapper
    return state_transitioner


@decorator
def check_state(required_states):
    def state_checker(func):
        @preserve_signature(func)
        def wrapper(obj, *args, **kwargs):
            if obj.state not in required_states:
                raise IllegalStateError('cannot call %s in %s state' % (func.__name__, obj.state))
            return func(obj, *args, **kwargs)
        return wrapper
    return state_checker


@decorator
def check_transfer_state(direction, state):
    def state_checker(func):
        @preserve_signature(func)
        def wrapper(obj, *args, **kwargs):
            if obj.transfer_handler.direction != direction:
                raise IllegalDirectionError('cannot transfer in %s direction' % obj.transfer_handler.direction)
            if obj.transfer_handler.state != state:
                raise IllegalStateError('cannot transfer in %s state' % obj.transfer_handler.state)
            return func(obj, *args, **kwargs)
        return wrapper
    return state_checker


class AddParticipantOperation(object):
    pass

class RemoveParticipantOperation(object):
    pass


@implementer(IObserver)
class ReferralHandler(object):

    def __init__(self, session, participant_uri, operation):
        self.participant_uri = participant_uri
        if not isinstance(self.participant_uri, SIPURI):
            if not self.participant_uri.startswith(('sip:', 'sips:')):
                self.participant_uri = 'sip:%s' % self.participant_uri
            try:
                self.participant_uri = SIPURI.parse(self.participant_uri)
            except SIPCoreError:
                notification_center = NotificationCenter()
                if operation is AddParticipantOperation:
                    notification_center.post_notification('SIPConferenceDidNotAddParticipant', sender=session, data=NotificationData(participant=self.participant_uri, code=0, reason='invalid participant URI'))
                else:
                    notification_center.post_notification('SIPConferenceDidNotRemoveParticipant', sender=session, data=NotificationData(participant=self.participant_uri, code=0, reason='invalid participant URI'))
                return
        self.session = session
        self.operation = operation
        self.active = False
        self.route = None
        self._channel = coros.queue()
        self._referral = None

    def start(self):
        notification_center = NotificationCenter()
        if not self.session.remote_focus:
            if self.operation is AddParticipantOperation:
                notification_center.post_notification('SIPConferenceDidNotAddParticipant', sender=self.session, data=NotificationData(participant=self.participant_uri, code=0, reason='remote endpoint is not a focus'))
            else:
                notification_center.post_notification('SIPConferenceDidNotRemoveParticipant', sender=self.session, data=NotificationData(participant=self.participant_uri, code=0, reason='remote endpoint is not a focus'))
            self.session = None
            return
        notification_center.add_observer(self, sender=self.session)
        notification_center.add_observer(self, name='NetworkConditionsDidChange')
        proc.spawn(self._run)

    def _run(self):
        notification_center = NotificationCenter()
        settings = SIPSimpleSettings()

        try:
            # Lookup routes
            account = self.session.account
            if account is BonjourAccount():
                uri = SIPURI.new(self.session._invitation.remote_contact_header.uri)
            elif account.sip.outbound_proxy is not None and account.sip.outbound_proxy.transport in settings.sip.transport_list:
                uri = SIPURI(host=account.sip.outbound_proxy.host, port=account.sip.outbound_proxy.port, parameters={'transport': account.sip.outbound_proxy.transport})
            elif account.sip.always_use_my_proxy:
                uri = SIPURI(host=account.id.domain)
            else:
                uri = SIPURI.new(self.session.remote_identity.uri)
            lookup = DNSLookup()
            try:
                tls_name = account.sip.tls_name if account is not BonjourAccount() else None
                routes = lookup.lookup_sip_proxy(uri, settings.sip.transport_list, tls_name=tls_name).wait()
            except DNSLookupError as e:
                timeout = random.uniform(15, 30)
                raise ReferralError(error='DNS lookup failed: %s' % e)

            target_uri = SIPURI.new(self.session.remote_identity.uri)

            timeout = time() + 30
            for route in routes:
                self.route = route
                remaining_time = timeout - time()
                if remaining_time > 0:
                    try:
                        contact_uri = account.contact[NoGRUU, route]
                    except KeyError:
                        continue
                    refer_to_header = ReferToHeader(str(self.participant_uri))
                    refer_to_header.parameters['method'] = 'INVITE' if self.operation is AddParticipantOperation else 'BYE'
                    referral = Referral(target_uri, FromHeader(account.uri, account.display_name),
                                        ToHeader(target_uri),
                                        refer_to_header,
                                        ContactHeader(contact_uri),
                                        RouteHeader(route.uri),
                                        account.credentials)
                    notification_center.add_observer(self, sender=referral)
                    try:
                        referral.send_refer(timeout=limit(remaining_time, min=1, max=5))
                    except SIPCoreError:
                        notification_center.remove_observer(self, sender=referral)
                        timeout = 5
                        raise ReferralError(error='Internal error')
                    self._referral = referral
                    try:
                        while True:
                            notification = self._channel.wait()
                            if notification.name == 'SIPReferralDidStart':
                                break
                    except SIPReferralDidFail as e:
                        notification_center.remove_observer(self, sender=referral)
                        self._referral = None
                        if e.data.code in (403, 405):
                            raise ReferralError(error=sip_status_messages[e.data.code], code=e.data.code)
                        else:
                            # Otherwise just try the next route
                            continue
                    else:
                        break
            else:
                self.route = None
                raise ReferralError(error='No more routes to try')
            # At this point it is subscribed. Handle notifications and ending/failures.
            try:
                self.active = True
                while True:
                    notification = self._channel.wait()
                    if notification.name == 'SIPReferralGotNotify':
                        if notification.data.event == 'refer' and notification.data.body:
                            match = sipfrag_re.match(notification.data.body)
                            if match:
                                code = int(match.group('code'))
                                reason = match.group('reason')
                                if code/100 > 2:
                                    continue
                                if self.operation is AddParticipantOperation:
                                    notification_center.post_notification('SIPConferenceGotAddParticipantProgress', sender=self.session, data=NotificationData(participant=self.participant_uri, code=code, reason=reason))
                                else:
                                    notification_center.post_notification('SIPConferenceGotRemoveParticipantProgress', sender=self.session, data=NotificationData(participant=self.participant_uri, code=code, reason=reason))
                    elif notification.name == 'SIPReferralDidEnd':
                        break
            except SIPReferralDidFail as e:
                notification_center.remove_observer(self, sender=self._referral)
                raise ReferralError(error=e.data.reason, code=e.data.code)
            else:
                notification_center.remove_observer(self, sender=self._referral)
                if self.operation is AddParticipantOperation:
                    notification_center.post_notification('SIPConferenceDidAddParticipant', sender=self.session, data=NotificationData(participant=self.participant_uri))
                else:
                    notification_center.post_notification('SIPConferenceDidRemoveParticipant', sender=self.session, data=NotificationData(participant=self.participant_uri))
            finally:
                self.active = False
        except TerminateReferral:
            if self._referral is not None:
                try:
                    self._referral.end(timeout=2)
                except SIPCoreError:
                    pass
                else:
                    try:
                        while True:
                            notification = self._channel.wait()
                            if notification.name == 'SIPReferralDidEnd':
                                break
                    except SIPReferralDidFail:
                        pass
                finally:
                    notification_center.remove_observer(self, sender=self._referral)
            if self.operation is AddParticipantOperation:
                notification_center.post_notification('SIPConferenceDidNotAddParticipant', sender=self.session, data=NotificationData(participant=self.participant_uri, code=0, reason='error'))
            else:
                notification_center.post_notification('SIPConferenceDidNotRemoveParticipant', sender=self.session, data=NotificationData(participant=self.participant_uri, code=0, reason='error'))
        except ReferralError as e:
            if self.operation is AddParticipantOperation:
                notification_center.post_notification('SIPConferenceDidNotAddParticipant', sender=self.session, data=NotificationData(participant=self.participant_uri, code=e.code, reason=e.error))
            else:
                notification_center.post_notification('SIPConferenceDidNotRemoveParticipant', sender=self.session, data=NotificationData(participant=self.participant_uri, code=e.code, reason=e.error))
        finally:
            notification_center.remove_observer(self, sender=self.session)
            notification_center.remove_observer(self, name='NetworkConditionsDidChange')
            self.session = None
            self._referral = None

    def _refresh(self):
        try:
            contact_header = ContactHeader(self.session.account.contact[NoGRUU, self.route])
        except KeyError:
            pass
        else:
            try:
                self._referral.refresh(contact_header=contact_header, timeout=2)
            except (SIPCoreError, SIPCoreInvalidStateError):
                pass

    @run_in_twisted_thread
    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def _NH_SIPReferralDidStart(self, notification):
        self._channel.send(notification)

    def _NH_SIPReferralDidEnd(self, notification):
        self._channel.send(notification)

    def _NH_SIPReferralDidFail(self, notification):
        self._channel.send_exception(SIPReferralDidFail(notification.data))

    def _NH_SIPReferralGotNotify(self, notification):
        self._channel.send(notification)

    def _NH_SIPSessionDidFail(self, notification):
        self._channel.send_exception(TerminateReferral())

    def _NH_SIPSessionWillEnd(self, notification):
        self._channel.send_exception(TerminateReferral())

    def _NH_NetworkConditionsDidChange(self, notification):
        if self.active:
            self._refresh()


@implementer(IObserver)
class ConferenceHandler(object):

    def __init__(self, session):
        self.session = session
        self.active = False
        self.subscribed = False
        self._command_proc = None
        self._command_channel = coros.queue()
        self._data_channel = coros.queue()
        self._subscription = None
        self._subscription_proc = None
        self._subscription_timer = None
        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=self.session)
        notification_center.add_observer(self, name='NetworkConditionsDidChange')
        self._command_proc = proc.spawn(self._run)

    @run_in_green_thread
    def add_participant(self, participant_uri):
        referral_handler = ReferralHandler(self.session, participant_uri, AddParticipantOperation)
        referral_handler.start()

    @run_in_green_thread
    def remove_participant(self, participant_uri):
        referral_handler = ReferralHandler(self.session, participant_uri, RemoveParticipantOperation)
        referral_handler.start()

    def _run(self):
        while True:
            command = self._command_channel.wait()
            handler = getattr(self, '_CH_%s' % command.name)
            handler(command)

    def _activate(self):
        self.active = True
        command = Command('subscribe')
        self._command_channel.send(command)
        return command

    def _deactivate(self):
        self.active = False
        command = Command('unsubscribe')
        self._command_channel.send(command)
        return command

    def _resubscribe(self):
        command = Command('subscribe')
        self._command_channel.send(command)
        return command

    def _terminate(self):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=self.session)
        notification_center.remove_observer(self, name='NetworkConditionsDidChange')
        self._deactivate()
        command = Command('terminate')
        self._command_channel.send(command)
        command.wait()
        self.session = None

    def _CH_subscribe(self, command):
        if self._subscription_timer is not None and self._subscription_timer.active():
            self._subscription_timer.cancel()
        self._subscription_timer = None
        if self._subscription_proc is not None:
            subscription_proc = self._subscription_proc
            subscription_proc.kill(InterruptSubscription)
            subscription_proc.wait()
        self._subscription_proc = proc.spawn(self._subscription_handler, command)

    def _CH_unsubscribe(self, command):
        # Cancel any timer which would restart the subscription process
        if self._subscription_timer is not None and self._subscription_timer.active():
            self._subscription_timer.cancel()
        self._subscription_timer = None
        if self._subscription_proc is not None:
            subscription_proc = self._subscription_proc
            subscription_proc.kill(TerminateSubscription)
            subscription_proc.wait()
            self._subscription_proc = None
        command.signal()

    def _CH_terminate(self, command):
        command.signal()
        raise proc.ProcExit()

    def _subscription_handler(self, command):
        notification_center = NotificationCenter()
        settings = SIPSimpleSettings()

        try:
            # Lookup routes
            account = self.session.account
            if account is BonjourAccount():
                uri = SIPURI.new(self.session._invitation.remote_contact_header.uri)
            elif account.sip.outbound_proxy is not None and account.sip.outbound_proxy.transport in settings.sip.transport_list:
                uri = SIPURI(host=account.sip.outbound_proxy.host, port=account.sip.outbound_proxy.port, parameters={'transport': account.sip.outbound_proxy.transport})
            elif account.sip.always_use_my_proxy:
                uri = SIPURI(host=account.id.domain)
            else:
                uri = SIPURI.new(self.session.remote_identity.uri)
            lookup = DNSLookup()
            try:
                tls_name = account.sip.tls_name if account is not BonjourAccount() else None
                routes = lookup.lookup_sip_proxy(uri, settings.sip.transport_list, tls_name=tls_name).wait()
            except DNSLookupError as e:
                timeout = random.uniform(15, 30)
                raise SubscriptionError(error='DNS lookup failed: %s' % e, timeout=timeout)

            target_uri = SIPURI.new(self.session.remote_identity.uri)
            default_interval = 600 if account is BonjourAccount() else account.sip.subscribe_interval
            refresh_interval = getattr(command, 'refresh_interval', default_interval)

            timeout = time() + 30
            for route in routes:
                remaining_time = timeout - time()
                if remaining_time > 0:
                    try:
                        contact_uri = account.contact[NoGRUU, route]
                    except KeyError:
                        continue
                    subscription = Subscription(target_uri, FromHeader(account.uri, account.display_name),
                                                ToHeader(target_uri),
                                                ContactHeader(contact_uri),
                                                b'conference',
                                                RouteHeader(route.uri),
                                                credentials=account.credentials,
                                                refresh=refresh_interval)
                    notification_center.add_observer(self, sender=subscription)
                    try:
                        subscription.subscribe(timeout=limit(remaining_time, min=1, max=5))
                    except SIPCoreError as e:
                        notification_center.remove_observer(self, sender=subscription)
                        timeout = 5
                        raise SubscriptionError(error='Internal error %s' % str(e), timeout=timeout)
                    self._subscription = subscription

                    try:
                        while True:
                            notification = self._data_channel.wait()
                            if notification.sender is subscription:
                                break
                    except SIPSubscriptionDidFail as e:
                        notification_center.remove_observer(self, sender=subscription)
                        self._subscription = None
                        if e.data.code == 407:
                            # Authentication failed, so retry the subscription in some time
                            timeout = random.uniform(60, 120)
                            raise SubscriptionError(error='Authentication failed', timeout=timeout)
                        elif e.data.code == 423:
                            # Get the value of the Min-Expires header
                            timeout = random.uniform(60, 120)
                            if e.data.min_expires is not None and e.data.min_expires > refresh_interval:
                                raise SubscriptionError(error='Interval too short', timeout=timeout, min_expires=e.data.min_expires)
                            else:
                                raise SubscriptionError(error='Interval too short', timeout=timeout)
                        elif e.data.code in (405, 406, 489, 1400):
                            command.signal(e)
                            return
                        else:
                            # Otherwise just try the next route
                            continue
                    else:
                        self.subscribed = True
                        command.signal()
                        break
            else:
                # There are no more routes to try, reschedule the subscription
                timeout = random.uniform(60, 180)
                raise SubscriptionError(error='No more routes to try', timeout=timeout)
            # At this point it is subscribed. Handle notifications and ending/failures.
            try:
                while True:
                    notification = self._data_channel.wait()
                    if notification.sender is not self._subscription:
                        continue
                    if notification.name == 'SIPSubscriptionGotNotify':
                        if notification.data.event == 'conference' and notification.data.body:
                            try:
                                conference_info = ConferenceDocument.parse(notification.data.body)
                            except ParserError:
                                pass
                            else:
                                notification_center.post_notification('SIPSessionGotConferenceInfo', sender=self.session, data=NotificationData(conference_info=conference_info))
                    elif notification.name == 'SIPSubscriptionDidEnd':
                        break
            except SIPSubscriptionDidFail:
                self._command_channel.send(Command('subscribe'))
            notification_center.remove_observer(self, sender=self._subscription)
        except InterruptSubscription as e:
            if not self.subscribed:
                command.signal(e)
            if self._subscription is not None:
                notification_center.remove_observer(self, sender=self._subscription)
                try:
                    self._subscription.end(timeout=2)
                except SIPCoreError:
                    pass
        except TerminateSubscription as e:
            if not self.subscribed:
                command.signal(e)
            if self._subscription is not None:
                try:
                    self._subscription.end(timeout=2)
                except SIPCoreError:
                    pass
                else:
                    try:
                        while True:
                            notification = self._data_channel.wait()
                            if notification.sender is self._subscription and notification.name == 'SIPSubscriptionDidEnd':
                                break
                    except SIPSubscriptionDidFail:
                        pass
                finally:
                    notification_center.remove_observer(self, sender=self._subscription)
        except SubscriptionError as e:
            if 'min_expires' in e.attributes:
                command = Command('subscribe', command.event, refresh_interval=e.attributes['min_expires'])
            else:
                command = Command('subscribe', command.event)
            self._subscription_timer = reactor.callLater(e.timeout, self._command_channel.send, command)
        finally:
            self.subscribed = False
            self._subscription = None
            self._subscription_proc = None

    @run_in_twisted_thread
    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def _NH_SIPSubscriptionDidStart(self, notification):
        self._data_channel.send(notification)

    def _NH_SIPSubscriptionDidEnd(self, notification):
        self._data_channel.send(notification)

    def _NH_SIPSubscriptionDidFail(self, notification):
        self._data_channel.send_exception(SIPSubscriptionDidFail(notification.data))

    def _NH_SIPSubscriptionGotNotify(self, notification):
        self._data_channel.send(notification)

    def _NH_SIPSessionDidStart(self, notification):
        if self.session.remote_focus:
            self._activate()

    @run_in_green_thread
    def _NH_SIPSessionDidFail(self, notification):
        self._terminate()

    @run_in_green_thread
    def _NH_SIPSessionDidEnd(self, notification):
        self._terminate()

    def _NH_SIPSessionDidRenegotiateStreams(self, notification):
        if self.session.remote_focus and not self.active:
            self._activate()
        elif not self.session.remote_focus and self.active:
            self._deactivate()

    def _NH_NetworkConditionsDidChange(self, notification):
        if self.active:
            self._resubscribe()


class TransferInfo(object):
    def __init__(self, referred_by=None, replaced_dialog_id=None):
        self.referred_by = referred_by
        self.replaced_dialog_id = replaced_dialog_id


@implementer(IObserver)
class TransferHandler(object):

    def __init__(self, session):
        self.state = None
        self.direction = None
        self.new_session = None
        self.session = session
        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=self.session)
        notification_center.add_observer(self, sender=self.session._invitation)
        self._command_channel = coros.queue()
        self._data_channel = coros.queue()
        self._proc = proc.spawn(self._run)
        self.completed = False

    def _run(self):
        while True:
            command = self._command_channel.wait()
            handler = getattr(self, '_CH_%s' % command.name)
            handler(command)
            self.direction = None
            self.state = None

    def _CH_incoming_transfer(self, command):
        self.direction = 'incoming'
        notification_center = NotificationCenter()
        refer_to_hdr = command.data.headers.get('Refer-To')
        target = SIPURI.parse(refer_to_hdr.uri)
        referred_by_hdr = command.data.headers.get('Referred-By', None)
        if referred_by_hdr is not None:
            origin = referred_by_hdr.body
        else:
            origin = str(self.session.remote_identity.uri)
        try:
            while True:
                try:
                    notification = self._data_channel.wait()
                except SIPInvitationTransferDidFail:
                    self.state = 'failed'
                    return
                else:
                    if notification.name == 'SIPInvitationTransferDidStart':
                        self.state = 'starting'
                        refer_to_uri = SIPURI.new(target)
                        refer_to_uri.headers = {}
                        refer_to_uri.parameters = {}
                        notification_center.post_notification('SIPSessionTransferNewIncoming', self.session, NotificationData(transfer_destination=refer_to_uri))
                    elif notification.name == 'SIPSessionTransferDidStart':
                        break
                    elif notification.name == 'SIPSessionTransferDidFail':
                        self.state = 'failed'
                        try:
                            self.session._invitation.notify_transfer_progress(notification.data.code, notification.data.reason)
                        except SIPCoreError:
                            return
                        while True:
                            try:
                                notification = self._data_channel.wait()
                            except SIPInvitationTransferDidFail:
                                return
            self.state = 'started'
            transfer_info = TransferInfo(referred_by=origin)
            try:
                replaces_hdr = target.headers.pop('Replaces')
                call_id, rest = replaces_hdr.split(';', 1)
                params = dict((item.split('=') for item in rest.split(';')))
                to_tag = params.get('to-tag')
                from_tag = params.get('from-tag')
            except (KeyError, ValueError):
                pass
            else:
                transfer_info.replaced_dialog_id = DialogID(call_id, local_tag=from_tag, remote_tag=to_tag)
            settings = SIPSimpleSettings()
            account = self.session.account
            if account is BonjourAccount():
                uri = target
            elif account.sip.outbound_proxy is not None and account.sip.outbound_proxy.transport in settings.sip.transport_list:
                uri = SIPURI(host=account.sip.outbound_proxy.host, port=account.sip.outbound_proxy.port, parameters={'transport': account.sip.outbound_proxy.transport})
            elif account.sip.always_use_my_proxy:
                uri = SIPURI(host=account.id.domain)
            else:
                uri = target
            lookup = DNSLookup()
            try:
                tls_name = account.sip.tls_name if account is not BonjourAccount() else None
                routes = lookup.lookup_sip_proxy(uri, settings.sip.transport_list, tls_name=tls_name).wait()
            except DNSLookupError as e:
                self.state = 'failed'
                notification_center.post_notification('SIPSessionTransferDidFail', sender=self.session, data=NotificationData(code=0, reason="DNS lookup failed: {}".format(e)))
                try:
                    self.session._invitation.notify_transfer_progress(480)
                except SIPCoreError:
                    return
                while True:
                    try:
                        self._data_channel.wait()
                    except SIPInvitationTransferDidFail:
                        return
                return
            self.new_session = Session(account)
            notification_center = NotificationCenter()
            notification_center.add_observer(self, sender=self.new_session)
            self.new_session.connect(ToHeader(target), routes=routes, streams=[MediaStreamRegistry.AudioStream()], transfer_info=transfer_info)
            while True:
                try:
                    notification = self._data_channel.wait()
                except SIPInvitationTransferDidFail:
                    return
                if notification.name == 'SIPInvitationTransferDidEnd':
                    return
        except proc.ProcExit:
            if self.new_session is not None:
                notification_center.remove_observer(self, sender=self.new_session)
                self.new_session = None
            raise

    def _CH_outgoing_transfer(self, command):
        self.direction = 'outgoing'
        notification_center = NotificationCenter()
        self.completed = False
        self.state = 'starting'
        while True:
            try:
                notification = self._data_channel.wait()
            except SIPInvitationTransferDidFail as e:
                self.state = None
                self.direction = None
                notification_center.post_notification('SIPSessionTransferDidFail', sender=self.session, data=NotificationData(code=e.data.code, reason=e.data.reason))
                return
            if notification.name == 'SIPInvitationTransferDidStart':
                self.state = 'started'
                notification_center.post_notification('SIPSessionTransferDidStart', sender=self.session)
            elif notification.name == 'SIPInvitationTransferDidEnd':
                self.state = None
                self.direction = None
                self.session.end()
                notification_center.post_notification('SIPSessionTransferDidEnd', sender=self.session)
                return

    def _terminate(self):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=self.session._invitation)
        notification_center.remove_observer(self, sender=self.session)
        self._proc.kill()
        self._proc = None
        self._command_channel = None
        self._data_channel = None
        self.session = None

    @run_in_twisted_thread
    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def _NH_SIPInvitationTransferNewIncoming(self, notification):
        self._command_channel.send(Command('incoming_transfer', data=notification.data))

    def _NH_SIPInvitationTransferNewOutgoing(self, notification):
        self._command_channel.send(Command('outgoing_transfer', data=notification.data))

    def _NH_SIPInvitationTransferDidStart(self, notification):
        self._data_channel.send(notification)

    def _NH_SIPInvitationTransferDidFail(self, notification):
        self.direction = None
        if not self.completed:
            self._data_channel.send_exception(SIPInvitationTransferDidFail(notification.data))

    def _NH_SIPInvitationTransferDidEnd(self, notification):
        self.direction = None
        self._data_channel.send(notification)

    def _NH_SIPInvitationTransferGotNotify(self, notification):
        if notification.data.event == 'refer' and notification.data.body:
            match = sipfrag_re.match(notification.data.body.decode())
            if match:
                code = int(match.group('code'))
                reason = match.group('reason')
                notification.center.post_notification('SIPSessionTransferGotProgress', sender=self.session, data=NotificationData(code=code, reason=reason))
                if code == 200:
                    self.completed = True
                    self.direction = None
                    self.state = None
                    notification.center.post_notification('SIPSessionTransferDidEnd', sender=self.session)
                elif code >= 400:
                    self.state = None
                    self.direction = None
                    notification.center.post_notification('SIPSessionTransferDidFail', sender=self.session, data=NotificationData(code=code, reason=reason))

    def _NH_SIPSessionTransferDidStart(self, notification):
        if notification.sender is self.session and self.state == 'starting':
            self._data_channel.send(notification)

    def _NH_SIPSessionTransferDidFail(self, notification):
        if notification.sender is self.session and self.state == 'starting':
            self._data_channel.send(notification)

    def _NH_SIPSessionGotRingIndication(self, notification):
        if notification.sender is self.new_session and self.session is not None:
            try:
                self.session._invitation.notify_transfer_progress(180)
            except SIPCoreError:
                pass

    def _NH_SIPSessionGotProvisionalResponse(self, notification):
        if notification.sender is self.new_session and self.session is not None:
            try:
                self.session._invitation.notify_transfer_progress(notification.data.code, notification.data.reason)
            except SIPCoreError:
                pass

    def _NH_SIPSessionDidStart(self, notification):
        if notification.sender is self.new_session:
            notification.center.remove_observer(self, sender=notification.sender)
            self.new_session = None
            if self.session is not None:
                notification.center.post_notification('SIPSessionTransferDidEnd', sender=self.session)
                if self.state == 'started':
                    try:
                        self.session._invitation.notify_transfer_progress(200)
                    except SIPCoreError:
                        pass
                self.state = 'ended'
                self.session.end()

    def _NH_SIPSessionDidEnd(self, notification):
        if notification.sender is self.new_session:
            # If any stream fails to start we won't get SIPSessionDidFail, we'll get here instead
            notification.center.remove_observer(self, sender=notification.sender)
            self.new_session = None
            if self.session is not None:
                notification.center.post_notification('SIPSessionTransferDidFail', sender=self.session, data=NotificationData(code=500, reason='internal error'))
                if self.state == 'started':
                    try:
                        self.session._invitation.notify_transfer_progress(500)
                    except SIPCoreError:
                        pass
                self.state = 'failed'
        else:
            self._terminate()

    def _NH_SIPSessionDidFail(self, notification):
        if notification.sender is self.new_session:
            notification.center.remove_observer(self, sender=notification.sender)
            self.new_session = None
            if self.session is not None:
                notification.center.post_notification('SIPSessionTransferDidFail', sender=self.session, data=NotificationData(code=notification.data.code or 500, reason=notification.data.reason))
                if self.state == 'started':
                    try:
                        self.session._invitation.notify_transfer_progress(notification.data.code or 500, notification.data.reason)
                    except SIPCoreError:
                        pass
                self.state = 'failed'
        else:
            self._terminate()


class OptionalTag(str):
    def __eq__(self, other):
        return other is None or super(OptionalTag, self).__eq__(other)

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, super(OptionalTag, self).__repr__())


@implementer(IObserver)
class SessionReplaceHandler(object):

    def __init__(self, session):
        self.session = session

    def start(self):
        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=self.session)
        notification_center.add_observer(self, sender=self.session.replaced_session)

    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def _NH_SIPSessionDidStart(self, notification):
        notification.center.remove_observer(self, sender=self.session)
        notification.center.remove_observer(self, sender=self.session.replaced_session)
        self.session.replaced_session.end()
        self.session.replaced_session = None
        self.session = None

    def _NH_SIPSessionDidFail(self, notification):
        if notification.sender is self.session:
            notification.center.remove_observer(self, sender=self.session)
            notification.center.remove_observer(self, sender=self.session.replaced_session)
            self.session.replaced_session = None
            self.session = None

    _NH_SIPSessionDidEnd = _NH_SIPSessionDidFail

@implementer(IObserver)
class OFLSession(Session):

    media_stream_timeout = 15
    short_reinvite_timeout = 5

    def __init__(self, account, client_id, weight_file, data_src):
        super().__init__(account)
        self.client_id = client_id
        self.weight_file = weight_file
        self.data_src = data_src

    def init_incoming(self, invitation, data):
        notification_center = NotificationCenter()
        remote_sdp = invitation.sdp.proposed_remote
        self.proposed_streams = []
        if remote_sdp:
            for index, media_stream in enumerate(remote_sdp.media):
                if media_stream.port != 0:
                    for stream_type in MediaStreamRegistry:
                        try:
                            stream = stream_type.new_from_sdp(self, remote_sdp, index)
                        except UnknownStreamError as e:
                            continue
                        except InvalidStreamError as e:
                            log.error("Invalid stream: {}".format(e))
                            break
                        except Exception as e:
                            log.exception("Exception occurred while setting up stream from SDP: {}".format(e))
                            break
                        else:
                            stream.index = index
                            self.proposed_streams.append(stream)
                            break
        self.direction = 'incoming'
        self.state = 'incoming'
        self.transport = invitation.transport.lower()
        self._invitation = invitation
        self.conference = ConferenceHandler(self)
        self.transfer_handler = TransferHandler(self)
        if 'isfocus' in invitation.remote_contact_header.parameters:
            self.remote_focus = True
        if 'Referred-By' in data.headers or 'Replaces' in data.headers:
            self.transfer_info = TransferInfo()
            if 'Referred-By' in data.headers:
                self.transfer_info.referred_by = data.headers['Referred-By'].body
            if 'Replaces' in data.headers:
                replaces_header = data.headers.get('Replaces')
                # Because we only allow the remote tag to be optional, it can only match established dialogs and early outgoing dialogs, but not early incoming dialogs,
                # which according to RFC3891 should be rejected with 481 (which will happen automatically by never matching them).
                if replaces_header.early_only or replaces_header.from_tag == '0':
                    replaced_dialog_id = DialogID(replaces_header.call_id, local_tag=replaces_header.to_tag, remote_tag=OptionalTag(replaces_header.from_tag))
                else:
                    replaced_dialog_id = DialogID(replaces_header.call_id, local_tag=replaces_header.to_tag, remote_tag=replaces_header.from_tag)
                session_manager = OFLSessionManager()
                try:
                    replaced_session = next(session for session in session_manager.sessions if session.dialog_id == replaced_dialog_id)
                except StopIteration:
                    invitation.send_response(481)
                    return
                else:
                    # Any matched dialog at this point is either established, terminated or early outgoing.
                    if replaced_session.state in ('terminating', 'terminated'):
                        invitation.send_response(603)
                        return
                    elif replaced_session.dialog_id.remote_tag is not None and replaces_header.early_only:  # The replaced dialog is established, but the early-only flag is set
                        invitation.send_response(486)
                        return
                    self.replaced_session = replaced_session
                    self.transfer_info.replaced_dialog_id = replaced_dialog_id
                    replace_handler = SessionReplaceHandler(self)
                    replace_handler.start()
        notification_center.add_observer(self, sender=invitation)
        notification_center.post_notification('SIPSessionNewIncoming', sender=self, data=NotificationData(streams=self.proposed_streams[:], headers=data.headers))

    
    #Hsu
    def generate_sdp(self, local_ip):
        sdp = SDPSession(local_ip.encode(), name="SLAMDevice".encode())
        conn = SDPConnection(local_ip.encode())
        port = find_free_udp_port()
        media = SDPMediaStream("video".encode(), port, "RTP/AVP".encode())
        media.formats = ['96'.encode()]
        resolution = self.data_src.replace("x", "*")
        media.attributes = [
            SDPAttribute("rtpmap".encode(), "96 H264/90000".encode()), 
            SDPAttribute('sendonly'.encode(), "".encode()),
            SDPAttribute("fmtp".encode(), f"96 profile-level-id=42e01f; packetization-mode=1; resolution={resolution}".encode())
        ]
        media.connection = conn
        sdp.media.append(media)
        
        return sdp
    
    def stop_media_stream(self):
        print("stop media stream -----")

        try:
            import re
            from sending_request import request_delete
            try:
                request_delete(self.client_id, re.search(r"'(.*?)'", str(self.account)).group(1))
            except Exception as e:
                print(f"Error during request_delete: {e}")
            # Use process group so we can kill children too
            if self.rtp_session:
                print("Terminating media stream process...")
                self.rtp_session.terminate()

                try:
                    self.rtp_session.wait(timeout=10)
                    print("Media stream process terminated gracefully.")
                except subprocess.TimeoutExpired:
                    print("Process did not terminate in time. Sending SIGKILL...")
                    try:
                        # Kill the whole process group
                        os.killpg(os.getpgid(self.rtp_session.pid), signal.SIGKILL)
                        self.rtp_session.wait(timeout=5)
                        print("Process killed.")
                    except Exception as kill_error:
                        print(f"Failed to kill process: {kill_error}")
        except Exception as e:
            print(f"Exception in stop_media_stream: {e}")
        finally:
            print("rtp_session process terminated.")
        
    def start_media_stream(self, sip_device_params, rtp_device_params):
        sip_device_params_json_str = json.dumps(sip_device_params)
        rtp_device_params_json_str = json.dumps(rtp_device_params)

        # self.rtp_session = subprocess.Popen(["python3","../../AIoTtalk_plus_Lib/example/send_data/send_img.py", sip_device_params_json_str, rtp_device_params_json_str, self.client_id, self.weight_file, self.data_src])
        self.rtp_session = subprocess.Popen(
            ["python3", "../../AIoTtalk_plus_Lib/example/send_data/send_img.py", sip_device_params_json_str, rtp_device_params_json_str, self.client_id, self.weight_file, self.data_src],
            preexec_fn=os.setsid  # Only on UNIX/Linux/MacOS
        )
        print("start_media_stream!")


@implementer(IObserver)
class OFLSessionManager(SessionManager):

    @run_in_twisted_thread
    def handle_notification(self, notification):
        if notification.name == 'SIPInvitationChangedState' and notification.data.state == 'incoming':
            account_manager = AccountManager()
            account = account_manager.find_account(notification.data.request_uri)
            if account is None:
                notification.sender.send_response(404)
                return
            notification.sender.send_response(100)
            session = OFLSession(account)
            session.init_incoming(notification.sender, notification.data)
        elif notification.name in ('SIPSessionNewIncoming', 'SIPSessionNewOutgoing'):
            self.sessions.append(notification.sender)
        elif notification.name in ('SIPSessionDidFail', 'SIPSessionDidEnd'):
            self.sessions.remove(notification.sender)
            if self.state == 'stopping':
                self._channel.send(notification)
