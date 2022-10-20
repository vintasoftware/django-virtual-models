## Example models

This tutorial will use the following Django models:

```python
class Person(models.Model):
    name = models.CharField(max_length=255)
    biography = models.TextField()

class Nomination(models.Model):
    award = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    person = models.ForeignKey(Person, related_name="nominations")
    movie = models.ForeignKey("Movie", related_name="nominations")
    is_winner = models.BooleanField()

class PersonDirector(models.Model):
    movie = models.ForeignKey("Movie")
    person = models.ForeignKey(Person)

class Movie(models.Model):
    name = models.CharField(max_length=255)
    directors = models.ManyToManyField(
        Person,
        through=PersonDirector,
        blank=True,
        related_name="directed_movies",
    )
```

## Why Django Virtual Models

Due to the way Django (and especially Django REST Framework) projects are structured, read logic is usually far from prefetch and annotation logic, but both are coupled. This coupling results in brittle code that suffers from [*change amplification*](https://en.wikiversity.org/wiki/Software_Design/Change_amplification).


!!! note
    This section describes the change amplification problem using Django REST Framework as an example, but other API frameworks (and sometimes Django-only codebases) suffer from similar problems because read logic is naturally coupled to prefetch and annotation logic. Please keep reading to check if Django Virtual Models is helpful to you. Then, the ["Using Virtual Models manually"](#using-virtual-models-manually) section to learn how to use this library without DRF.

Imagine you have the following DRF serializers:

```python
class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ["name"]

class MovieSerializer(serializers.ModelSerializer):
    directors = PersonSerializer(many=True)

    class Meta:
        model = Movie
        fields = ["name", "directors"]
```

Now, for every view that uses `MovieSerializer` you'll have to remember to do the following prefetch in every `get_queryset` method:

```python
class MovieListView(ListAPIView):
    serializer_class = MovieSerializer

    def get_queryset(self):
        return Movie.objects.prefetch_related("directors")

class MovieDetailView(RetrieveAPIView):
    serializer_class = MovieSerializer

    def get_queryset(self):
        return Movie.objects.prefetch_related("directors")
```

Otherwise you'll get the [*N+1 selects problem*](https://stackoverflow.com/questions/97197/what-is-the-n1-selects-problem-in-orm-object-relational-mapping), which is a possibly the main cause of performance issues in Django applications.

As the codebase gets more functionality, the problems get worse, and not only for N+1s. For example, if you add a new field inside `PersonSerializer`, like one that comes from an `annotate`, now you have to remember to call that `annotate` in all views that use `MovieSerializer`, because it has `PersonSerializer` nested on it:

```python
# Adding `nomination_count` here...
class PersonSerializer(serializers.ModelSerializer):
    nomination_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Person
        fields = ["name", "nomination_count"]

# ... requires changes here:
def queryset_ops_for_MovieSerializer(qs):
    return qs.prefetch_related(
        Prefetch(
            "directors",
            queryset=Person.objects.annotate(
                nomination_count=Count("nominations")
            ).distinct()
        )
    )

class MovieListView(ListAPIView):
    serializer_class = MovieSerializer

    def get_queryset(self):
        return queryset_ops_for_MovieSerializer(Movie.objects.all())

class MovieDetailView(RetrieveAPIView):
    serializer_class = MovieSerializer

    def get_queryset(self):
        return queryset_ops_for_MovieSerializer(Movie.objects.all())
```

Any change that requires a `annotate`, `select_related`, and `prefetch_related` in `MovieSerializer` or any of its nested serializers like `PersonSerializer` will demand changes in (possibly) many view classes. As views and serializers are usually not in the same Python module, it's hard to ensure those coordinated changes while coding and it's even harder to review that in Pull Requests. Read logic is naturally coupled to prefetch and annotation logic!

But at first glance, it seems the solution is abstracting the queryset operations in a function. Is that robust? What if we're using `PersonSerializer` in another view? We would have to abstract again with another function:

```python
def queryset_ops_for_PersonSerializer(qs):  # <--- need this now
    return qs.annotate(
        nomination_count=Count("nominations")
    ).distinct()

def queryset_ops_for_MovieSerializer(qs):
    return qs.prefetch_related(
        Prefetch(
            "directors",
            queryset=queryset_ops_for_PersonSerializer(Person.objetcs.all())
        )
    )

class MovieListView(ListAPIView):
    serializer_class = MovieSerializer

    def get_queryset(self):
        return queryset_ops_for_MovieSerializer(Movie.objects.all())

class MovieDetailView(RetrieveAPIView):
    serializer_class = MovieSerializer

    def get_queryset(self):
        return queryset_ops_for_MovieSerializer(Movie.objects.all())

class PersonView(RetrieveAPIView):
    serializer_class = PersonSerializer

    def get_queryset(self):
        return queryset_ops_for_PersonSerializer(Person.objects.all())
```

This rapidly results in a unwieldy codebase, and still suffers from change amplification. It's easy to nest serializers, but it's hard to nest those queryset operations because you have to change code in multiple places. As you can see, the queryset logic is always coupled with the serializer logic... so why not handle both things together somehow?

What if we had a tool that warns us about missing annotations and prefetches by reading a serializer and infering what queryset operations it needs? That's exactly what Django Virtual Models do.

## Defining Virtual Models (Django REST Framework examples)

### Handling prefetches and annotations

To solve the change amplification on view querysets vs. serializers, the key is to create another layer to remove the responsibility from the view to set the queryset operations the serializer needs. That layer is the Virtual Model. The minimum virtual model looks like this:

```python
import django_virtual_models as v

class VirtualMovie(v.VirtualModel):
    class Meta:
        model = Movie
```

The best thing is: this is already usable. Although the only purpose to use an empty Virtual Model is to get an exception...

But that's what you want! The idea is to be guided by the virtual model exceptions to know what fields you need to add to it. First, integrate the `VirtualMovie` with the `MovieSerializer` and the view by doing the following:

```python
import django_virtual_models as v

class MovieSerializer(v.VirtualModelSerializer):
    directors = PersonSerializer(many=True)

    class Meta:
        model = Movie
        virtual_model = VirtualMovie  # <--- add this
        fields = ["name", "directors"]


class MovieListView(v.VirtualModelListAPIView):  # <--- changed base class
    serializer_class = MovieSerializer
    queryset = Movie.objects.all()

class MovieDetailView(v.VirtualModelRetrieveAPIView):  # <--- changed base class
    serializer_class = MovieSerializer
    queryset = Movie.objects.all()
```

Now, if we try to access the `MovieListView` by hitting its URL, we get the following exception:

```
MissingVirtualModelFieldException at /movies/
`directors` must be defined in `VirtualMovie` because it's a nested serializer on `MovieSerializer`
```

In the browser, it looks like this:

![MissingVirtualModelFieldException for directors](https://user-images.githubusercontent.com/397989/194100101-344b89e3-faf9-4e9a-a69e-8ee1e6e480d5.png)

The exception is clearly telling us we need a `directors` field inside `VirtualMovie`. Since it's a relationship between models, we're going to create an empty Virtual Model for `Person` and reference it in the `directors` field:

```python
class VirtualPerson(v.VirtualModel):  # <--- new virtual model...
    class Meta:
        model = Person

class VirtualMovie(v.VirtualModel):
    directors = VirtualPerson()  # <--- ...nested here

    class Meta:
        model = Movie
```

Hitting the `MovieListView` URL again, we get another exception:

```
MissingVirtualModelFieldException at /movies/
`nomination_count` used by `PersonSerializer` must be defined in `VirtualPerson` (nested on `VirtualMovie`)
```

Now let's add `nomination_count` to `VirtualPerson`:

```python
class VirtualPerson(v.VirtualModel):
    nomination_count = v.Annotation(
        lambda qs, **kwargs: qs.annotate(
            nomination_count=Count("nominations")
        ).distinct()
    )

    class Meta:
        model = Person
```

Now the view works fine, without any N+1 queries or missing annotations! The `VirtualModelListAPIView` automatically uses the serializer and its virtual model to get an optimized queryset by overriding the `get_queryset` method.

!!! warning
    If you override the `get_queryset` method without calling super, the virtual model integration will not work. Either call `super().get_queryset()` or use the `GenericVirtualModelViewMixin` in case you have custom base view classes. Read more about why on section ["How DRF serializer integration works"](#how-drf-serializer-integration-works).

!!! warning
    If you already use a custom serializer class, use the `VirtualModelSerializerMixin`. Check the [source code](https://github.com/vintasoftware/django-virtual-models/blob/main/django_virtual_models/serializers.py) to learn how it works.

### Using filtered prefetches

If you need to prefetch a relationship with some filtering, you can define a method called `get_prefetch_queryset` inside the `VirtualModel`. Suppose we need to fetch only the nominations that a person won (with `is_winner=True`). It's simple to do that:

```python
class VirtualAward(v.VirtualModel):
    class Meta:
        model = Nomination

    def get_prefetch_queryset(self, **kwargs):  # <--- filter call here
        return Nomination.objects.filter(is_winner=True)


class VirtualPerson(v.VirtualModel):
    awards = VirtualAward(
        lookup="nominations"  # <--- the non-filtered relation name
    )

    class Meta:
        model = Person
```

### Using `to_attr` prefetches

As you can see in the previous example, you can specify the `to_attr` in nested virtual models, just as the regular `Prefetch` from Django. Remember to set both the `lookup` and the `to_attr`, as the left side attribute name corresponds to the field name in the serializer. In general, `to_attr` and the attribute name should be the same.

### Using joins (`select_related`)

If you want the same functionality of Django's `select_related`, you can use a `NestedJoin` field in the virtual model:

```python
class VirtualNomination(v.VirtualModel):
    person = v.NestedJoin(model_cls=Person)
    movie = v.NestedJoin(model_cls=Movie)

    class Meta:
        model = Nomination
```

With this, any access to `nomination.person` or `nomination.movie` won't make additional queries. Therefore, you can have nested serializers for those fields.

However, if those nested serializers have their own non-concrete fields (annotations or other nested serializers), then the virtual model will launch an exception with a message like this:

```
Cannot use a `NestedJoin` for `person` inside `VirtualNomination`.
`directors` must be a field of `person`,
because it's a nested serializer on `NominationSerializer`.
Change from `NestedJoin` to a `VirtualModel` and add `directors` as a field.
```

In other words, for further nesting you'll need nested `VirtualModel`s (which are nested prefetches behind the scenes).

### Deferring fields with `deferred_fields`

As Django's default behavior for querysets, Virtual Models load all concrete fields (all DB columns from the table) by default. If you have a model that contains concrete fields that are expensive to fetch, such as a `TextField` or a `JSONField` with lots of data, you can use `deferred_fields` to avoid fetching them:

```python
class VirtualPerson(v.VirtualModel):
    class Meta:
        model = Person
        deferred_fields = ["biography"]
```

Note this only makes a difference if the `biography` field is *not* declared in your serializer's `Meta.fields`. If it's there, this library assumes you'll need that field and will include it in the queryset to prevent N+1 queries.

But if you don't have the `biography` field in your serializer, any access to `person.biography` will make a new query. This is the same behavior of using `Person.objects.defer("biography")` in regular Django.

### Returning data relative to the current user

Sometimes it makes sense to include data relative to the current user in the virtual model fields.

Imagine you have a `UserMovieRating` model that relates users with movies and has a rating field:

```python
class UserMovieRating(models.Model):
    user = models.ForeignKey("User")
    movie = models.ForeignKey("Movie", related_name="ratings")
    rating = models.DecimalField(max_digits=3, decimal_places=1)
```

You can add a field for `user_rating` in a `MovieSerializer`:

```python
class MovieSerializer(v.VirtualModelSerializer):
    user_rating = serializers.DecimalField(max_digits=3, decimal_places=1)

    class Meta:
        model = Movie
        virtual_model = VirtualMovie
        fields = ["name", "user_rating"]
```

But you need to declare `user_rating` on `VirtualMovie` and ensure it is fetching the rating for the current user. This is possble with the following code:

```python
class VirtualMovie(v.VirtualModel):
    user_rating = v.Annotation(
        # Note `user` is an argument here:
        lambda qs, user, **kwargs: qs.annotate(
            Subquery(
                UserMovieRating.objects.filter(
                    movie=OuterRef("pk"),
                    user=user
                ).values("rating")[:1]
            )
        )
    )

    class Meta:
        model = Movie
```

The `user` argument is available on `v.Annotation` thanks to `v.VirtualModelSerializer` that gets the current user from `self.context["request"].user`.

The `user` argument is also available on `get_prefetch_queryset` for use in filtered prefetches. Therefore, the following code works:

```python
class VirtualUserMovieRating(v.VirtualModel):
    class Meta:
        model = UserMovieRating

    def get_prefetch_queryset(self, user, **kwargs):  # <--- here
        return UserMovieRating.objects.filter(user=user)
```

!!! warning
    An advice: in general, you should avoid returning data relative to the current user in HTTP APIs, as this makes caching very hard or even impossible. Use this only if you really need it, as in a request that's only specific for users like user profile pages. Avoid nesting data related to the current user inside global data. Consider adding an additional request to fetch data relative to the current user, and then "hydrate" the previous request data on the frontend.

### Ignoring a serializer field

If you have a serializer field that fetches data from somewhere other than your Django models, you cannot prefetch data for it with a Virtual Model. So you need to make the Virtual Model ignore that field.

Suppose you have some serializer that fetches data from an external service:

```python
class IMDBRatingField(serializers.Field):
    """
    Fetches the IMDB Rating for the movie.
    """
    ...

class MovieSerializer(v.VirtualModelSerializer):
    imdb_rating = IMDBRatingField()

    class Meta:
        model = Movie
        virtual_model = VirtualMovie
        fields = ["name", "imdb_rating"]
```

You need to mark `imdb_rating` as something to be ignored in the `VirtualMovie`. Use `v.NoOp()` for that:

```python
class VirtualMovie(v.VirtualModel):
    imdb_rating = v.NoOp()

    class Meta:
        model = Movie
```

## Prefetch hints with Django REST Framework

If your DRF serializer uses method fields, model methods or properties, you can still use Virtual Models with it! But you need to add some *prefetch hints*.

### Prefetching for method fields (`SerializerMethodField`)

It's very common to use `SerializerMethodField` in DRF serializers. If those method fields need some virtual model fields, you need to specify that. Suppose you have the following virtual model and serializer:

```python
class VirtualPerson(v.VirtualModel):
    awards = VirtualAward(lookup="nominations")

    class Meta:
        model = Person

class PersonSerializer(v.VirtualModelSerializer):
    has_won_any_award = serializers.SerializerMethodField()

    class Meta:
        model = Person
        virtual_model = VirtualPerson
        fields = ["name", "has_won_any_award"]

    def get_has_won_any_award(self, person):
        # How to ensure `person` will have `awards`?
        return len(person.awards) > 0
```

This serializer needs the `awards` field from `VirtualPerson` inside `get_has_won_any_award` method, otherwise it would raise an `AttributeError` as this is a *virtual field*. But how to specify that requirement? There are multiple ways of doing this:

#### Using type hints with `hints.Virtual`

This library supports special type hints for informing what virtual fields a serializer method needs:

```python
# Python < 3.9. For >= 3.9, use `from typing import Annotated`:
from typing_extensions import Annotated
from django_virtual_models import hints

class PersonSerializer(v.VirtualModelSerializer):
    ...

    def get_has_won_any_award(
        self,
        # Type hint to ensure `awards` here:
        person: Annotated[Person, hints.Virtual("awards")]
    ):
        return len(person.awards) > 0
```

Now thanks to `hints.Virtual("awards")`, this serializer will be able to require the field `awards` from the virtual model. If necessary, you can pass multiple fields or even nested lookups: `hints.Virtual("awards", "nominations__movie")`.

!!! note
    `hints.Virtual` can be used to ensure the fetching of any `deferred_fields` a method needs without N+1s.

!!! note
    [Annotated](https://docs.python.org/3/library/typing.html#typing.Annotated) is a built-in Python construct that allows us to add custom annotations that don't affect type checking.

#### Using `from_types_of` decorator

If your method calls another function, you can add type hints to that function with `hints.Virtual` and then use the `from_types_of` decorator:

```python
# Python < 3.9. For >= 3.9, use `from typing import Annotated`:
from typing_extensions import Annotated
from django_virtual_models import hints

def check_person_has_won_any_award(
    # Type hint to ensure `awards` here:
    person: Annotated[Person, hints.Virtual("awards")]
):
    return len(person.awards) > 0

class PersonSerializer(v.VirtualModelSerializer):
    ...

    # Decorator to specify where to find the type hint here:
    @hints.from_types_of(check_person_has_won_any_award, "person")
    def get_has_won_any_award(self, person, check_person_has_won_any_award):
        return check_person_has_won_any_award(person)
```

Note the function `check_person_has_won_any_award` is received in the decorator and passed to the method as an additional argument. This allow serializer methods to fully delegate their logic to some external helper function. Use that only if you really need that kind of indirection.

#### If you already defined the field on the virtual model

If you have the `has_won_any_award` field in your virtual model, you can use the `defined_on_virtual_model` decorator:

```python
from django_virtual_models import hints

class PersonSerializer(v.VirtualModelSerializer):
    ...

    @hints.defined_on_virtual_model()  # <--- here
    def get_has_won_any_award(self, person):
        return person.has_won_any_award
```

#### If you only use concrete fields

If your method field only uses concrete fields, in other words, it doesn't depend on any virtual model fields, nor any `deferred_fields`, you can use the `no_deferred_fields` decorator:

```python
from django_virtual_models import hints

class PersonSerializer(v.VirtualModelSerializer):
    name_title_case = serializers.SerializerMethodField()

    class Meta:
        model = Person
        virtual_model = VirtualPerson
        fields = ["name_title_case"]

    @hints.no_deferred_fields()  # <--- here
    def get_name_title_case(self, person):
        return person.name.title()
```

### Prefetching for model properties and methods

DRF Serializers can use directly model properties and methods in `Meta.fields`. If your serializer uses a model property or method, you need to use the same hints described by the previous section ["Prefetching for method fields"](#prefetching-for-method-fields-serializermethodfield). For example:

```python
from django_virtual_models import hints

class Person(models.Model):
    name = models.CharField(max_length=255)

    @property  # <--- property must come before
    @hints.no_deferred_fields()
    def name_title_case(self):
        return self.name.title()

    # method w/o params, DRF supports that too:
    def has_won_any_award(self: Annotated[Person, hints.Virtual("awards")]):
        return len(person.awards) > 0

class PersonSerializer(v.VirtualModelSerializer):
    class Meta:
        model = Person
        virtual_model = VirtualPerson
        fields = ["name_title_case", "has_won_any_award"]  #  <--- this works
```

## Using Virtual Models manually

### Getting optimized querysets

If you do not use Django REST Framework, you can still benefit from using Virtual Models to avoid maintaining annotations and prefetches across several parts of your codebase. By centralizing the read logic in virtual models, you reduce cognitive load and change amplification.

Consider the following virtual models:

```python
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

You can hydrate an existing queryset with those virtual fields by using a syntax similar to Django lookups:

```python
qs = Movie.objects.order_by("name")
optimized_qs = VirtualMovie().get_optimized_queryset(
    qs,
    lookup_list=[
        "directors__awards",
        "directors__nomination_count",
    ]
)
```

When the `lookup_list` omits a virtual field, it is not included in the optimized queryset.

If you want to get all virtual fields, pass `lookup_list=None` or omit the parameter.

### Passing down `**kwargs`

The keyword arguments you pass in the virtual model constructor are passed down to `v.Annotate` and `get_prefetch_queryset` of all nested virtual models.

### How DRF serializer integration works

The main logic that connects DRF serializers with Virtual Models is on `LookupFinder` ([source code](https://github.com/vintasoftware/django-virtual-models/blob/main/django_virtual_models/prefetch/serializer_optimization.py)). The `LookupFinder` automatically discovers what virtual fields are needed and raise exceptions if they're not available in the virtual model associated with the serializer. It has a method called `recursively_find_lookup_list` that returns a `lookup_list` to be passed to serializer's virtual model. `recursively_find_lookup_list` is called on `get_queryset` from `GenericVirtualModelViewMixin` ([source code](https://github.com/vintasoftware/django-virtual-models/blob/main/django_virtual_models/generic_views.py)).

If necessary, you can customize this logic in your own view classes.
