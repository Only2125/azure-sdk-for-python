# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from __future__ import unicode_literals

import logging
import sys
import platform
import uuid
import time
from abc import abstractmethod
from typing import Union, Any, TYPE_CHECKING

from uamqp import types  # type: ignore
from azure.eventhub import __version__
from azure.eventhub.configuration import _Configuration
from .common import EventHubSharedKeyCredential, EventHubSASTokenCredential, _Address

try:
    from urlparse import urlparse  # type: ignore
    from urllib import urlencode, quote_plus  # type: ignore
except ImportError:
    from urllib.parse import urlparse, urlencode, quote_plus

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential  # type: ignore

log = logging.getLogger(__name__)
MAX_USER_AGENT_LENGTH = 512


def _parse_conn_str(conn_str):
    endpoint = None
    shared_access_key_name = None
    shared_access_key = None
    entity_path = None
    for element in conn_str.split(';'):
        key, _, value = element.partition('=')
        if key.lower() == 'endpoint':
            endpoint = value.rstrip('/')
        elif key.lower() == 'hostname':
            endpoint = value.rstrip('/')
        elif key.lower() == 'sharedaccesskeyname':
            shared_access_key_name = value
        elif key.lower() == 'sharedaccesskey':
            shared_access_key = value
        elif key.lower() == 'entitypath':
            entity_path = value
    if not all([endpoint, shared_access_key_name, shared_access_key]):
        raise ValueError("Invalid connection string")
    return endpoint, shared_access_key_name, shared_access_key, entity_path


def _generate_sas_token(uri, policy, key, expiry=None):
    """Create a shared access signiture token as a string literal.
    :returns: SAS token as string literal.
    :rtype: str
    """
    from base64 import b64encode, b64decode
    from hashlib import sha256
    from hmac import HMAC
    if not expiry:
        expiry = time.time() + 3600  # Default to 1 hour.
    encoded_uri = quote_plus(uri)
    ttl = int(expiry)
    sign_key = '%s\n%d' % (encoded_uri, ttl)
    signature = b64encode(HMAC(b64decode(key), sign_key.encode('utf-8'), sha256).digest())
    result = {
        'sr': uri,
        'sig': signature,
        'se': str(ttl)}
    if policy:
        result['skn'] = policy
    return 'SharedAccessSignature ' + urlencode(result)


def _build_uri(address, entity):
    parsed = urlparse(address)
    if parsed.path:
        return address
    if not entity:
        raise ValueError("No EventHub specified")
    address += "/" + str(entity)
    return address


