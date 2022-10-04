from movies.models import Movie
from movies.serializers import MovieSerializer

import django_virtual_models as v


class MovieList(v.VirtualModelListAPIView):
    queryset = Movie.objects.all()
    serializer_class = MovieSerializer
