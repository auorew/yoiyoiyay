import contextvars
import logging

from yoiyoi.extra.loggers import get_handlers
from yoiyoi.extra.settings import log_settings

# Define context variables
update_id = contextvars.ContextVar("update_id", default=0)

# Create the parent logger for app
log = logging.getLogger(__name__)

log_level = logging.DEBUG
log_format = "%(asctime)s [%(levelname)s] > [%(update_id)s] %(name)s: %(message)s"

# Save the original log record factory
original_factory = logging.getLogRecordFactory()


def log_record_factory(*args, **kwargs):
    record = original_factory(*args, **kwargs)
    record.update_id = update_id.get(0)
    return record


# Set the new log record factory
logging.setLogRecordFactory(log_record_factory)

for handler in get_handlers(log_settings.bot):
    log.addHandler(handler)

log.propagate = False
