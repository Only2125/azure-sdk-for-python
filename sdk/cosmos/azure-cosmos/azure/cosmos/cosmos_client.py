﻿# The MIT License (MIT)
# Copyright (c) 2014 Microsoft Corporation

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Create, read, and delete databases in the Azure Cosmos DB SQL API service.
"""

# pylint: disable=unused-import
from typing import Any, Dict, Mapping, Optional, Union, cast, Iterable, List

import six
from azure.core.tracing.decorator import distributed_trace  # type: ignore

from ._cosmos_client_connection import CosmosClientConnection
from ._base import build_options
from .database import DatabaseProxy
from .documents import ConnectionPolicy, DatabaseAccount
from .errors import CosmosResourceNotFoundError

__all__ = ("CosmosClient",)


def _parse_connection_str(conn_str, credential):
    # type: (str, Optional[Any]) -> Dict[str, str]
    conn_str = conn_str.rstrip(";")
    conn_settings = dict(  # type: ignore  # pylint: disable=consider-using-dict-comprehension
        s.split("=", 1) for s in conn_str.split(";")
    )
    if 'AccountEndpoint' not in conn_settings:
        raise ValueError("Connection string missing setting 'AccountEndpoint'.")
    if not credential and 'AccountKey' not in conn_settings:
        raise ValueError("Connection string missing setting 'AccountKey'.")
    return conn_settings


def _build_auth(credential):
    # type: (Any) -> Dict[str, Any]
    auth = {}
    if isinstance(credential, six.string_types):
        auth['masterKey'] = credential
    elif isinstance(credential, dict):
        if any(k for k in credential.keys() if k in ['masterKey', 'resourceTokens', 'permissionFeed']):
            return credential  # Backwards compatible
        auth['resourceTokens'] = credential  # type: ignore
    elif hasattr(credential, '__iter__'):
        auth['permissionFeed'] = credential
    else:
        raise TypeError(
            "Unrecognized credential type. Please supply the master key as str, "
            "or a dictionary or resource tokens, or a list of permissions.")
    return auth


def _build_connection_policy(kwargs):
    # type: (Dict[str, Any]) -> ConnectionPolicy
    # pylint: disable=protected-access
    policy = kwargs.pop('connection_policy', None) or ConnectionPolicy()

    # Connection config
    policy.RequestTimeout = kwargs.pop('request_timeout', None) or \
        kwargs.pop('connection_timeout', None) or \
        policy.RequestTimeout
    policy.MediaRequestTimeout = kwargs.pop('media_request_timeout', None) or policy.MediaRequestTimeout
    policy.ConnectionMode = kwargs.pop('connection_mode', None) or policy.ConnectionMode
    policy.MediaReadMode = kwargs.pop('media_read_mode', None) or policy.MediaReadMode
    policy.ProxyConfiguration = kwargs.pop('proxy_config', None) or policy.ProxyConfiguration
    policy.EnableEndpointDiscovery = kwargs.pop('enable_endpoint_discovery', None) or policy.EnableEndpointDiscovery
    policy.PreferredLocations = kwargs.pop('preferred_locations', None) or policy.PreferredLocations
    policy.UseMultipleWriteLocations = kwargs.pop('multiple_write_locations', None) or \
        policy.UseMultipleWriteLocations

    # SSL config
    verify = kwargs.pop('connection_verify', None)
    policy.DisableSSLVerification = not bool(verify if verify is not None else True)
    ssl = kwargs.pop('ssl_config', None) or policy.SSLConfiguration
    if ssl:
        ssl.SSLCertFile = kwargs.pop('connection_cert', None) or ssl.SSLCertFile
        ssl.SSLCaCerts = verify or ssl.SSLCaCerts
        policy.SSLConfiguration = ssl

    # Retry config
    retry = kwargs.pop('retry_options', None) or policy.RetryOptions
    retry._max_retry_attempt_count = kwargs.pop('retry_total', None) or retry._max_retry_attempt_count
    retry._fixed_retry_interval_in_milliseconds = kwargs.pop('retry_fixed_interval', None) or \
        retry._fixed_retry_interval_in_milliseconds
    retry._max_wait_time_in_seconds = kwargs.pop('retry_backoff_max', None) or retry._max_wait_time_in_seconds
    policy.RetryOptions = retry

    return policy


class CosmosClient(object):
    """
    Provides a client-side logical representation of an Azure Cosmos DB account.
    Use this client to configure and execute requests to the Azure Cosmos DB service.

    :param str url: The URL of the Cosmos DB account.
    :param credential:
        Can be the account key, or a dictionary of resource tokens.
    :type credential: str or dict(str, str)
    :param str consistency_level:
        Consistency level to use for the session. The default value is "Session".

    **Keyword arguments:**

    *request_timeout* - The HTTP request timeout in seconds.
    *media_request_timeout* - The media request timeout in seconds.
    *connection_mode* - The connection mode for the client - currently only supports 'Gateway'.
    *media_read_mode* - The mode for use with downloading attachment content - default value is `Buffered`.
    *proxy_config* - Instance of ~azure.cosmos.documents.ProxyConfiguration
    *ssl_config* - Instance of ~azure.cosmos.documents.SSLConfiguration
    *connection_verify* - Whether to verify the connection, default value is True.
    *connection_cert* - An alternative certificate to verify the connection.
    *retry_total* - Maximum retry attempts.
    *retry_backoff_max* - Maximum retry wait time in seconds.
    *retry_fixed_interval* - Fixed retry interval in milliseconds.
    *enable_endpoint_discovery* - Enable endpoint discovery for geo-replicated database accounts. Default is True.
    *preferred_locations* - The preferred locations for geo-replicated database accounts.
        When `enable_endpoint_discovery` is true and `preferred_locations` is non-empty,
        the client will use this list to evaluate the final location, taking into consideration
        the order specified in `preferred_locations` list. The locations in this list are specified
        as the names of the azure Cosmos locations like, 'West US', 'East US', 'Central India'
        and so on.
    *connection_policy* - An instance of ~azure.cosmos.documents.ConnectionPolicy

    .. literalinclude:: ../../samples/examples.py
        :start-after: [START create_client]
        :end-before: [END create_client]
        :language: python
        :dedent: 0
        :caption: Create a new instance of the Cosmos DB client:
        :name: create_client
    """

    def __init__(self, url, credential, consistency_level="Session", **kwargs):
        # type: (str, Any, str, Any) -> None
        """ Instantiate a new CosmosClient."""
        auth = _build_auth(credential)
        connection_policy = _build_connection_policy(kwargs)
        self.client_connection = CosmosClientConnection(
            url, auth=auth, consistency_level=consistency_level, connection_policy=connection_policy, **kwargs
        )

    def __enter__(self):
        self.client_connection.pipeline_client.__enter__()
        return self

    def __exit__(self, *args):
        return self.client_connection.pipeline_client.__exit__(*args)

    @classmethod
    def from_connection_string(cls, conn_str, credential=None, consistency_level="Session", **kwargs):
        # type: (str, Optional[Any], str, Any) -> CosmosClient
        """
        Create CosmosClient from a connection string.

        This can be retrieved from the Azure portal.For full list of optional keyword
        arguments, see the CosmosClient constructor.

        :param str conn_str: The connection string.
        :param credential: Alternative credentials to use instead of the key provided in the
            connection string.
        :type credential: str or dict(str, str)
        :param str consistency_level: Consistency level to use for the session. The default value is "Session".
        """
        settings = _parse_connection_str(conn_str, credential)
        return cls(
            url=settings['AccountEndpoint'],
            credential=credential or settings['AccountKey'],
            consistency_level=consistency_level,
            **kwargs
        )

    @staticmethod
    def _get_database_link(database_or_id):
        # type: (Union[DatabaseProxy, str, Dict[str, str]]) -> str
        if isinstance(database_or_id, six.string_types):
            return "dbs/{}".format(database_or_id)
        try:
            return cast("DatabaseProxy", database_or_id).database_link
        except AttributeError:
            pass
        database_id = cast("Dict[str, str]", database_or_id)["id"]
        return "dbs/{}".format(database_id)

    @distributed_trace
    def create_database(  # pylint: disable=redefined-builtin
        self,
        id,  # type: str
        populate_query_metrics=None,  # type: Optional[bool]
        offer_throughput=None,  # type: Optional[int]
        **kwargs  # type: Any
    ):
        # type: (...) -> DatabaseProxy
        """
        Create a new database with the given ID (name).

        :param id: ID (name) of the database to create.
        :param str session_token: Token for use with Session consistency.
        :param dict(str, str) initial_headers: Initial headers to be sent as part of the request.
        :param dict(str, str) access_condition: Conditions Associated with the request.
        :param bool populate_query_metrics: Enable returning query metrics in response headers.
        :param int offer_throughput: The provisioned throughput for this offer.
        :param dict(str, Any) request_options: Dictionary of additional properties to be used for the request.
        :param Callable response_hook: a callable invoked with the response metadata
        :returns: A DatabaseProxy instance representing the new database.
        :rtype: ~azure.cosmos.database.DatabaseProxy
        :raises `CosmosResourceExistsError`: If database with the given ID already exists.

        .. literalinclude:: ../../samples/examples.py
            :start-after: [START create_database]
            :end-before: [END create_database]
            :language: python
            :dedent: 0
            :caption: Create a database in the Cosmos DB account:
            :name: create_database

        """

        request_options = build_options(kwargs)
        response_hook = kwargs.pop('response_hook', None)
        if populate_query_metrics is not None:
            request_options["populateQueryMetrics"] = populate_query_metrics
        if offer_throughput is not None:
            request_options["offerThroughput"] = offer_throughput

        result = self.client_connection.CreateDatabase(database=dict(id=id), options=request_options, **kwargs)
        if response_hook:
            response_hook(self.client_connection.last_response_headers)
        return DatabaseProxy(self.client_connection, id=result["id"], properties=result)

    @distributed_trace
    def create_database_if_not_exists(  # pylint: disable=redefined-builtin
        self,
        id,  # type: str
        populate_query_metrics=None,  # type: Optional[bool]
        offer_throughput=None,  # type: Optional[int]
        **kwargs  # type: Any
    ):
        # type: (...) -> DatabaseProxy
        """
        Create the database if it does not exist already.

        If the database already exists, the existing settings are returned.
        Note: it does not check or update the existing database settings or offer throughput
        if they differ from what was passed into the method.

        :param id: ID (name) of the database to read or create.
        :param str session_token: Token for use with Session consistency.
        :param dict(str, str) initial_headers: Initial headers to be sent as part of the request.
        :param dict(str, str) access_condition: Conditions Associated with the request.
        :param bool populate_query_metrics: Enable returning query metrics in response headers.
        :param int offer_throughput: The provisioned throughput for this offer.
        :param dict(str, Any) request_options: Dictionary of additional properties to be used for the request.
        :param Callable response_hook: a callable invoked with the response metadata
        :returns: A DatabaseProxy instance representing the database.
        :rtype: ~azure.cosmos.database.DatabaseProxy
        :raise CosmosHttpResponseError: The database read or creation failed.
        """
        try:
            database_proxy = self.get_database_client(id)
            database_proxy.read(
                populate_query_metrics=populate_query_metrics,
                **kwargs
            )
            return database_proxy
        except CosmosResourceNotFoundError:
            return self.create_database(
                id,
                populate_query_metrics=populate_query_metrics,
                offer_throughput=offer_throughput,
                **kwargs
            )

    def get_database_client(self, database):
        # type: (Union[str, DatabaseProxy, Dict[str, Any]]) -> DatabaseProxy
        """
        Retrieve an existing database with the ID (name) `id`.

        :param database: The ID (name), dict representing the properties or `DatabaseProxy`
            instance of the database to read.
        :type database: str or dict(str, str) or ~azure.cosmos.database.DatabaseProxy
        :returns: A `DatabaseProxy` instance representing the retrieved database.
        :rtype: ~azure.cosmos.database.DatabaseProxy
        """
        if isinstance(database, DatabaseProxy):
            id_value = database.id
        elif isinstance(database, Mapping):
            id_value = database["id"]
        else:
            id_value = database

        return DatabaseProxy(self.client_connection, id_value)

    @distributed_trace
    def list_databases(
        self,
        max_item_count=None,  # type: Optional[int]
        populate_query_metrics=None,  # type: Optional[bool]
        **kwargs  # type: Any
    ):
        # type: (...) -> Iterable[Dict[str, Any]]
        """
        List the databases in a Cosmos DB SQL database account.

        :param int max_item_count: Max number of items to be returned in the enumeration operation.
        :param str session_token: Token for use with Session consistency.
        :param dict[str, str] initial_headers: Initial headers to be sent as part of the request.
        :param bool populate_query_metrics: Enable returning query metrics in response headers.
        :param dict[str, str] feed_options: Dictionary of additional properties to be used for the request.
        :param Callable response_hook: a callable invoked with the response metadata
        :returns: An Iterable of database properties (dicts).
        :rtype: Iterable[dict[str, str]]
        """
        feed_options = build_options(kwargs)
        response_hook = kwargs.pop('response_hook', None)
        if max_item_count is not None:
            feed_options["maxItemCount"] = max_item_count
        if populate_query_metrics is not None:
            feed_options["populateQueryMetrics"] = populate_query_metrics

        result = self.client_connection.ReadDatabases(options=feed_options, **kwargs)
        if response_hook:
            response_hook(self.client_connection.last_response_headers)
        return result

    @distributed_trace
    def query_databases(
        self,
        query=None,  # type: Optional[str]
        parameters=None,  # type: Optional[List[str]]
        enable_cross_partition_query=None,  # type: Optional[bool]
        max_item_count=None,  # type:  Optional[int]
        populate_query_metrics=None,  # type: Optional[bool]
        **kwargs  # type: Any
    ):
        # type: (...) -> Iterable[Dict[str, Any]]
        """
        Query the databases in a Cosmos DB SQL database account.

        :param str query: The Azure Cosmos DB SQL query to execute.
        :param list[str] parameters: Optional array of parameters to the query. Ignored if no query is provided.
        :param bool enable_cross_partition_query: Allow scan on the queries which couldn't be
            served as indexing was opted out on the requested paths.
        :param int max_item_count: Max number of items to be returned in the enumeration operation.
        :param str session_token: Token for use with Session consistency.
        :param dict[str, str] initial_headers: Initial headers to be sent as part of the request.
        :param bool populate_query_metrics: Enable returning query metrics in response headers.
        :param dict[str, Any] feed_options: Dictionary of additional properties to be used for the request.
        :param Callable response_hook: a callable invoked with the response metadata
        :returns: An Iterable of database properties (dicts).
        :rtype: Iterable[dict[str, str]]
        """
        feed_options = build_options(kwargs)
        response_hook = kwargs.pop('response_hook', None)
        if enable_cross_partition_query is not None:
            feed_options["enableCrossPartitionQuery"] = enable_cross_partition_query
        if max_item_count is not None:
            feed_options["maxItemCount"] = max_item_count
        if populate_query_metrics is not None:
            feed_options["populateQueryMetrics"] = populate_query_metrics

        if query:
            # This is currently eagerly evaluated in order to capture the headers
            # from the call.
            # (just returning a generator did not initiate the first network call, so
            # the headers were misleading)
            # This needs to change for "real" implementation
            query = query if parameters is None else dict(query=query, parameters=parameters)  # type: ignore
            result = self.client_connection.QueryDatabases(query=query, options=feed_options, **kwargs)
        else:
            result = self.client_connection.ReadDatabases(options=feed_options, **kwargs)
        if response_hook:
            response_hook(self.client_connection.last_response_headers)
        return result

    @distributed_trace
    def delete_database(
        self,
        database,  # type: Union[str, DatabaseProxy, Dict[str, Any]]
        populate_query_metrics=None,  # type: Optional[bool]
        **kwargs  # type: Any
    ):
        # type: (...) -> None
        """
        Delete the database with the given ID (name).

        :param database: The ID (name), dict representing the properties or :class:`DatabaseProxy`
            instance of the database to delete.
        :type database: str or dict(str, str) or ~azure.cosmos.database.DatabaseProxy
        :param str session_token: Token for use with Session consistency.
        :param dict[str, str] initial_headers: Initial headers to be sent as part of the request.
        :param dict[str, str] access_condition: Conditions Associated with the request.
        :param bool populate_query_metrics: Enable returning query metrics in response headers.
        :param dict[str, str] request_options: Dictionary of additional properties to be used for the request.
        :param Callable response_hook: a callable invoked with the response metadata
        :raise CosmosHttpResponseError: If the database couldn't be deleted.
        :rtype: None
        """
        request_options = build_options(kwargs)
        response_hook = kwargs.pop('response_hook', None)
        if populate_query_metrics is not None:
            request_options["populateQueryMetrics"] = populate_query_metrics

        database_link = self._get_database_link(database)
        self.client_connection.DeleteDatabase(database_link, options=request_options, **kwargs)
        if response_hook:
            response_hook(self.client_connection.last_response_headers)

    @distributed_trace
    def get_database_account(self, **kwargs):
        # type: (Any) -> DatabaseAccount
        """
        Retrieve the database account information.

        :param Callable response_hook: a callable invoked with the response metadata
        :returns: A `DatabaseAccount` instance representing the Cosmos DB Database Account.
        :rtype: ~azure.cosmos.documents.DatabaseAccount
        """
        response_hook = kwargs.pop('response_hook', None)
        result = self.client_connection.GetDatabaseAccount(**kwargs)
        if response_hook:
            response_hook(self.client_connection.last_response_headers)
        return result
