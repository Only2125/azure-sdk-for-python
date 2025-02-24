# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

import sys


X_MS_VERSION = '2019-02-02'

# Socket timeout in seconds
DEFAULT_SOCKET_TIMEOUT = 20

# for python 3.5+, there was a change to the definition of the socket timeout (as far as socket.sendall is concerned)
# The socket timeout is now the maximum total duration to send all data.
if sys.version_info >= (3, 5):
    # the timeout to connect is 20 seconds, and the read timeout is 2000 seconds
    # the 2000 seconds was calculated with: 100MB (max block size)/ 50KB/s (an arbitrarily chosen minimum upload speed)
    DEFAULT_SOCKET_TIMEOUT = (20, 2000) # type: ignore

STORAGE_OAUTH_SCOPE = "https://storage.azure.com/.default"

SERVICE_HOST_BASE = 'core.windows.net'
