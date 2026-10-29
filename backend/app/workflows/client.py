import logging

import inngest

from app.core.config import get_settings

# Development talks to the local Inngest dev server (no keys needed).
# Staging and production use Inngest Cloud: INNGEST_EVENT_KEY and INNGEST_SIGNING_KEY,
# plus INNGEST_ENV to pick a non-production Inngest environment (staging).
inngest_client = inngest.Inngest(
    app_id="bridge",
    is_production=get_settings().environment != "development",
    logger=logging.getLogger("uvicorn"),
)
