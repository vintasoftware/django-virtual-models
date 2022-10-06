## Example models

This tutorial will use the following Django models:

```python
class Person(models.Model):
    name = models.CharField(max_length=255)

class Nomination(models.Model):
    award = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    year = models.PositiveSmallIntegerField()
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

Due to the way Django (and especially Django REST Framework) projects are structured, read logic is usually far from prefetching logic and this causes brittle code that suffers from [*change amplification*](https://en.wikiversity.org/wiki/Software_Design/Change_amplification).


!!! note
    This section describes the change amplification problem using Django REST Framework as an example, but other API frameworks (and sometimes Django-only codebases) suffer from similar problems because read logic and serialization are naturally coupled to prefetching. Please keep reading to check if Django Virtual Models is helpful to you and check the latter sections to learn how to use this library without DRF.

For example, imagine you have the following DRF serializers:

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
        fields = ["name"]

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

Any change that requires a `annotate`, `select_related`, and `prefetch_related` in `MovieSerializer` or any of its nested serializers like `PersonSerializer` will demand changes in (possibly) many view classes. As views and serializers are usually not in the same Python module, it's hard to ensure those coordinated changes while coding and it's even harder to review that in Pull Requests.

But at first glance, it seems that solution of abstracting the queryset operations in a function works. Is it really so? What if we're using `PersonSerializer` in another view? We would have to abstract again with another function:

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

## Defining and using Virtual Models with Django REST Framework

### Handling prefetches and annotations

To solve the change amplification on view querysets vs. serializers, the key is to create another layer to remove the responsibility from the view to set the queryset operations the serializer needs. That layer is the Virtual Model. The minimum virtual model looks like this:

```python
import django_virtual_models as v

class VirtualMovie(v.VirtualModel):
    class Meta:
        model = Movie
```

The best thing is: this is already usable! Although the only purpose to use an empty Virtual Model is to get an exception...

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

!!! warning
    If you override the `get_queryset` method without calling super, the virtual model integration will not work. Either call `super().get_queryset()` or use the `v.GenericVirtualModelViewMixin` in case you have custom base view classes. Check the [source code](https://github.com/vintasoftware/django-virtual-models/blob/main/django_virtual_models/generic_views.py) to learn how it works.

Now, if we try to access the `MovieListView` by hitting its URL, we get the following exception:

```
MissingVirtualModelFieldException at /movies/
`directors` must be defined in `VirtualMovie` because it's a nested serializer on `MovieSerializer`
```

In the browser, it looks like this:

![MissingVirtualModelFieldException for directors](https://user-images.githubusercontent.com/397989/194100101-344b89e3-faf9-4e9a-a69e-8ee1e6e480d5.png)

The exception is clearly telling us we need a `directors` field inside `VirtualMovie`. Since it's a relationship between models, we're going to create an empty Virtual Model for `Person` and reference it in the `directors` field:

```python
class VirtualPerson(v.VirtualModel):
    class Meta:
        model = Person

class VirtualMovie(v.VirtualModel):
    directors = VirtualPerson(manager=Person.objects)

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

### Using filtered prefetches

If you need to prefetch a relationship with some filtering, you can define a method called `get_prefetch_queryset` inside the `VirtualModel`. For example, suppose we need to fetch only the nominations that a person won (with `is_winner=True`). It's simple to do that:

```python
class VirtualAward(v.VirtualModel):
    class Meta:
        model = Nomination

    def get_prefetch_queryset(self, **kwargs):  # <--- filter here
        return Nomination.objects.filter(is_winner=True)


class VirtualPerson(v.VirtualModel):
    awards = VirtualAward(
        manager=Nomination.objects,
        lookup="nominations",  # <--- lookup is the non-filtered relation name
        to_attr="awards")  # <--- `to_attr` is the same behavior from Django's Prefetch

    class Meta:
        model = Person
```

### Using `to_attr` prefetches

As with the regular `Prefetch` from Django, you can specify the `to_attr` in nested virtual models. Just remember to set both the `lookup` and the `to_attr`, as the left side attribute name corresponds to the field name in the serializer. In general, `to_attr` and the attribute name should be the same. Check the example above on "Using filtered prefetches".

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

### Deferring fields with `deferred_fields`

TODO.

### Using methods and properties

TODO.

### Using nested serializers manually

TODO.

### Ignoring a field

TODO.

## Defining and using Virtual Models manually

### Getting optimized querysets

If you do not use Django REST Framework, you can still benefit from using Virtual Models to avoid maintaining annotations and prefetches across several parts of your codebase. By centralizing the read logic in virtual models, you reduce the cognitive load and the change amplification.

Consider the following virtual models:

```python
class VirtualAward(v.VirtualModel):
    class Meta:
        model = Nomination

    def get_prefetch_queryset(self, **kwargs):
        return Nomination.objects.filter(is_winner=True)

class VirtualPerson(v.VirtualModel):
    awards = VirtualAward(
        manager=Nomination.objects,
        lookup="nominations",
        to_attr="awards",
    )
    nomination_count = v.Annotation(
        lambda qs, **kwargs: qs.annotate(
            nomination_count=Count("nominations")
        ).distinct()
    )

    class Meta:
        model = Person
```

You can hydrate... TODO.

### Selecting fields with lookup syntax

TODO.

## Advanced usage

### Inheriting virtual models

TODO.

### Passing down current request user

TODO.

### Passing down `**kwargs`

TODO.
