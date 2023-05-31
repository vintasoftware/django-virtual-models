# pylint: disable=unidiomatic-typecheck, signature-differs, protected-access, useless-suppression
from __future__ import annotations

import copy
from collections import OrderedDict
from functools import cached_property
from typing import Any, Callable, Dict, List, Optional, Set, Type

from django.db.models import Model, Prefetch, QuerySet
from django.db.models.expressions import Expression as DjangoExpression
from django.db.models.fields.related_descriptors import ReverseManyToOneDescriptor
from django.db.models.manager import Manager

from rest_framework.utils.serializer_helpers import BindingDict

from . import utils
from .exceptions import InvalidFieldException, InvalidLookupException, InvalidVirtualModelParams


def _defer_fields(qs: QuerySet, lookup_list: List[str], deferred_fields: List[str]) -> QuerySet:
    requested_fields = set(utils.one_level_lookup_list(lookup_list))
    actual_deferred_fields = set(deferred_fields) - requested_fields
    if actual_deferred_fields:
        qs = qs.defer(*actual_deferred_fields)
    return qs


class BaseVirtualField:
    def __init__(self):
        # These are set up by `.bind()` when the field is declared inside a `VirtualModel`:
        self.field_name: Optional[str] = None
        self.parent: Optional[VirtualModel] = None

    def bind(self, field_name, parent):
        """
        Initializes the field name and parent for the field instance.
        Called when a field is declared inside a `VirtualModel`.
        """
        self.field_name = field_name
        self.parent = parent

    def hydrate_queryset(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        raise NotImplementedError  # pragma: no cover


class NoOp(BaseVirtualField):
    def hydrate_queryset(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        return qs


class Expression(BaseVirtualField):
    def __init__(self, expr: DjangoExpression):
        super().__init__()

        self.expr = expr

    def hydrate_queryset(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        return qs.annotate(**{self.field_name: self.expr})


class Annotation(BaseVirtualField):
    def __init__(self, func: Callable[[QuerySet, Any], QuerySet]):
        super().__init__()

        self.func = func

    def hydrate_queryset(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        new_qs = self.func(qs, user=user, **kwargs)  # type: ignore
        return new_qs


class NestedJoin(BaseVirtualField):
    def __init__(self, model_cls: Type[Model]):
        super().__init__()

        self.model_cls: Type[Model] = model_cls

    def hydrate_queryset(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        model_concrete_fields = utils.get_model_concrete_fields(self.model_cls)
        select_related_choices = utils.get_select_related_choices(qs=qs, model_cls=self.model_cls)

        new_qs = qs.select_related(self.field_name)
        for k in lookup_list:
            if k in model_concrete_fields:
                continue

            k_one_level = utils.one_level_lookup(k)
            if k_one_level not in select_related_choices:
                # NOTE: we cannot handle `InvalidLookupException` for 2-level nested lookups,
                #       here we're handling only the 1st level.
                raise InvalidLookupException(
                    f"`{k_one_level}` cannot be used as a lookup for `{self.field_name} = {self.__class__.__name__}(...)` "
                    f"used by `{self.parent.__class__.__name__}`. "
                    f"Choices are {', '.join(select_related_choices) or '(none)'}. "
                )
            nested_field = f"{self.field_name}__{k}"
            new_qs = new_qs.select_related(nested_field)

        return new_qs


class VirtualModelMetaclass(type):
    # Based on DRF's SerializerMetaclass code.
    """
    This metaclass sets a dictionary named `declared_fields` on the class.

    Any instances of `BaseVirtualField` included as attributes on either the class
    or on any of its superclasses will be include in the
    `declared_fields` dictionary.
    """

    @classmethod
    def _get_declared_fields(cls, bases, attrs):
        fields = [
            (field_name, attrs.pop(field_name))
            for field_name, obj in list(attrs.items())
            if isinstance(obj, BaseVirtualField)
        ]

        for field_name, __ in fields:
            if "__" in field_name:
                raise InvalidFieldException(
                    f"Field `{field_name}` in `{cls.__name__}` shouldn't cointain `__`"
                )

        # Ensures a base class field doesn't override cls attrs, and maintains
        # field precedence when inheriting multiple parents. e.g. if there is a
        # class C(A, B), and A and B both define 'field', use 'field' from A.
        known = set(attrs)

        def visit(name):
            known.add(name)
            return name

        base_fields = [
            (visit(name), f)
            for base in bases
            if hasattr(base, "_declared_fields")
            for name, f in base._declared_fields.items()
            if name not in known
        ]

        return OrderedDict(base_fields + fields)

    def __new__(cls, name, bases, attrs):
        attrs["_declared_fields"] = cls._get_declared_fields(bases, attrs)
        return super().__new__(cls, name, bases, attrs)


class VirtualModel(BaseVirtualField, metaclass=VirtualModelMetaclass):
    _declared_fields: Dict[str, BaseVirtualField]

    class Meta:
        model: Optional[Type[Model]] = None
        deferred_fields: Optional[List[str]] = None

    def __init__(
        self,
        user: Optional[Model] = None,
        manager: Optional[Manager] = None,
        lookup: Optional[str] = None,
        to_attr: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__()

        if manager is None and (not hasattr(self.Meta, "model") or self.Meta.model is None):
            raise InvalidVirtualModelParams("Always provide a `manager` or `Meta.model`")
        if to_attr is not None and lookup is None:
            raise InvalidVirtualModelParams("Always provide a `lookup` when providing a `to_attr`")

        self.user = user
        if manager is None:
            self.manager = self.Meta.model._default_manager
            self.model_cls = self.Meta.model
        else:
            self.manager = manager
            self.model_cls = manager.model
        self.lookup = lookup
        self.to_attr = to_attr  # can be `None`, but will receive `field_name` in `bind()`
        self.extra_kwargs = kwargs

    def get_fields(self) -> Dict[str, BaseVirtualField]:
        """
        Returns a dictionary of {field_name: field_instance}.
        """
        # Based on DRF's Serializer code.
        return copy.deepcopy(self._declared_fields)

    @cached_property
    def fields(self) -> Dict[str, BaseVirtualField]:
        """
        A dictionary of {field_name: field_instance}.
        """
        # Based on DRF's Serializer code.
        fields = BindingDict(self)
        for key, value in self.get_fields().items():
            fields[key] = value
        return fields

    @cached_property
    def deferred_fields(self) -> Set[str]:
        if hasattr(self.Meta, "deferred_fields") and self.Meta.deferred_fields:
            return set(self.Meta.deferred_fields)
        return set()

    def bind(self, field_name, parent):
        super().bind(field_name, parent)

        if self.lookup is not None and self.to_attr is None:
            self.to_attr = self.field_name

    @cached_property
    def model_concrete_fields(self) -> Set[str]:
        return utils.get_model_concrete_fields(self.model_cls)

    def get_prefetch_queryset(self, user: Optional[Model] = None, **kwargs: Any) -> QuerySet:
        return self.manager.all()

    def _hydrate_queryset_with_nested_declared_fields(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        kwargs = {**kwargs, **self.extra_kwargs}

        # handle internal declared fields (if any)
        new_qs = qs
        for k in utils.one_level_lookup_list(lookup_list):
            if k in self.model_concrete_fields:
                continue

            # field is not concrete, so handle it
            try:
                f = self.fields[k]
            except KeyError as e:
                if self.parent is not None:
                    raise InvalidLookupException(
                        f"`{k}` not declared in `{self.field_name} = {self.__class__.__name__}(...)` "
                        f"used by `{self.parent.__class__.__name__}`"
                    ) from e
                else:
                    raise InvalidLookupException(
                        f"`{k}` not declared in `{self.__class__.__name__}`"
                    ) from e
            f_lookup_list = [
                utils.str_remove_prefix(lookup, f"{k}__")
                for lookup in lookup_list
                if lookup.startswith(f"{k}__")
            ]
            new_qs = f.hydrate_queryset(
                qs=new_qs,
                lookup_list=f_lookup_list,
                user=user,
                **kwargs,
            )

        return new_qs

    def _build_prefetch(self, prefetch_queryset: QuerySet):
        if self.lookup:
            return Prefetch(self.lookup, queryset=prefetch_queryset, to_attr=self.to_attr)
        else:
            return Prefetch(self.field_name, queryset=prefetch_queryset)

    def hydrate_queryset(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        # if lookup_list is empty, consider as full prefetch (all fields, concrete or virtual)
        if not lookup_list:
            new_lookup_list = list(self.model_concrete_fields) + list(self.fields.keys())
        else:
            new_lookup_list = list(lookup_list)

        prefetch_queryset = self.get_prefetch_queryset(user=user, **kwargs)
        prefetch_queryset = self._hydrate_queryset_with_nested_declared_fields(
            qs=prefetch_queryset,
            lookup_list=new_lookup_list,
            user=user,
            **kwargs,
        )

        # always include the "back reference" field name in the Prefetch's lookup list
        # to avoid N+1s in internal Django prefetch code
        field_to_prefetch = self.lookup if self.lookup else self.field_name
        field_descriptor = getattr(self.parent.model_cls, field_to_prefetch)
        if type(field_descriptor) == ReverseManyToOneDescriptor:  # don't use isinstance
            back_reference = field_descriptor.rel.field.name
            new_lookup_list.append(back_reference)

        # defer fields on prefetch_queryset
        prefetch_queryset = _defer_fields(
            qs=prefetch_queryset,
            lookup_list=new_lookup_list,
            deferred_fields=self.deferred_fields,
        )

        # build prefetch object, call prefetch_related
        prefetch = self._build_prefetch(prefetch_queryset)
        new_qs = qs.prefetch_related(prefetch)
        return new_qs

    def get_optimized_queryset(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        **kwargs: Any,
    ) -> QuerySet:
        # if lookup_list is empty, consider as full prefetch (all fields, concrete or virtual)
        if not lookup_list:
            new_lookup_list = list(self.model_concrete_fields) + list(self.fields.keys())
        else:
            new_lookup_list = list(lookup_list)

        new_qs = self._hydrate_queryset_with_nested_declared_fields(
            qs=qs,
            lookup_list=new_lookup_list,
            user=self.user,
            **kwargs,
        )
        new_qs = _defer_fields(
            qs=new_qs,
            lookup_list=new_lookup_list,
            deferred_fields=self.deferred_fields,
        )
        return new_qs
