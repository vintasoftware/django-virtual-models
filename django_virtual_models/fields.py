# pylint: disable=unidiomatic-typecheck, signature-differs, protected-access, useless-suppression
from __future__ import annotations

from collections import OrderedDict
from functools import cached_property
from typing import Any, Callable, Dict, List, Optional, Set, Type

from django.db.models import Model, Prefetch, QuerySet
from django.db.models.expressions import Expression as DjangoExpression
from django.db.models.fields.related_descriptors import ReverseManyToOneDescriptor
from django.db.models.manager import Manager

from . import utils
from .exceptions import InvalidFieldException, InvalidLookupException, InvalidVirtualModelParams


def _defer_fields(qs: QuerySet, lookup_list: List[str], deferred_fields: List[str]) -> QuerySet:
    requested_fields = set(utils.one_level_lookup_list(lookup_list))
    actual_deferred_fields = set(deferred_fields) - requested_fields
    if actual_deferred_fields:
        qs = qs.defer(*actual_deferred_fields)
    return qs


class BaseVirtualField:
    def hydrate_queryset(
        self,
        qs: QuerySet,
        field: str,
        lookup_list: List[str],
        parent_model_cls: Optional[Type[Model]] = None,
        parent_virtual_field: Optional[BaseVirtualField] = None,
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        raise NotImplementedError  # pragma: no cover


class NoOp(BaseVirtualField):
    def hydrate_queryset(
        self,
        qs: QuerySet,
        field: str,
        lookup_list: List[str],
        parent_model_cls: Optional[Type[Model]] = None,
        parent_virtual_field: Optional[BaseVirtualField] = None,
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        return qs


class Expression(BaseVirtualField):
    def __init__(self, expr: DjangoExpression):
        self.expr = expr

    def hydrate_queryset(
        self,
        qs: QuerySet,
        field: str,
        lookup_list: List[str],
        parent_model_cls: Optional[Type[Model]] = None,
        parent_virtual_field: Optional[BaseVirtualField] = None,
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        return qs.annotate(**{field: self.expr})


class Annotation(BaseVirtualField):
    def __init__(self, func: Callable[[QuerySet, Any], QuerySet]):
        self.func = func

    def hydrate_queryset(
        self,
        qs: QuerySet,
        field: str,
        lookup_list: List[str],
        parent_model_cls: Optional[Type[Model]] = None,
        parent_virtual_field: Optional[BaseVirtualField] = None,
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        new_qs = self.func(qs, user=user, **kwargs)  # type: ignore
        return new_qs


class NestedJoin(BaseVirtualField):
    def __init__(self, model_cls: Type[Model]):
        self.model_cls: Type[Model] = model_cls

    def hydrate_queryset(
        self,
        qs: QuerySet,
        field: str,
        lookup_list: List[str],
        parent_model_cls: Optional[Type[Model]] = None,
        parent_virtual_field: Optional[BaseVirtualField] = None,
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        model_concrete_fields = utils.get_model_concrete_fields(self.model_cls)
        select_related_choices = utils.get_select_related_choices(qs=qs, model_cls=self.model_cls)

        new_qs = qs.select_related(field)
        for k in lookup_list:
            if k in model_concrete_fields:
                continue

            k_one_level = utils.one_level_lookup(k)
            if k_one_level not in select_related_choices:
                # NOTE: we cannot handle `InvalidLookupException` for 2-level nested lookups,
                #       here we're handling only the 1st level.
                raise InvalidLookupException(
                    f"`{k_one_level}` cannot be used as a lookup for `{field} = {self.__class__.__name__}(...)` "
                    f"used by `{parent_virtual_field.__class__.__name__}`. "
                    f"Choices are {', '.join(select_related_choices) or '(none)'}. "
                )
            nested_field = f"{field}__{k}"
            new_qs = new_qs.select_related(nested_field)

        return new_qs


class VirtualModelMetaclass(type):
    """
    This metaclass sets a dictionary named `declared_fields` on the class.

    Any instances of `BaseVirtualField` included as attributes on either the class
    or on any of its superclasses will be include in the
    `declared_fields` dictionary.

    Based on Django REST Framework `SerializerMetaclass`.
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
            if hasattr(base, "declared_fields")
            for name, f in base.declared_fields.items()
            if name not in known
        ]

        return OrderedDict(base_fields + fields)

    def __new__(cls, name, bases, attrs):
        attrs["declared_fields"] = cls._get_declared_fields(bases, attrs)
        return super().__new__(cls, name, bases, attrs)


class VirtualModel(BaseVirtualField, metaclass=VirtualModelMetaclass):
    declared_fields: Dict[str, BaseVirtualField]

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
        if manager is None and (not hasattr(self.Meta, "model") or self.Meta.model is None):
            raise InvalidVirtualModelParams("Always provide a `manager` or `Meta.model`")
        if bool(lookup) ^ bool(to_attr):
            raise InvalidVirtualModelParams(
                "Always provide `lookup` and `to_attr` together or leave both `None`"
            )

        self.user = user
        self.manager = manager or self.Meta.model._default_manager
        self.model_cls = self.Meta.model or manager.model
        self.lookup = lookup
        self.to_attr = to_attr
        self.extra_kwargs = kwargs

    @cached_property
    def deferred_fields(self) -> Set[str]:
        if hasattr(self.Meta, "deferred_fields") and self.Meta.deferred_fields:
            return set(self.Meta.deferred_fields)
        return set()

    @cached_property
    def model_concrete_fields(self) -> Set[str]:
        return utils.get_model_concrete_fields(self.model_cls)

    def get_prefetch_queryset(self, user: Optional[Model] = None, **kwargs: Any) -> QuerySet:
        return self.manager.all()

    def _hydrate_queryset_with_nested_declared_fields(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        field: str = None,
        parent_virtual_field: Optional[BaseVirtualField] = None,
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
                f = self.declared_fields[k]
            except KeyError as e:
                if parent_virtual_field:
                    raise InvalidLookupException(
                        f"`{k}` not declared in `{field} = {self.__class__.__name__}(...)` "
                        f"used by `{parent_virtual_field.__class__.__name__}`"
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
                field=k,
                lookup_list=f_lookup_list,
                parent_model_cls=self.model_cls,
                parent_virtual_field=self,
                user=user,
                **kwargs,
            )

        return new_qs

    def hydrate_queryset(
        self,
        qs: QuerySet,
        field: str,
        lookup_list: List[str],
        parent_model_cls: Optional[Type[Model]] = None,
        parent_virtual_field: Optional[BaseVirtualField] = None,
        user: Optional[Model] = None,
        **kwargs: Any,
    ) -> QuerySet:
        # if lookup_list is empty, consider as full prefetch (all fields, concrete or virtual)
        if not lookup_list:
            new_lookup_list = list(self.model_concrete_fields) + list(self.declared_fields.keys())
        else:
            new_lookup_list = list(lookup_list)

        prefetch_queryset = self.get_prefetch_queryset(user=user, **kwargs)
        prefetch_queryset = self._hydrate_queryset_with_nested_declared_fields(
            qs=prefetch_queryset,
            lookup_list=new_lookup_list,
            field=field,
            parent_virtual_field=parent_virtual_field,
            user=user,
            **kwargs,
        )

        # always include the "back reference" field name in the Prefetch's lookup list
        # to avoid N+1s in internal Django prefetch code
        field_to_prefetch = self.lookup if self.lookup else field
        field_descriptor = getattr(parent_model_cls, field_to_prefetch)
        if type(field_descriptor) == ReverseManyToOneDescriptor:  # don't use isinstance
            back_reference = field_descriptor.rel.field.name
            new_lookup_list.append(back_reference)

        # defer fields on prefetch_queryset
        prefetch_queryset = _defer_fields(
            qs=prefetch_queryset,
            lookup_list=new_lookup_list,
            deferred_fields=self.deferred_fields,
        )

        # build prefetch with lookups
        if self.lookup:
            prefetch = Prefetch(self.lookup, queryset=prefetch_queryset, to_attr=self.to_attr)
        else:
            prefetch = Prefetch(field, queryset=prefetch_queryset)

        new_qs = qs.prefetch_related(prefetch)
        # prefeches don't need lookup
        # (but their internal qs need, see prefetch_queryset above)
        return new_qs

    def get_optimized_queryset(
        self,
        qs: QuerySet,
        lookup_list: List[str],
        **kwargs: Any,
    ) -> QuerySet:
        # if lookup_list is empty, consider as full prefetch (all fields, concrete or virtual)
        if not lookup_list:
            new_lookup_list = list(self.model_concrete_fields) + list(self.declared_fields.keys())
        else:
            new_lookup_list = list(lookup_list)

        new_qs = self._hydrate_queryset_with_nested_declared_fields(
            qs=qs,
            lookup_list=new_lookup_list,
            field=None,
            parent_virtual_field=None,
            user=self.user,
            **kwargs,
        )
        new_qs = _defer_fields(
            qs=new_qs,
            lookup_list=new_lookup_list,
            deferred_fields=self.deferred_fields,
        )
        return new_qs
