"""Top-level package for django_virtual_models."""
import logging

__version__ = "0.0.1"

# Good practice: https://docs.python-guide.org/writing/logging/#logging-in-a-library
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Top-level imports:
from .fields import *