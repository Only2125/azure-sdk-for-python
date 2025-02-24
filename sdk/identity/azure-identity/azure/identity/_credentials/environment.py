# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------
import os

from azure.core.exceptions import ClientAuthenticationError
from .._constants import EnvironmentVariables
from .client_credential import CertificateCredential, ClientSecretCredential
from .user import UsernamePasswordCredential


try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import Any, Mapping, Optional, Union
    from azure.core.credentials import AccessToken

    EnvironmentCredentialTypes = Union["CertificateCredential", "ClientSecretCredential", "UsernamePasswordCredential"]


class EnvironmentCredential:
    """
    Authenticates as a service principal using a client secret or a certificate, or as a user with a username and
    password, depending on environment variable settings. Configuration is attempted in this order, using these
    environment variables:

    Service principal with secret:
      - **AZURE_CLIENT_ID**: the service principal's client ID
      - **AZURE_CLIENT_SECRET**: one of the service principal's client secrets
      - **AZURE_TENANT_ID**: ID of the service principal's tenant. Also called its 'directory' ID.

    Service principal with certificate:
      - **AZURE_CLIENT_ID**: the service principal's client ID
      - **AZURE_CLIENT_CERTIFICATE_PATH**: path to a PEM-encoded certificate file including the private key
      - **AZURE_TENANT_ID**: ID of the service principal's tenant. Also called its 'directory' ID.

    User with username and password:
      - **AZURE_CLIENT_ID**: the application's client ID
      - **AZURE_USERNAME**: a username (usually an email address)
      - **AZURE_PASSWORD**: that user's password
      - **AZURE_TENANT_ID**: (optional) ID of the service principal's tenant. Also called its 'directory' ID.
        If not provided, defaults to the 'organizations' tenant, which supports only Azure Active Directory work or
        school accounts.
    """

    def __init__(self, **kwargs):
        # type: (Mapping[str, Any]) -> None
        self._credential = None  # type: Optional[EnvironmentCredentialTypes]

        if all(os.environ.get(v) is not None for v in EnvironmentVariables.CLIENT_SECRET_VARS):
            self._credential = ClientSecretCredential(
                client_id=os.environ[EnvironmentVariables.AZURE_CLIENT_ID],
                secret=os.environ[EnvironmentVariables.AZURE_CLIENT_SECRET],
                tenant_id=os.environ[EnvironmentVariables.AZURE_TENANT_ID],
                **kwargs
            )
        elif all(os.environ.get(v) is not None for v in EnvironmentVariables.CERT_VARS):
            self._credential = CertificateCredential(
                client_id=os.environ[EnvironmentVariables.AZURE_CLIENT_ID],
                tenant_id=os.environ[EnvironmentVariables.AZURE_TENANT_ID],
                certificate_path=os.environ[EnvironmentVariables.AZURE_CLIENT_CERTIFICATE_PATH],
                **kwargs
            )
        elif all(os.environ.get(v) is not None for v in EnvironmentVariables.USERNAME_PASSWORD_VARS):
            self._credential = UsernamePasswordCredential(
                client_id=os.environ[EnvironmentVariables.AZURE_CLIENT_ID],
                username=os.environ[EnvironmentVariables.AZURE_USERNAME],
                password=os.environ[EnvironmentVariables.AZURE_PASSWORD],
                tenant=os.environ.get(EnvironmentVariables.AZURE_TENANT_ID),  # optional for username/password auth
                **kwargs
            )

    def get_token(self, *scopes, **kwargs):  # pylint:disable=unused-argument
        # type: (*str, **Any) -> AccessToken
        """
        Request an access token for `scopes`.

        :param str scopes: desired scopes for the token
        :rtype: :class:`azure.core.credentials.AccessToken`
        :raises: :class:`azure.core.exceptions.ClientAuthenticationError`
        """
        if not self._credential:
            raise ClientAuthenticationError(message="Incomplete environment configuration.")
        return self._credential.get_token(*scopes, **kwargs)
