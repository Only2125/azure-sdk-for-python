# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------
"""Implements azure.core.tracing.AbstractSpan to wrap opencensus spans."""

from opencensus.trace import Span, execution_context
from opencensus.trace.tracer import Tracer
from opencensus.trace.span import SpanKind as OpenCensusSpanKind
from opencensus.trace.link import Link
from opencensus.trace.propagation import trace_context_http_header_format

from azure.core.tracing import SpanKind  # pylint: disable=no-name-in-module

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import Dict, Optional, Union, Callable

    from azure.core.pipeline.transport import HttpRequest, HttpResponse

__version__ = "1.0.0b4"

class OpenCensusSpan(object):
    """Wraps a given OpenCensus Span so that it implements azure.core.tracing.AbstractSpan"""

    def __init__(self, span=None, name="span"):
        # type: (Optional[Span], Optional[str]) -> None
        """
        If a span is not passed in, creates a new tracer. If the instrumentation key for Azure Exporter is given, will
        configure the azure exporter else will just create a new tracer.

        :param span: The OpenCensus span to wrap
        :type span: :class: opencensus.trace.Span
        :param name: The name of the OpenCensus span to create if a new span is needed
        :type name: str
        """
        tracer = self.get_current_tracer()
        self._span_instance = span or tracer.start_span(name=name)
        self._span_component = "component"
        self._http_user_agent = "http.user_agent"
        self._http_method = "http.method"
        self._http_url = "http.url"
        self._http_status_code = "http.status_code"

    @property
    def span_instance(self):
        # type: () -> Span
        """
        :return: The OpenCensus span that is being wrapped.
        """
        return self._span_instance

    def span(self, name="span"):
        # type: (Optional[str]) -> OpenCensusSpan
        """
        Create a child span for the current span and append it to the child spans list in the span instance.
        :param name: Name of the child span
        :type name: str
        :return: The OpenCensusSpan that is wrapping the child span instance
        """
        return self.__class__(name=name)

    @property
    def kind(self):
        # type: () -> Optional[SpanKind]
        """Get the span kind of this span."""
        value = self.span_instance.span_kind
        return (
            SpanKind.CLIENT if value == OpenCensusSpanKind.CLIENT else
            SpanKind.SERVER if value == OpenCensusSpanKind.SERVER else
            SpanKind.UNSPECIFIED if value == OpenCensusSpanKind.UNSPECIFIED else
            None
        )


    @kind.setter
    def kind(self, value):
        # type: (SpanKind) -> None
        """Set the span kind of this span."""
        kind = (
            OpenCensusSpanKind.CLIENT if value == SpanKind.CLIENT else
            OpenCensusSpanKind.SERVER if value == SpanKind.SERVER else
            OpenCensusSpanKind.UNSPECIFIED if value == SpanKind.UNSPECIFIED else
            None
        )
        if kind is None:
            raise ValueError("Kind {} is not supported in OpenCensus".format(value))
        self.span_instance.span_kind = kind

    def __enter__(self):
        """Start a span."""
        self.span_instance.__enter__()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        """Finish a span."""
        self.span_instance.__exit__(exception_type, exception_value, traceback)

    def start(self):
        # type: () -> None
        """Set the start time for a span."""
        self.__enter__()

    def finish(self):
        # type: () -> None
        """Set the end time for a span."""
        self.__exit__(None, None, None)

    def to_header(self):
        # type: () -> Dict[str, str]
        """
        Returns a dictionary with the header labels and values.
        :return: A key value pair dictionary
        """
        tracer_from_context = self.get_current_tracer()
        temp_headers = {} # type: Dict[str, str]
        if tracer_from_context is not None:
            ctx = tracer_from_context.span_context
            try:
                temp_headers = tracer_from_context.propagator.to_headers(ctx)
            except AttributeError:
                pass
        return temp_headers

    def add_attribute(self, key, value):
        # type: (str, Union[str, int]) -> None
        """
        Add attribute (key value pair) to the current span.

        :param key: The key of the key value pair
        :type key: str
        :param value: The value of the key value pair
        :type value: str
        """
        self.span_instance.add_attribute(key, value)

    def set_http_attributes(self, request, response=None):
        # type: (HttpRequest, Optional[HttpResponse]) -> None
        """
        Add correct attributes for a http client span.

        :param request: The request made
        :type request: HttpRequest
        :param response: The response received by the server. Is None if no response received.
        :type response: HttpResponse
        """
        self.kind = SpanKind.CLIENT
        self.span_instance.add_attribute(self._span_component, "http")
        self.span_instance.add_attribute(self._http_method, request.method)
        self.span_instance.add_attribute(self._http_url, request.url)
        user_agent = request.headers.get("User-Agent")
        if user_agent:
            self.span_instance.add_attribute(self._http_user_agent, user_agent)
        if response:
            self._span_instance.add_attribute(self._http_status_code, response.status_code)
        else:
            self._span_instance.add_attribute(self._http_status_code, 504)

    def get_trace_parent(self):
        """Return traceparent string as defined in W3C trace context specification.

        Example:
        Value = 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
        base16(version) = 00
        base16(trace-id) = 4bf92f3577b34da6a3ce929d0e0e4736
        base16(parent-id) = 00f067aa0ba902b7
        base16(trace-flags) = 01  // sampled

        :return: a traceparent string
        :rtype: str
        """
        return self.to_header()['traceparent']

    @classmethod
    def link(cls, traceparent):
        # type: (str) -> None
        """
        Links the context to the current tracer.

        :param traceparent: A complete traceparent
        :type traceparent: str
        """
        cls.link_from_headers({
            'traceparent': traceparent
        })

    @classmethod
    def link_from_headers(cls, headers):
        # type: (Dict[str, str]) -> None
        """
        Given a dictionary, extracts the context and links the context to the current tracer.

        :param headers: A key value pair dictionary
        :type headers: dict
        """
        ctx = trace_context_http_header_format.TraceContextPropagator().from_headers(headers)
        current_span = cls.get_current_span()
        current_span.add_link(Link(ctx.trace_id, ctx.span_id))

    @classmethod
    def get_current_span(cls):
        # type: () -> Span
        """
        Get the current span from the execution context. Return None otherwise.
        """
        return execution_context.get_current_span()

    @classmethod
    def get_current_tracer(cls):
        # type: () -> Tracer
        """
        Get the current tracer from the execution context. Return None otherwise.
        """
        return execution_context.get_opencensus_tracer()

    @classmethod
    def set_current_span(cls, span):
        # type: (Span) -> None
        """
        Set the given span as the current span in the execution context.

        :param span: The span to set the current span as
        :type span: :class: opencensus.trace.Span
        """
        return execution_context.set_current_span(span)

    @classmethod
    def set_current_tracer(cls, tracer):
        # type: (Tracer) -> None
        """
        Set the given tracer as the current tracer in the execution context.
        :param tracer: The tracer to set the current tracer as
        :type tracer: :class: opencensus.trace.Tracer
        """
        return execution_context.set_opencensus_tracer(tracer)

    @classmethod
    def with_current_context(cls, func):
        # type: (Callable) -> Callable
        """Passes the current spans to the new context the function will be run in.

        :param func: The function that will be run in the new context
        :return: The target the pass in instead of the function
        """
        try:
            import opencensus.ext.threading  # pylint: disable=unused-import
        except ImportError:
            raise ValueError("In order to trace threads with Opencensus, please install opencensus-ext-threading")
        # Noop, once opencensus-ext-threading is installed threads get context for free.
        return func
