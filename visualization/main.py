from pprint import pprint

from bokeh.plotting import figure, curdoc

from models.publication_by_year import PublicationCountsByYear

p = PublicationCountsByYear().render()

curdoc().add_root(p)