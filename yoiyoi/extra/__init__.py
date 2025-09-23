"""Extra module"""

# set max timeout and tries
RETRY_MIN_TIMEOUT = 0
RETRY_MAX_TIMEOUT = 2
RETRY_MAX_TRIES = 5
RETRY_PROXY_MAX_TRIES = 2
RETRY_PROXY_MAX_TIMEOUT = 0

# set proxy countries
PROXY_CID = None

# set proxy response timeout
PROXY_TIMEOUT = 1

# set proxy limit of simultaneous requests
PROXY_LIMIT = 25

# define proxy dictionary
PROXY = {"active": None}
PROXY_SET = set()
