"""Explicit actual fixture registration for copying or isolated collection.

Root alone executes PG with the repository target guard and its exclusive lock.
Importing fixtures does not invoke them or establish a database connection.
"""

from tests.conftest import engines as engines
from tests.conftest import setup as setup
from tests.professional_authority.test_transactions import authority_work as authority_work
