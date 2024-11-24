
# sudo apt-get install libgdal-dev gdal-bin

.venv/bin/activate:
	( \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		pip install -r requirements.txt \
	)

