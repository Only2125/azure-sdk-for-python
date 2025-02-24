# --------------------------------------------------------------------------
#
# Copyright (c) Microsoft Corporation. All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the ""Software""), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED *AS IS*, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#
# --------------------------------------------------------------------------
"""
This module is the requests implementation of Pipeline ABC
"""
from __future__ import absolute_import  # we have a "requests" module that conflicts with "requests" on Py2.7
import logging
from typing import TYPE_CHECKING, List, Callable, Iterator, Any, Union, Dict, Optional  # pylint: disable=unused-import

from azure.core.exceptions import AzureError, ClientAuthenticationError
from .base import HTTPPolicy
from .base_async import AsyncHTTPPolicy
from .retry import RetryPolicy

_LOGGER = logging.getLogger(__name__)



class AsyncRetryPolicy(RetryPolicy, AsyncHTTPPolicy):  # type: ignore
    """Async flavor of the retry policy.

    The async retry policy in the pipeline can be configured directly, or tweaked on a per-call basis.

    **Keyword arguments:**

    *retry_total (int)* - Total number of retries to allow. Takes precedence over other counts.
    Default value is 10.

    *retry_connect (int)* - How many connection-related errors to retry on.
    These are errors raised before the request is sent to the remote server,
    which we assume has not triggered the server to process the request. Default value is 3.

    *retry_read (int)* - How many times to retry on read errors.
    These errors are raised after the request was sent to the server, so the
    request may have side-effects. Default value is 3.

    *retry_status (int)* - How many times to retry on bad status codes. Default value is 3.

    *retry_backoff_factor (float)* - A backoff factor to apply between attempts after the second try
    (most errors are resolved immediately by a second try without a delay).
    Retry policy will sleep for: `{backoff factor} * (2 ** ({number of total retries} - 1))`
    seconds. If the backoff_factor is 0.1, then the retry will sleep
    for [0.0s, 0.2s, 0.4s, ...] between retries. The default value is 0.8.

    *retry_backoff_max (int)* - The maximum back off time. Default value is 120 seconds (2 minutes).

    .. admonition:: Example:

        .. literalinclude:: ../examples/test_example_async.py
            :start-after: [START async_retry_policy]
            :end-before: [END async_retry_policy]
            :language: python
            :dedent: 4
            :caption: Configuring an async retry policy.
    """

    async def _sleep_for_retry(self, response, transport):
        """Sleep based on the Retry-After response header value.

        :param response: The PipelineResponse object.
        :type response: ~azure.core.pipeline.PipelineResponse
        :param transport: The HTTP transport type.
        """
        retry_after = self.get_retry_after(response)
        if retry_after:
            await transport.sleep(retry_after)
            return True
        return False

    async def _sleep_backoff(self, settings, transport):
        """Sleep using exponential backoff. Immediately returns if backoff is 0.

        :param dict settings: The retry settings.
        :param transport: The HTTP transport type.
        """
        backoff = self.get_backoff_time(settings)
        if backoff <= 0:
            return
        await transport.sleep(backoff)

    async def sleep(self, settings, transport, response=None):
        """Sleep between retry attempts.

        This method will respect a server's ``Retry-After`` response header
        and sleep the duration of the time requested. If that is not present, it
        will use an exponential backoff. By default, the backoff factor is 0 and
        this method will return immediately.

        :param dict settings: The retry settings.
        :param transport: The HTTP transport type.
        :param response: The PipelineResponse object.
        :type response: ~azure.core.pipeline.PipelineResponse
        """
        if response:
            slept = await self._sleep_for_retry(response, transport)
            if slept:
                return
        await self._sleep_backoff(settings, transport)

    async def send(self, request):
        """Uses the configured retry policy to send the request to the next policy in the pipeline.

        :param request: The PipelineRequest object
        :type request: ~azure.core.pipeline.PipelineRequest
        :return: Returns the PipelineResponse or raises error if maximum retries exceeded.
        :rtype: ~azure.core.pipeline.PipelineResponse
        :raise: ~azure.core.exceptions.AzureError if maximum retries exceeded.
        :raise: ~azure.core.exceptions.ClientAuthenticationError if authentication fails
        """
        retry_active = True
        response = None
        retry_settings = self.configure_retries(request.context.options)
        while retry_active:
            try:
                response = await self.next.send(request)
                if self.is_retry(retry_settings, response):
                    retry_active = self.increment(retry_settings, response=response)
                    if retry_active:
                        await self.sleep(retry_settings, request.context.transport, response=response)
                        continue
                break
            except ClientAuthenticationError:  # pylint:disable=try-except-raise
                # the authentication policy failed such that the client's request can't
                # succeed--we'll never have a response to it, so propagate the exception
                raise
            except AzureError as err:
                if self._is_method_retryable(retry_settings, request.http_request):
                    retry_active = self.increment(retry_settings, response=request, error=err)
                    if retry_active:
                        await self.sleep(retry_settings, request.context.transport)
                        continue
                raise err

        self.update_context(response.context, retry_settings)
        return response
