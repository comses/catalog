from bokeh.plotting import curdoc

from bokeh_example.models.publication_by_year import PublicationCountsByYear

p = PublicationCountsByYear().render()

curdoc().add_root(p)