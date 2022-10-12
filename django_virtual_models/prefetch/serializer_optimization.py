import logging
from typing import Callable, List, Optional, Set, Type

from django.db.models import Model

from rest_framework import serializers
from rest_framework.fields import Field

import typing_extensions

from django_virtual_models.prefetch import hints

from .. import utils
from ..fields import BaseVirtualField, NestedJoin, NoOp
from .exceptions import ImproperlyAnnotatedCodeException, MissingVirtualModelFieldException
from .hints import OnOffDecorator

logger = logging.getLogger(__name__)


def _get_param_type_hints_with_annotated(x):
    type_hints_dict = typing_extensions.get_type_hints(x, include_extras=True)
    type_hints_dict.pop("return", None)  # ignore return typing
    return type_hints_dict


def _validate_type_hint(type_hint, invalid_type_hint_message):
    if typing_extensions.get_origin(type_hint) is not typing_extensions.Annotated:
        raise ImproperlyAnnotatedCodeException(invalid_type_hint_message)

    metadata = typing_extensions.get_args(type_hint)[1:]
    metadata_only = [datum for datum in metadata if isinstance(datum, hints.Virtual)]
    if len(metadata_only) == 0:
        raise ImproperlyAnnotatedCodeException(invalid_type_hint_message)
    if len(metadata_only) > 1:
        raise ImproperlyAnnotatedCodeException(invalid_type_hint_message)


def _extract_type_hint_from_function(field, function):
    type_hints_dict = _get_param_type_hints_with_annotated(function)
    friendly_name = utils.get_friendly_field_name(field)

    # Check if function has a single annotation
    if len(type_hints_dict) == 0:
        raise ImproperlyAnnotatedCodeException(
            f"`{friendly_name}` inside `{field.parent.__class__.__name__}` "
            "must have a `hints` decorator or "
            "a single `Annotated` type hint with a single `hints.Virtual` inside it."
        )
    if len(type_hints_dict) > 1:
        raise ImproperlyAnnotatedCodeException(
            f"`{friendly_name}` inside `{field.parent.__class__.__name__}` "
            "has more than 1 type annotated parameter. "
            "It should have a single one. Please change it."
        )
    type_hint = list(type_hints_dict.values())[0]

    # Check if Annotated is correct
    invalid_type_hint_message = (
        f"`{friendly_name}` inside `{field.parent.__class__.__name__}` "
        "must have a single `Annotated` type hint with a single `hints.Virtual` inside it."
    )
    _validate_type_hint(type_hint, invalid_type_hint_message=invalid_type_hint_message)
    return type_hint


def _extract_type_hint_from_types_of_other_function(
    field: Field, decorator_instance: hints.from_types_of
):
    friendly_name = utils.get_friendly_field_name(field)
    typed_func = decorator_instance.typed_func
    type_hints_dict = _get_param_type_hints_with_annotated(decorator_instance.typed_func)
    if len(type_hints_dict) == 0:
        raise ImproperlyAnnotatedCodeException(
            f"Couldn't find the annotated param `{decorator_instance.obj_param_name}` "
            f"on function `{typed_func.__module__}.{typed_func.__qualname__}` "
            f"referenced by decorator `{decorator_instance.__class__.__name__}` "
            f"on `{friendly_name}` inside `{field.parent.__class__.__name__}`"
        )
    try:
        type_hint = type_hints_dict[decorator_instance.obj_param_name]
    except KeyError as e:
        raise ImproperlyAnnotatedCodeException(
            f"Couldn't find the annotated param `{decorator_instance.obj_param_name}` "
            f"on function `{typed_func.__module__}.{typed_func.__qualname__}` "
            f"Please fix decorator `{decorator_instance.__class__.__name__}` "
            f"on `{friendly_name}` inside `{field.parent.__class__.__name__}`"
        ) from e

    # Check if Annotated is correct
    invalid_type_hint_message = (
        f"Function `{typed_func.__module__}.{typed_func.__qualname__}`. "
        f"referenced by decorator `{decorator_instance.__class__.__name__}` "
        f"on `{friendly_name}` inside `{field.parent.__class__.__name__}` "
        f"must have a `Annotated` type hint on param `{decorator_instance.obj_param_name}` "
        "with a single `hints.Virtual` inside it."
    )
    _validate_type_hint(type_hint, invalid_type_hint_message=invalid_type_hint_message)
    return type_hint


