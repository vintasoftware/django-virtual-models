<p align="center" style="margin: 0 0 10px">
  <img width="100" src="https://user-images.githubusercontent.com/397989/193950778-4550eebb-8650-45f8-8f57-d3bbab15e91a.svg" alt="Django Virtual Models Icon">
</p>
<p align="center">
  <strong>Django Virtual Models</strong>
</p>
<p align="center">
    <em>Improve performance and maintainability with a prefetching layer in your Django / Django REST Framework project</em>
</p>
<p align="center">
<a href="https://github.com/vintasoftware/django-virtual-models/actions?query=workflow%3ATest+event%3Apush+branch%3Amain" target="_blank">
    <img src="https://github.com/vintasoftware/django-virtual-models/workflows/tests/badge.svg?event=push&branch=main" alt="Test">
</a>&nbsp;
<a href="https://coveralls.io/github/vintasoftware/django-virtual-models?branch=main" target="_blank">
    <img src="https://coveralls.io/repos/github/vintasoftware/django-virtual-models/badge.svg?branch=main" alt="Coverage Status" />
</a>&nbsp;
<a href="https://pypi.org/project/django-virtual-models" target="_blank">
    <img src="https://img.shields.io/pypi/v/django-virtual-models?color=%2334D058&label=pypi%20package" alt="Package version">
</a>&nbsp;
<a href="https://pypi.org/project/django-virtual-models" target="_blank">
    <img src="https://img.shields.io/pypi/pyversions/django-virtual-models.svg?color=%2334D058" alt="Supported Python versions">
</a>
</p>

---

**Documentation**: <a href="https://vintasoftware.github.io/django-virtual-models/" target="_blank">https://vintasoftware.github.io/django-virtual-models/</a>

**Example project**: <a href="https://github.com/vintasoftware/django-virtual-models/tree/main/example" target="_blank">https://github.com/vintasoftware/django-virtual-models/tree/main/example</a>

**Source Code**: <a href="https://github.com/vintasoftware/django-virtual-models" target="_blank">https://github.com/vintasoftware/django-virtual-models</a>

---

Django Virtual Models introduces a new "prefetching layer" to Django codebases that assists developers to express complex read logic without sacrificing maintainability, composability and performance. A Virtual Model allows developers to declare all nesting they need along with all annotations, prefetches, and joins in a single declarative class.

When implementing Django REST Framework serializers, developers need to be careful to avoid causing the [*N+1 selects problem*](https://stackoverflow.com/questions/97197/what-is-the-n1-selects-problem-in-orm-object-relational-mapping) due to missing `prefetch_related` or `select_related` calls on the associated queryset. Additionaly, developers must not miss `annotate` calls for fields that are computed at queryset-level.

With Virtual Models integration with DRF, if you change a DRF Serializer, you won't forget to modify the associated queryset with additional annotations, prefetches, and joins. If you do forget to update the queryset, Django Virtual Models will guide you by raising friendly exceptions to assist you to write the correct Virtual Model for the serializer you're changing. This guidance will prevent N+1s and missing annotations in all serializers that use Virtual Models.

For example, imagine if you have following nested serializers starting from `MovieSerializer`:

```python
from movies.models import Nomination, Person, Movie

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

class MovieSerializer(serializers.ModelSerializer):
    directors = PersonSerializer(many=True)

    class Meta:
        model = Movie
        fields = ["name", "directors"]

```

For good performance and correct functionality, all nested serializers must have a corresponding `prefetch_related` on the queryset used by `MovieSerializer`. Also, the `nomination_count` field should be `annotate`d on it. Therefore, you'll need to write this complex chain of nested prefetches:

```python
from django.db.models import Prefetch

awards_qs = Nomination.objects.filter(is_winner=True)

directors_qs = Person.objects.prefetch_related(
    Prefetch(
        "nominations",
        queryset=awards_qs,
        to_attr="awards"
    )
).annotate(
    nomination_count=Count("nominations")
).distinct()

qs = Movie.objects.prefetch_related(
    Prefetch(
        "directors",
        queryset=directors_qs
    )
)
```

Conversely, you can declare Virtual Models for this read logic to easily reuse and customize those classes in multiple places of the codebase:

```python
import django_virtual_models as v

class VirtualAward(v.VirtualModel):
    class Meta:
        model = Nomination

    def get_prefetch_queryset(self, **kwargs):
        return Nomination.objects.filter(is_winner=True)


class VirtualPerson(v.VirtualModel):
    awards = VirtualAward(lookup="nominations")
    nomination_count = v.Annotation(
        lambda qs, **kwargs: qs.annotate(
            nomination_count=Count("nominations")
        ).distinct()
    )

    class Meta:
        model = Person


class VirtualMovie(v.VirtualModel):
    directors = VirtualPerson()

    class Meta:
        model = Movie
```

To configure your DRF view and serializer to use Virtual Models, inherit from the proper classes:

```python
import django_virtual_models as v

class MovieSerializer(v.VirtualModelSerializer):
    ...

    class Meta:
        ...
        virtual_model = VirtualMovie

class MovieList(v.VirtualModelListAPIView):
    queryset = Movie.objects.all()
    serializer_class = MovieSerializer
    ...
```

**Then the library will automatically do the right prefetches and annotations for you!**

If, for example, you forget to add the `nomination_count` field on `VirtualPerson`, the following exception will appear when using `MovieSerializer`:

![MissingVirtualModelFieldException exception](https://user-images.githubusercontent.com/397989/193944879-5205d80b-4102-415e-b178-7630a14db5a1.png)

If you aren't using DRF serializers, you hydrate your queryset with *virtual fields* manually:

```python
qs = VirtualMovie().get_optimized_queryset(
    Movie.objects.all(),
    lookup_list=[
        "directors__awards",
        "directors__nomination_count",
    ]
)
```

To learn more, check the [Installation](https://vintasoftware.github.io/django-virtual-models/installation/) and the [Tutorial](https://vintasoftware.github.io/django-virtual-models/tutorial/).
Or the [example project](https://github.com/vintasoftware/django-virtual-models/tree/main/example).
