from django.core.serializers import serialize
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Model
from django.db.models.query import QuerySet
from django.http import JsonResponse as DjangoJsonResponse
from django.utils.functional import curry

import json


class CatalogJSONEncoder(DjangoJSONEncoder):

    def default(self, obj):
        if isinstance(obj, QuerySet):
            return json.loads(serialize('json', obj))
        elif isinstance(obj, Model):
            return json.loads(serialize('json', [obj]))[0]
        else:
            return DjangoJSONEncoder.default(self, obj)

dumps = curry(json.dumps, cls=CatalogJSONEncoder)


class JsonResponse(DjangoJsonResponse):

    """ Proxies django's JsonResponse with CatalogJSONEncoder and safe=False defaults """

    def __init__(self, dictionary, encoder=CatalogJSONEncoder, safe=False, **kwargs):
        super(JsonResponse, self).__init__(
            dictionary, encoder=encoder, safe=safe, **kwargs)
