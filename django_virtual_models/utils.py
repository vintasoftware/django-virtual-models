from __future__ import annotations

from itertools import chain
from typing import Dict, Iterable, List, Set, Type, TypeVar

from django.db.models import Model, QuerySet

from rest_framework import serializers
from rest_framework.fields import Field

T = TypeVar("T")


def unique_keep_order(ls: Iterable[T]) -> List[T]:
    return list({x: None for x in ls}.keys())


def one_level_lookup(lookup: str) -> str:
    return lookup.split("__")[0]


def one_level_lookup_list(lookup_list: List[str]) -> List[str]:
    return unique_keep_order(one_level_lookup(lookup) for lookup in lookup_list)


def get_field_name(field: Field) -> str:
    if isinstance(field, serializers.SerializerMethodField):
        return field.field_name
    if isinstance(field, serializers.HyperlinkedRelatedField):
        return field.field_name
    return field.source


def get_friendly_field_name(field: Field) -> str:
    if isinstance(field, serializers.SerializerMethodField):
        return field.method_name
    if isinstance(field, serializers.HyperlinkedRelatedField):
        return field.field_name
    return field.source


def str_remove_prefix(s: str, prefix: str) -> str:
    if s.startswith(prefix):
        return s[len(prefix) :]
    return s


def get_model_concrete_fields(model_cls: Type[Model], exclude_relations: bool = False) -> Set[str]:
    return {
        f.attname
        for f in model_cls._meta.concrete_fields
        if not (exclude_relations and f.is_relation)
    }


def get_select_related_choices(qs: QuerySet, model_cls: Type[Model]) -> Set[str]:
    # Adapted from Django code inside django/db/models/sql/compiler.py::get_related_selections
    opts = model_cls._meta
    direct_choices = (f.name for f in opts.fields if f.is_relation)
    reverse_choices = (f.field.related_query_name() for f in opts.related_objects if f.field.unique)
    return set(chain(direct_choices, reverse_choices, qs.query._filtered_relations))


def _get_own_properties(cls: Type) -> List[str]:
    return [key for key, value in cls.__dict__.items() if isinstance(value, property)]


def get_properties(cls: Type) -> Set[str]:
    props = []
    for kls in cls.mro():
        props += _get_own_properties(kls)
    return set(props)


def get_methods(cls: Type) -> Set[str]:
    return {attr for attr in dir(cls) if callable(getattr(cls, attr)) and not attr.startswith("__")}


def get_readable_fields(
    serializer_instance: serializers.BaseSerializer,
) -> Dict[str, serializers.Field]:
    return {key: field for key, field in serializer_instance.fields.items() if not field.write_only}
