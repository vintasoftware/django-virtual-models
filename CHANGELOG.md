# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.6]

- Fix support for custom manager in VirtualModel
- Separate method for _build_prefetch to allow overrides

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
