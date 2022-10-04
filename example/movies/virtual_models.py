from django.db.models.aggregates import Count

from movies.models import Movie, Nomination, Person

import django_virtual_models as v


class VirtualAward(v.VirtualModel):
    class Meta:
        model = Nomination

    def get_prefetch_queryset(self, **kwargs):
        return Nomination.objects.filter(is_winner=True)


class VirtualPerson(v.VirtualModel):
    awards = VirtualAward(manager=Nomination.objects, lookup="nominations", to_attr="awards")
    nomination_count = v.Annotation(
        lambda qs, **kwargs: qs.annotate(nomination_count=Count("nominations")).distinct()
    )

    class Meta:
        model = Person


class VirtualMovie(v.VirtualModel):
    directors = VirtualPerson(manager=Person.objects)

    class Meta:
        model = Movie
