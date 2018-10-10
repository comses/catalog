from bokeh.layouts import row
from bokeh.models import Panel, Tabs, Paragraph
from bokeh.plotting import curdoc

from models.publication_by_year import PublicationCodeAvailabilityChart, PublicationModelDocumentationChart, \
    PublicationCitationNetwork, Overview

code_availability = Panel(child=PublicationCodeAvailabilityChart().render(), title='Code Availability')
model_documentation_availability = Panel(child=PublicationModelDocumentationChart().render(), title='Model Documentation Availability')
citation_network = Panel(child=PublicationCitationNetwork().render(), title='Citation Network')
overview = Panel(child=Overview().render(), title='Overview')
tabs = Tabs(tabs=[overview, code_availability, model_documentation_availability, citation_network])
curdoc().add_root(tabs)
