# The MIT License (MIT)
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

"""Synchronized request in the Azure Cosmos database service.
"""

import json

from six.moves.urllib.parse import urlparse
import six
from azure.core.exceptions import DecodeError  # type: ignore

from . import documents
from . import errors
from . import http_constants
from . import _retry_utility


def _is_readable_stream(obj):
    """Checks whether obj is a file-like readable stream.

    :rtype: boolean
    """
    if hasattr(obj, "read") and callable(getattr(obj, "read")):
        return True
    return False


def _request_body_from_data(data):
    """Gets request body from data.

    When `data` is dict and list into unicode string; otherwise return `data`
    without making any change.

    :param (str, unicode, file-like stream object, dict, list or None) data:

    :rtype:
        str, unicode, file-like stream object, or None

    """
    if data is None or isinstance(data, six.string_types) or _is_readable_stream(data):
        return data
    if isinstance(data, (dict, list, tuple)):

        json_dumped = json.dumps(data, separators=(",", ":"))

        if six.PY2:
            return json_dumped.decode("utf-8")
        return json_dumped
    return None


def _Request(global_endpoint_manager, request_params, connection_policy, pipeline_client, request, **kwargs):
    """Makes one http request using the requests module.

    :param _GlobalEndpointManager global_endpoint_manager:
    :param dict request_params:
        contains the resourceType, operationType, endpointOverride,
        useWriteEndpoint, useAlternateWriteEndpoint information
    :param documents.ConnectionPolicy connection_policy:
    :param azure.core.PipelineClient pipeline_client:
        Pipeline client to process the resquest
    :param azure.core.HttpRequest request:
        The request object to send through the pipeline

    :return:
        tuple of (result, headers)
    :rtype:
        tuple of (dict, dict)

    """
    # pylint: disable=protected-access

    is_media = request.url.find("media") > -1
    is_media_stream = is_media and connection_policy.MediaReadMode == documents.MediaReadMode.Streamed

    connection_timeout = connection_policy.MediaRequestTimeout if is_media else connection_policy.RequestTimeout
    connection_timeout = kwargs.pop("connection_timeout", connection_timeout / 1000.0)

    # Every request tries to perform a refresh
    global_endpoint_manager.refresh_endpoint_list(None)

    if request_params.endpoint_override:
        base_url = request_params.endpoint_override
    else:
        base_url = global_endpoint_manager.resolve_service_endpoint(request_params)
    if base_url != pipeline_client._base_url:
        request.url = request.url.replace(pipeline_client._base_url, base_url)

    parse_result = urlparse(request.url)

    # The requests library now expects header values to be strings only starting 2.11,
    # and will raise an error on validation if they are not, so casting all header values to strings.
    request.headers.update({header: str(value) for header, value in request.headers.items()})

    # We are disabling the SSL verification for local emulator(localhost/127.0.0.1) or if the user
    # has explicitly specified to disable SSL verification.
    is_ssl_enabled = (
        parse_result.hostname != "localhost"
        and parse_result.hostname != "127.0.0.1"
        and not connection_policy.DisableSSLVerification
    )

    if connection_policy.SSLConfiguration or "connection_cert" in kwargs:
        ca_certs = connection_policy.SSLConfiguration.SSLCaCerts
        cert_files = (connection_policy.SSLConfiguration.SSLCertFile, connection_policy.SSLConfiguration.SSLKeyFile)
        response = pipeline_client._pipeline.run(
            request,
            stream=is_media_stream,
            connection_timeout=connection_timeout,
            connection_verify=kwargs.pop("connection_verify", ca_certs),
            connection_cert=kwargs.pop("connection_cert", cert_files),
            **kwargs
        )
    else:
        response = pipeline_client._pipeline.run(
            request,
            stream=is_media_stream,
            connection_timeout=connection_timeout,
            # If SSL is disabled, verify = false
            connection_verify=kwargs.pop("connection_verify", is_ssl_enabled),
            **kwargs
        )

    response = response.http_response
    headers = dict(response.headers)

    # In case of media stream response, return the response to the user and the user
    # will need to handle reading the response.
    if is_media_stream:
        return (response.stream_download(pipeline_client._pipeline), headers)

    data = response.body()
    if not six.PY2:
        # python 3 compatible: convert data from byte to unicode string
        data = data.decode("utf-8")

    if response.status_code == 404:
        raise errors.CosmosResourceNotFoundError(message=data, response=response)
    if response.status_code == 409:
        raise errors.CosmosResourceExistsError(message=data, response=response)
    if response.status_code == 412:
        raise errors.CosmosAccessConditionFailedError(message=data, response=response)
    if response.status_code >= 400:
        raise errors.CosmosHttpResponseError(message=data, response=response)

    result = None
    if is_media:
        result = data
    else:
        if data:
            try:
                result = json.loads(data)
            except Exception as e:
                raise DecodeError(
                    message="Failed to decode JSON data: {}".format(e),
                    response=response,
                    error=e)

    return (result, headers)


def SynchronizedRequest(
    client,
    request_params,
    global_endpoint_manager,
    connection_policy,
    pipeline_client,
    request,
    request_data,
    **kwargs
):
    """Performs one synchronized http request according to the parameters.

    :param object client:
        Document client instance
    :param dict request_params:
    :param _GlobalEndpointManager global_endpoint_manager:
    :param  documents.ConnectionPolicy connection_policy:
    :param azure.core.PipelineClient pipeline_client:
        PipelineClient to process the request.
    :param str method:
    :param str path:
    :param (str, unicode, file-like stream object, dict, list or None) request_data:
    :param dict query_params:
    :param dict headers:

    :return:
        tuple of (result, headers)
    :rtype:
        tuple of (dict dict)

    """
    request.data = _request_body_from_data(request_data)
    if request.data and isinstance(request.data, six.string_types):
        request.headers[http_constants.HttpHeaders.ContentLength] = len(request.data)
    elif request.data is None:
        request.headers[http_constants.HttpHeaders.ContentLength] = 0

    # Pass _Request function with it's parameters to retry_utility's Execute method that wraps the call with retries
    return _retry_utility.Execute(
        client,
        global_endpoint_manager,
        _Request,
        request_params,
        connection_policy,
        pipeline_client,
        request,
        **kwargs
    )
