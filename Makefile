.PHONY: check test render serve serve-left serve-right

check: test render   ## everything CI runs

test:                ## stdlib + pytest, no network
	python3 -m pytest -q

render:              ## open both sites in Chromium, fail on errors, refresh docs/screenshots/
	node scripts/render.mjs

# `make serve` runs both sides so the sibling status check resolves locally.
serve:
	@trap 'kill 0' INT TERM; \
	python3 -m http.server 8001 --bind 127.0.0.1 --directory sites/left/public & \
	python3 -m http.server 8002 --bind 127.0.0.1 --directory sites/right/public & \
	echo "left  → http://localhost:8001/"; echo "right → http://localhost:8002/"; wait

serve-left:
	python3 -m http.server 8001 --bind 127.0.0.1 --directory sites/left/public

serve-right:
	python3 -m http.server 8002 --bind 127.0.0.1 --directory sites/right/public
