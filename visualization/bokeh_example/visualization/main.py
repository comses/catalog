from bokeh.layouts import row
from bokeh.plotting import curdoc

from models.publication_by_year import PublicationCountsByYear, PublicationCocitationGraph

# p = PublicationCountsByYear().render()
g = PublicationCocitationGraph().render()
curdoc().add_root(row(g))