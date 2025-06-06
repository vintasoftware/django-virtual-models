# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0]
- Rename internal `user` attribute from `VirtualModel` to `_user` to avoid conflict with ForeignKey and OneToOneField fields with the same name

## [0.3.0]

- Include `py.typed` file for type hints
- Add support to Python 3.12 and 3.13
- Drop support to Python 3.8 and 3.9
- Add support to Django 5.0, 5.1, and 5.2
- Drop support to Django 3.2, 4.0, and 4.1

## [0.2.0]

- Add support to nested prefetch lookups like `v.VirtualModel(manager=User.objects, lookup="course__facilitators")`
  * Warning: this will remain undocumented for now, because the behavior is strange:
             the prefetch is made inside `course` in this case, due to Django behavior.
- Add parameter `serializer_context` to be used in `v.Annotation` and `get_prefetch_queryset`.

## [0.1.6]

- Fix support for custom manager in `VirtualModel` initialization
- Separate method for `_build_prefetch` to allow overrides.

## [0.1.5]

- More robust `is_preloaded` check
- Add Django 4.2 to tests.

## [0.1.4]

- Add Python 3.11 to tests.

## [0.1.3]

- README update.

## [0.1.2]

- Avoid redundant `to_attr` when nesting Virtual Models
- Refactor `fields.py` to use `self.parent` and `self.field_name`
- Simplify docs and tests by not using manager param

## [0.1.1]

- Handle additional case for related primary key field.

## [0.1.0]

- Change the hints API from `prefetch.Required` to `hints.Virtual`.

## [0.0.2]

- Fix documentation link on PyPI.

## [0.0.1]

- First release.
