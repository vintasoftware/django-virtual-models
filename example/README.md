# Example project for django-virtual-models

This is a very simple Django project with a single app called `movies` and some initial data to demonstrate how to use django-virtual-models.
It follows from the example in the django-virtual-models's README.

## Running the project

1. `python manage.py migrate`
1. `python manage.py loaddata movies_initial.yaml`
1. `python manage.py runserver`

Now go to `http://localhost:8000/movies/` to see what data the view returns.

## Architecture

First, check the models at `example/movies/models.py` to learn how the relationships are set.

Then, check the following Python modules to learn how django-virtual-models works:

- `example/movies/views.py`
- `example/movies/virtual_models.py`
