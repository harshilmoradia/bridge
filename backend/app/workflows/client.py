import logging

import inngest

from app.core.config import get_settings

# Dev mode talks to the local Inngest dev server (no keys needed).
# Production reads INNGEST_EVENT_KEY and INNGEST_SIGNING_KEY from the environment.
inngest_client = inngest.Inngest(
    app_id="bridge",
    is_production=get_settings().environment == "production",
    logger=logging.getLogger("uvicorn"),
)
