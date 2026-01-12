"""Extra module"""

# set max timeout and tries
DEFAULT_REQUEST_TIMEOUT = 5
RETRY_MIN_TIMEOUT = 1
RETRY_MAX_TIMEOUT = 3
RETRY_MAX_TRIES = 5
RETRY_PROXY_MAX_TRIES = RETRY_MAX_TRIES - 1
RETRY_PROXY_MAX_TIMEOUT = 0

# set proxy countries
PROXY_CID = None

# set proxy response timeout
PROXY_TIMEOUT = 1

# set proxy limit of simultaneous requests
PROXY_LIMIT = 25
