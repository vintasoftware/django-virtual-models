from django.contrib.contenttypes.fields import GenericForeignKey, ReverseGenericManyToOneDescriptor
from django.db.models import Model
from django.db.models.fields.related import (
    ForwardManyToOneDescriptor,
    ForwardOneToOneDescriptor,
    ManyToManyDescriptor,
    ReverseManyToOneDescriptor,
    ReverseOneToOneDescriptor,
)
from django.db.models.query_utils import DeferredAttribute

# These are all possible related field descriptors from Django.
# Based on:
# https://github.com/charettes/django-seal/blob/51aeff67b92d313bf0452fa56a9630471f767b30/seal/descriptors.py
_RELATED_DESCRIPTOR_CLASSES = (
    DeferredAttribute,
    ForwardOneToOneDescriptor,
    ReverseOneToOneDescriptor,
    ForwardManyToOneDescriptor,
    ReverseManyToOneDescriptor,
    ManyToManyDescriptor,
    GenericForeignKey,
    ReverseGenericManyToOneDescriptor,
)


def is_preloaded(model: Model, attribute: str) -> bool:
    # empty params:
    if not model or not attribute:
        return False
    # attribute is on field cache:
    if attribute in model._state.fields_cache:
        return True
    # attribute is on prefetch cache:
    if hasattr(model, "_prefetched_objects_cache") and attribute in model._prefetched_objects_cache:
        return True
    # attribute is not on any cache but it's a related field:
    if hasattr(model.__class__, attribute) and isinstance(
        getattr(model.__class__, attribute), _RELATED_DESCRIPTOR_CLASSES
    ):
        return False
    # attribute is on model instance:
    # (note this check MUST be down here to avoid evaluating any related field)
    if hasattr(model, attribute):
        return True

    return False
