from django.core.exceptions import ImproperlyConfigured


class MissingHintsException(Exception):
    pass


class InvalidLookupException(Exception):
    pass


class InvalidFieldException(Exception):
    pass


class InvalidVirtualModelParams(Exception):
    pass


class ImproperlyConfiguredVirtualModelSerializer(ImproperlyConfigured):
    pass
