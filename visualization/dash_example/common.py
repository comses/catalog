import dash

import data_wrangling as dw

app = dash.Dash()

app.config.supress_callback_exceptions = True
data_cache = dw.DataCache()
