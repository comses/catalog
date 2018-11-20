#!/usr/bin/env bash

cd /code/visualization/bokeh_example
exec bokeh serve --address 0.0.0.0 --allow-websocket-origin=localhost visualization
