
# sudo apt-get install libgdal-dev gdal-bin

.venv/bin/activate:
	( \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		pip install -r requirements.txt \
	)

.PHONY: install
install: .venv/bin/activate

.PHONY: test
test:
	( \
		. .venv/bin/activate && \
		pytest tests -s \
	)

.PHONY: clean
clean:
	rm -rf out _tmp
