from django.core.management import call_command
from django.urls import reverse

import pytest


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("loaddata", "movies_initial.yaml")


@pytest.mark.django_db
def test_movie_list_get(client, django_assert_num_queries):
    expected_response_data = [
        {
            "name": "The Matrix",
            "directors": [
                {
                    "name": "Lana Wachowski",
                    "awards": [
                        {
                            "award": "Saturn Awards",
                            "category": "Best Director",
                            "year": 2000,
                            "is_winner": True,
                        }
                    ],
                    "nomination_count": 2,
                },
                {
                    "name": "Lilly Wachowski",
                    "awards": [
                        {
                            "award": "Saturn Awards",
                            "category": "Best Director",
                            "year": 2000,
                            "is_winner": True,
                        }
                    ],
                    "nomination_count": 2,
                },
            ],
        },
        {
            "name": "Drive",
            "directors": [
                {
                    "name": "Nicolas Winding Refn",
                    "awards": [
                        {
                            "award": "Cannes Film Festival",
                            "category": "Best Director",
                            "year": 2011,
                            "is_winner": True,
                        }
                    ],
                    "nomination_count": 2,
                }
            ],
        },
    ]

    url = reverse("movies:list")
    with django_assert_num_queries(3):
        response = client.get(url)
    response_data = response.json()

    assert response_data == expected_response_data
