"""Top-level package for django_virtual_models."""
import logging

__version__ = "0.1.0"

# Good practice: https://docs.python-guide.org/writing/logging/#logging-in-a-library
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Top-level imports:
from .fields import *
from .generic_views import *
from .prefetch import hints
from .serializers import *
