# micropython/interlog_run.py — eki-bin
#
# Run the REAL firmware with recording switched on, without editing config.py.
# Launched by scripts/interaction_log.py via
#     mpremote mount micropython run micropython/interlog_run.py
# (mounted from the Mac — nothing is written to flash, same reasoning as
# `make dev`).
#
# A wrapper rather than a flag in config.py on purpose: config.py holds
# credentials and is deliberately never read or edited by tooling, and a
# recording should be a thing you START, not a state a unit is left in.
import settings

settings.INTERACTION_LOG = True

import main  # noqa: E402  (must come AFTER the flag is set)

main.main()