def _extract_lookups_from_type_hint_obj(type_hint) -> List[str]:
    metadata = typing_extensions.get_args(type_hint)[1:]
    only = next(datum for datum in metadata if isinstance(datum, hints.Virtual))  # pragma: no cover
    return only.fields


def _extract_lookups_from_nested_serializer(
    field, virtual_model, parent_virtual_model, serializer_instance, block_queries
) -> List[str]:
    field_name = utils.get_field_name(field)
    parent_serializer_name = field.parent.__class__.__name__
    if isinstance(virtual_model, NestedJoin):
        raise MissingVirtualModelFieldException(
            f"Cannot use a `NestedJoin` for `{serializer_instance.parent.field_name}` "
            f"inside `{parent_virtual_model.__class__.__name__}`. "
            f"`{field_name}` must be a field of `{serializer_instance.parent.field_name}`, "
            f"because it's a nested serializer on `{parent_serializer_name}`. "
            f"Change from `NestedJoin` to a `VirtualModel` and add `{field_name}` as a field."
        )
    if field_name not in virtual_model.declared_fields:
        raise MissingVirtualModelFieldException(
            f"`{field_name}` must be defined in `{virtual_model.__class__.__name__}` "
            f"because it's a nested serializer on `{parent_serializer_name}`"
        )

    # map nested serializer to virtual_model
    virtual_model_of_field = virtual_model.declared_fields[field_name]

    # find nested lookup_list
    lookup_list = LookupFinder(
        serializer_instance=serializer_instance,
        virtual_model=virtual_model_of_field,
        block_queries=block_queries,
    ).recursively_find_lookup_list(parent_virtual_model=virtual_model)
    nested_lookup_list = [field_name] + [f"{field_name}__{lookup}" for lookup in lookup_list]
    return nested_lookup_list


def _extract_lookups_from_function_type_hint(
    field, function, virtual_model, parent_virtual_model, block_queries
) -> List[str]:
    decorator_instance = getattr(function, "_decorator_instance", None)
    if decorator_instance is None:
        type_hint = _extract_type_hint_from_function(field, function)
        return _extract_lookups_from_type_hint_obj(type_hint)
    elif isinstance(decorator_instance, hints.from_types_of):
        type_hint = _extract_type_hint_from_types_of_other_function(field, decorator_instance)
        return _extract_lookups_from_type_hint_obj(type_hint)
    elif isinstance(decorator_instance, hints.from_serializer):
        serializer_instance = decorator_instance.serializer_cls(
            **(decorator_instance.serializer_kwargs or {})
        )
        return _extract_lookups_from_nested_serializer(
            field=field,
            virtual_model=virtual_model,
            parent_virtual_model=parent_virtual_model,
            serializer_instance=serializer_instance,
            block_queries=block_queries,
        )
    elif isinstance(decorator_instance, hints.defined_on_virtual_model):
        # `field.field_name` must be defined in virtual model
        return [field.field_name]
    elif isinstance(decorator_instance, hints.no_deferred_fields):
        # `field.field_name` uses only fields that are always
        # fetched by the virtual model (which are all concrete fields minus the deferred ones)
        # so we don't need to return anything here to be included as a lookup
        return []
    else:
        raise Exception(
            "Unknown decorator, please restart the Python process. "
            "If error persists, create a support ticket."
        )  # pragma: no cover


