import os

from bokeh.core.properties import String, List, Dict, Any
from bokeh.models import InputWidget


class VueMultiselectWidget(InputWidget):
    __implementation__ = os.path.join(os.path.dirname(__file__), 'vue_multiselect.js')
    __javascript__ = ['https://cdn.jsdelivr.net/npm/vue/dist/vue.js',
                      'https://cdn.jsdelivr.net/npm/debounce@1.2.0/index.min.js',
                      'https://unpkg.com/axios/dist/axios.min.js',
                      'https://cdn.jsdelivr.net/npm/vue-multiselect@2.1.0/dist/vue-multiselect.min.js']
    __css__ = ['https://unpkg.com/vue-multiselect@2.1.0/dist/vue-multiselect.min.css']

    selectedOptions = List(Dict(String(), Any(), help="""
    Initial value in the multiselect
    # """))

    options = List(Dict(String(), Any()), help="""
    List of dropdown options
    """, default=[])

    modelName = String(help='name of model you want to autocomplete against')