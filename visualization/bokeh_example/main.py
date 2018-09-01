from bokeh.plotting import curdoc

from models.publication_by_year import PublicationCountsByYear

p = PublicationCountsByYear().render()

curdoc().add_root(p)