class LookupFinder:
    serializer_instance: serializers.ModelSerializer
    virtual_model: BaseVirtualField

    class CantHandleException(Exception):
        pass

    def __init__(
        self,
        serializer_instance: serializers.BaseSerializer,
        virtual_model: BaseVirtualField,
        block_queries: bool = True,
    ):
        if getattr(serializer_instance, "many", False):
            self.serializer_instance = serializer_instance.child
        else:
            self.serializer_instance = serializer_instance
        self.virtual_model = virtual_model
        self.block_queries = block_queries

    def _maybe_handle_concrete_field(
        self, field: Field, model_concrete_fields: Set[str], **kwargs
    ) -> List[str]:
        if field.source not in model_concrete_fields:
            raise self.CantHandleException
        return [field.source]

    def _maybe_handle_property_field(
        self,
        field: Field,
        virtual_model: BaseVirtualField,
        parent_virtual_model: Optional[BaseVirtualField],
        model_cls: Type[Model],
        model_property_fields: Set[str],
        **kwargs,
    ) -> List[str]:
        if field.source not in model_property_fields:
            raise self.CantHandleException
        function = getattr(model_cls, field.source).fget
        return _extract_lookups_from_function_type_hint(
            field=field,
            function=function,
            virtual_model=virtual_model,
            parent_virtual_model=parent_virtual_model,
            block_queries=self.block_queries,
        )

    def _maybe_handle_model_method_field(
        self,
        field: Field,
        virtual_model: BaseVirtualField,
        parent_virtual_model: Optional[BaseVirtualField],
        model_cls: Type[Model],
        model_methods: Set[str],
        **kwargs,
    ) -> List[str]:
        if field.source not in model_methods:
            raise self.CantHandleException
        function = getattr(model_cls, field.source)
        return _extract_lookups_from_function_type_hint(
            field=field,
            function=function,
            virtual_model=virtual_model,
            parent_virtual_model=parent_virtual_model,
            block_queries=self.block_queries,
        )

    def _maybe_handle_method_field(
        self,
        field: Field,
        virtual_model: BaseVirtualField,
        parent_virtual_model: Optional[BaseVirtualField],
        **kwargs,
    ) -> List[str]:
        if not isinstance(field, serializers.SerializerMethodField):
            raise self.CantHandleException
        method = getattr(field.parent, field.method_name)
        return _extract_lookups_from_function_type_hint(
            field=field,
            function=method,
            virtual_model=virtual_model,
            parent_virtual_model=parent_virtual_model,
            block_queries=self.block_queries,
        )

    def _maybe_handle_relational_field(self, field: Field, **kwargs) -> List[str]:
        lookup = None
        if isinstance(field, serializers.PrimaryKeyRelatedField):
            lookup = field.source
        elif isinstance(field, serializers.ManyRelatedField) and isinstance(
            field.child_relation, serializers.PrimaryKeyRelatedField
        ):
            lookup = field.child_relation.source
        if lookup is None:
            raise self.CantHandleException
        return [lookup]

    def _maybe_handle_field_with_nested_source(self, field: Field, **kwargs) -> List[str]:
        # TODO: Right now, those fields must always be defined in the Virtual Model,
        #       or must be concrete nested fields. One example is "office_hour.public_id"
        field_name = utils.get_field_name(field)
        if "." not in field_name:
            raise self.CantHandleException

        return [field_name.replace(".", "__")]

    def _maybe_handle_url_field(self, field: Field, **kwargs) -> List[str]:
        # TODO: Implement proper handling of URL field.
        #       See code of `HyperlinkedRelatedField` and `HyperlinkedIdentityField` in DRF.
        if isinstance(field, serializers.HyperlinkedRelatedField):
            friendly_name = utils.get_friendly_field_name(field)
            raise ImproperlyAnnotatedCodeException(
                f"`{friendly_name}` inside `{field.parent.__class__.__name__}` "
                f"is a `{field.__class__.__name__}` that django-virtual-models cannot handle yet. "
                "Please replace it with a `SerializerMethodField`."
            )

        raise self.CantHandleException

    def _maybe_handle_nested_serializer_field(
        self,
        field: Field,
        virtual_model: BaseVirtualField,
        parent_virtual_model: Optional[BaseVirtualField],
        **kargs,
    ) -> List[str]:
        if not isinstance(field, serializers.BaseSerializer):
            raise self.CantHandleException

        nested_lookup_list = _extract_lookups_from_nested_serializer(
            field=field,
            virtual_model=virtual_model,
            parent_virtual_model=parent_virtual_model,
            serializer_instance=field,
            block_queries=self.block_queries,
        )
        return nested_lookup_list

    def _validate_lookup_list(
        self,
        field: Field,
        virtual_model: BaseVirtualField,
        model_concrete_fields: Set[str],
        model_property_fields: Set[str],
        lookup_list: List[str],
    ):
        for k in utils.one_level_lookup_list(lookup_list):
            if k in model_concrete_fields:
                continue

            friendly_name = utils.get_friendly_field_name(field)
            serializer_name = field.parent.__class__.__name__
            if k not in virtual_model.declared_fields:
                if k in model_property_fields:
                    raise MissingVirtualModelFieldException(
                        f"Property field `{k}` hinted at `{friendly_name}` "
                        f"in `{serializer_name}` "
                        f"must be defined in `{virtual_model.__class__.__name__}` "
                        "(or switched for a concrete field)"
                    )
                raise MissingVirtualModelFieldException(
                    f"Non-concrete field `{k}` hinted at `{friendly_name}` "
                    f"in `{serializer_name}` "
                    f"must be defined in `{virtual_model.__class__.__name__}`"
                )

    def _activate_prefetch_hints_decorator(self, field, model_cls, model_property_fields):
        if field.source in model_property_fields:
            function = getattr(model_cls, field.source).fget
        elif isinstance(field, serializers.SerializerMethodField):
            function = getattr(field.parent, field.method_name)
        else:
            function = None

        if function:
            decorator_instance: OnOffDecorator = getattr(function, "_decorator_instance", None)
            if decorator_instance:
                decorator_instance.activate()

    def _activate_query_blocking(
        self, readable_serializer_fields, model_cls, model_property_fields
    ):
        for field in readable_serializer_fields.values():
            self._activate_prefetch_hints_decorator(
                field=field,
                model_cls=model_cls,
                model_property_fields=model_property_fields,
            )

    def recursively_find_lookup_list(
        self, parent_virtual_model: BaseVirtualField = None
    ) -> List[str]:
        # if field is marked as `NoOp`, don't infer nested lookups:
        if isinstance(self.virtual_model, NoOp):
            return []

        readable_serializer_fields = utils.get_readable_fields(self.serializer_instance)
        model_cls = self.virtual_model.model_cls
        model_concrete_fields = utils.get_model_concrete_fields(model_cls)
        model_property_fields = utils.get_properties(model_cls)
        model_methods = utils.get_methods(model_cls)
        lookup_list = []

        # find lookups by looking at type hints and validate them
        # (note there's a recursion at `_maybe_handle_nested_serializer_field`)
        get_type_hints_handler_fns: List[Callable[..., List[str]]] = [
            # See DRF code: rest_framework/serializers.py::ModelSerializer::build_field
            # To learn about the various types of fields it can use.
            # We try to handle them all here:
            self._maybe_handle_concrete_field,
            self._maybe_handle_property_field,
            self._maybe_handle_model_method_field,
            self._maybe_handle_method_field,
            self._maybe_handle_relational_field,
            self._maybe_handle_field_with_nested_source,
            self._maybe_handle_url_field,
            self._maybe_handle_nested_serializer_field,
        ]
        for k, field in readable_serializer_fields.items():
            f_lookup_list = unassigned = object()
            for handler_fn in get_type_hints_handler_fns:
                try:
                    f_lookup_list = handler_fn(
                        field=field,
                        virtual_model=self.virtual_model,
                        parent_virtual_model=parent_virtual_model,
                        model_cls=model_cls,
                        model_property_fields=model_property_fields,
                        model_concrete_fields=model_concrete_fields,
                        model_methods=model_methods,
                    )
                    self._validate_lookup_list(
                        field=field,
                        virtual_model=self.virtual_model,
                        model_property_fields=model_property_fields,
                        model_concrete_fields=model_concrete_fields,
                        lookup_list=f_lookup_list,
                    )
                except self.CantHandleException:
                    continue

            if f_lookup_list is unassigned:
                field_name = utils.get_field_name(field)
                if field_name not in self.virtual_model.declared_fields:
                    serializer_name = field.parent.__class__.__name__
                    raise MissingVirtualModelFieldException(
                        f"`{field_name}` used by `{serializer_name}` "
                        f"must be defined in `{self.virtual_model.__class__.__name__}`"
                        + (
                            f" (nested on `{parent_virtual_model.__class__.__name__}`)"
                            if parent_virtual_model
                            else ""
                        )
                    )

                # include this field because it's available in `virtual_model.declared_fields`
                lookup_list.append(field_name)
            elif f_lookup_list is not None and isinstance(f_lookup_list, list):
                lookup_list.extend(f_lookup_list)
            else:
                raise Exception(
                    "Unreachable code. "
                    f"Debug info `{k}` from `{self.serializer_instance.__class__.__name__}`"
                )  # pragma: no cover

        # activate the `hints` decorators to block unexpected queries
        if self.block_queries:
            self._activate_query_blocking(
                readable_serializer_fields=readable_serializer_fields,
                model_cls=model_cls,
                model_property_fields=model_property_fields,
            )

        lookup_list = utils.unique_keep_order(lookup_list)
        return lookup_list
