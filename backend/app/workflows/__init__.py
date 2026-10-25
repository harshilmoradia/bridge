from app.workflows.client import inngest_client
from app.workflows.smoke import smoke_run

# Every Inngest function must be listed here to be served and synced.
functions = [smoke_run]

__all__ = ["functions", "inngest_client"]
