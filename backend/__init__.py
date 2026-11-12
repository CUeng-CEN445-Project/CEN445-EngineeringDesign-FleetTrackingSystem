"""FiloTrack backend package.

Sub-packages:
    api/         HTTP layer: router, REST endpoints, SSE, static files
    simulation/  vehicle motion model, simulator thread, dashboard snapshot
    storage/     SQLite schema and table repositories

Modules:
    alarms.py    speeding / off-route alarm engine
    clock.py     timestamp helpers
    config.py    configuration and defaults
    geo.py       geographic calculations
    routes.py    simulated route and vehicle definitions
"""

import logging

# Library convention: leave logging configuration to the application (app.py).
# Without it (e.g. in tests) warnings are not printed via logging's "last resort" handler.
logging.getLogger("filotrack").addHandler(logging.NullHandler())