class EventHubClientAbstract(object):  # pylint:disable=too-many-instance-attributes
    """
    The EventHubClientAbstract class defines a high level interface for sending
    events to and receiving events from the Azure Event Hubs service.
    """

    def __init__(self, host, event_hub_path, credential, **kwargs):
        # type:(str, str, Union[EventHubSharedKeyCredential, EventHubSASTokenCredential, TokenCredential], Any) -> None
        """
        Constructs a new EventHubClient.

        :param host: The hostname of the Event Hub.
        :type host: str
        :param event_hub_path: The path of the specific Event Hub to connect the client to.
        :type event_hub_path: str
        :param network_tracing: Whether to output network trace logs to the logger. Default
         is `False`.
        :type network_tracing: bool
        :param credential: The credential object used for authentication which implements particular interface
         of getting tokens. It accepts ~azure.eventhub.EventHubSharedKeyCredential,
         ~azure.eventhub.EventHubSASTokenCredential, credential objects generated by the azure-identity library and
         objects that implement get_token(self, *scopes) method.
        :param http_proxy: HTTP proxy settings. This must be a dictionary with the following
         keys: 'proxy_hostname' (str value) and 'proxy_port' (int value).
         Additionally the following keys may also be present: 'username', 'password'.
        :type http_proxy: dict[str, Any]
        :param auth_timeout: The time in seconds to wait for a token to be authorized by the service.
         The default value is 60 seconds. If set to 0, no timeout will be enforced from the client.
        :type auth_timeout: float
        :param user_agent: The user agent that needs to be appended to the built in user agent string.
        :type user_agent: str
        :param retry_total: The total number of attempts to redo the failed operation when an error happened. Default
         value is 3.
        :type retry_total: int
        :param transport_type: The type of transport protocol that will be used for communicating with
         the Event Hubs service. Default is ~azure.eventhub.TransportType.Amqp.
        :type transport_type: ~azure.eventhub.TransportType
        :param prefetch: The message prefetch count of the consumer. Default is 300.
        :type prefetch: int
        :param max_batch_size: Receive a batch of events. Batch size will be up to the maximum specified, but
         will return as soon as service returns no new events. Default value is the same as prefetch.
        :type max_batch_size: int
        :param receive_timeout: The timeout in seconds to receive a batch of events from an Event Hub.
         Default value is 0 seconds.
        :type receive_timeout: float
        :param send_timeout: The timeout in seconds for an individual event to be sent from the time that it is
         queued. Default value is 60 seconds. If set to 0, there will be no timeout.
        :type send_timeout: float
        """
        self.eh_name = event_hub_path
        self._host = host
        self._container_id = "eventhub.pysdk-" + str(uuid.uuid4())[:8]
        self._address = _Address()
        self._address.hostname = host
        self._address.path = "/" + event_hub_path if event_hub_path else ""
        self._credential = credential
        self._keep_alive = kwargs.get("keep_alive", 30)
        self._auto_reconnect = kwargs.get("auto_reconnect", True)
        self._mgmt_target = "amqps://{}/{}".format(self._host, self.eh_name)
        self._auth_uri = "sb://{}{}".format(self._address.hostname, self._address.path)
        self._config = _Configuration(**kwargs)
        self._debug = self._config.network_tracing

        log.info("%r: Created the Event Hub client", self._container_id)

    @abstractmethod
    def _create_auth(self):
        pass

    def _create_properties(self, user_agent=None):  # pylint: disable=no-self-use
        """
        Format the properties with which to instantiate the connection.
        This acts like a user agent over HTTP.

        :rtype: dict
        """
        properties = {}
        product = "azure-eventhub"
        properties[types.AMQPSymbol("product")] = product
        properties[types.AMQPSymbol("version")] = __version__
        framework = "Python {}.{}.{}, {}".format(
            sys.version_info[0], sys.version_info[1], sys.version_info[2], platform.python_implementation()
        )
        properties[types.AMQPSymbol("framework")] = framework
        platform_str = platform.platform()
        properties[types.AMQPSymbol("platform")] = platform_str

        final_user_agent = '{}/{} ({}, {})'.format(product, __version__, framework, platform_str)
        if user_agent:
            final_user_agent = '{}, {}'.format(final_user_agent, user_agent)

        if len(final_user_agent) > MAX_USER_AGENT_LENGTH:
            raise ValueError("The user-agent string cannot be more than {} in length."
                             "Current user_agent string is: {} with length: {}".format(
                                MAX_USER_AGENT_LENGTH, final_user_agent, len(final_user_agent)))
        properties[types.AMQPSymbol("user-agent")] = final_user_agent
        return properties

    def _add_span_request_attributes(self, span):
        span.add_attribute("component", "eventhubs")
        span.add_attribute("message_bus.destination", self._address.path)
        span.add_attribute("peer.address", self._address.hostname)

    @classmethod
    def from_connection_string(cls, conn_str, **kwargs):
        """Create an EventHubClient from an EventHub connection string.

        :param conn_str: The connection string of an eventhub
        :type conn_str: str
        :param event_hub_path: The path of the specific Event Hub to connect the client to, if the EntityName is
         not included in the connection string.
        :type event_hub_path: str
        :param network_tracing: Whether to output network trace logs to the logger. Default
         is `False`.
        :type network_tracing: bool
        :param http_proxy: HTTP proxy settings. This must be a dictionary with the following
         keys: 'proxy_hostname' (str value) and 'proxy_port' (int value).
         Additionally the following keys may also be present: 'username', 'password'.
        :type http_proxy: dict[str, Any]
        :param auth_timeout: The time in seconds to wait for a token to be authorized by the service.
         The default value is 60 seconds. If set to 0, no timeout will be enforced from the client.
        :type auth_timeout: float
        :param user_agent: The user agent that needs to be appended to the built in user agent string.
        :type user_agent: str
        :param retry_total: The total number of attempts to redo the failed operation when an error happened. Default
         value is 3.
        :type retry_total: int
        :param transport_type: The type of transport protocol that will be used for communicating with
         the Event Hubs service. Default is ~azure.eventhub.TransportType.Amqp.
        :type transport_type: ~azure.eventhub.TransportType
        :param prefetch: The message prefetch count of the consumer. Default is 300.
        :type prefetch: int
        :param max_batch_size: Receive a batch of events. Batch size will be up to the maximum specified, but
         will return as soon as service returns no new events. Default value is the same as prefetch.
        :type max_batch_size: int
        :param receive_timeout: The timeout in seconds to receive a batch of events from an Event Hub.
         Default value is 0 seconds, meaning there is no timeout.
        :type receive_timeout: float
        :param send_timeout: The timeout in seconds for an individual event to be sent from the time that it is
         queued. Default value is 60 seconds. If set to 0, there will be no timeout.
        :type send_timeout: float

        Example:
            .. literalinclude:: ../examples/test_examples_eventhub.py
                :start-after: [START create_eventhub_client_connstr]
                :end-before: [END create_eventhub_client_connstr]
                :language: python
                :dedent: 4
                :caption: Create an EventHubClient from a connection string.

        """
        event_hub_path = kwargs.pop("event_hub_path", None)
        address, policy, key, entity = _parse_conn_str(conn_str)
        entity = event_hub_path or entity
        left_slash_pos = address.find("//")
        if left_slash_pos != -1:
            host = address[left_slash_pos + 2:]
        else:
            host = address
        return cls(host, entity, EventHubSharedKeyCredential(policy, key), **kwargs)
