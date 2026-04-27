# Build voxl-clean-logger on the VOXL 2 (or in the voxl-cross docker image).
#
#   make            -> builds ./voxl-clean-logger
#   make install    -> installs to /usr/bin/voxl-clean-logger
#   make clean

CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -Wno-unused-parameter
LDFLAGS ?=
LIBS    := -lmodal_pipe -lmodal_json -lpthread

SRC := src/voxl_clean_logger.c
BIN := voxl-clean-logger
PREFIX ?= /usr

$(BIN): $(SRC)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LIBS)

install: $(BIN)
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 0755 $(BIN) $(DESTDIR)$(PREFIX)/bin/$(BIN)

clean:
	rm -f $(BIN) src/*.o

.PHONY: install clean
