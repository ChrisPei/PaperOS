CC ?= cc
ROOT ?= ..
OUT ?= ../build/host
FBINK_DIR ?= $(ROOT)/tools/FBInk
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Werror
CPPFLAGS += -I$(ROOT)/assets

ifdef KINDLE
CPPFLAGS += -DHAVE_FBINK -I$(FBINK_DIR)
LDLIBS += $(OUT)/fbink/libfbink.a
FBINK_DEP = $(OUT)/fbink/libfbink.a
endif
LDLIBS += -lm

all: $(OUT)/paperos $(OUT)/paperos-inputd $(OUT)/paperos-input $(OUT)/libpaperos-input.a

$(OUT)/paperos: paperos.c launcher.inc muyu.inc muyu.h store.inc store.h store_order.c dashboard.inc wallpaper.inc weather.inc battery.inc mihome.inc dashboard.h services.c services.h calendar.c calendar.h lunar-data.h solar-terms-data.h apps.c apps.h ime.c ime.h input.c input.h keyboard.c keyboard.h $(ROOT)/assets/stb_truetype.h $(FBINK_DEP)
	mkdir -p $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) paperos.c apps.c ime.c input.c keyboard.c services.c calendar.c store_order.c -o $@ $(LDFLAGS) $(LDLIBS)

$(OUT)/paperos-inputd: inputd.c input.c input.h
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) inputd.c input.c -o $@ $(LDFLAGS)

$(OUT)/paperos-input: input-cli.c input.c input.h
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) input-cli.c input.c -o $@ $(LDFLAGS)

$(OUT)/input.o: input.c input.h
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) -c input.c -o $@

$(OUT)/libpaperos-input.a: $(OUT)/input.o
	$(AR) rcs $@ $<

$(OUT)/fbink/libfbink.a:
	# libi2c.built is an unconditional upstream prerequisite but is Kobo-only.
	$(MAKE) -C $(FBINK_DIR) -o libi2c.built staticlib KINDLE=1 MINIMAL=1 IMAGE=1 DRAW=1 OUT_DIR=$(abspath $(OUT))/fbink CC="$(CC)" AR="$(AR)" RANLIB="$(RANLIB)" CFLAGS="-O2 -fno-common"

.PHONY: all

