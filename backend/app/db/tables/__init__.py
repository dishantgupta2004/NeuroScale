"""
Tables package.

IMPORTANT: every table module is imported here so that SQLAlchemy's
Base.metadata knows about them when Alembic generates migrations and
when create_all() runs. Forgetting to import a table = it won't get a
table created.
"""
from app.db.tables.agent_run import AgentRun
from app.db.tables.company import Company
from app.db.tables.content_output import ContentOutput
from app.db.tables.document import Document
from app.db.tables.email_log import EmailLog
from app.db.tables.user import User

__all__ = [
    "AgentRun",
    "Company",
    "ContentOutput",
    "Document",
    "EmailLog",
    "User",
]