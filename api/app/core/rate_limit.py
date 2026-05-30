from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import RATE_LIMIT_ENABLED

limiter = Limiter(key_func=get_remote_address, enabled=RATE_LIMIT_ENABLED)

# Shared bucket for all video-generation submissions.
GENERATE_SCOPE = "generate"
JOB_DOWNLOAD_SCOPE = "job_download"
