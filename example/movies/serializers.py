from rest_framework import serializers

from movies.models import Movie, Nomination, Person
from movies.virtual_models import VirtualMovie

import django_virtual_models as v


class AwardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Nomination
        fields = ["award", "category", "year", "is_winner"]


class PersonSerializer(serializers.ModelSerializer):
    awards = AwardSerializer(many=True)
    nomination_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Person
        fields = ["name", "awards", "nomination_count"]


class MovieSerializer(v.VirtualModelSerializer):
    directors = PersonSerializer(many=True)

    class Meta:
        model = Movie
        virtual_model = VirtualMovie
        fields = ["name", "directors"]
