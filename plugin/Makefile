PLUGIN_NAME = hypr-canvas

CXX = g++
PLUGIN_CXXFLAGS = -shared -fPIC -std=c++2b -O2
PLUGIN_CPPFLAGS = $(shell pkg-config --cflags hyprland pixman-1 libdrm)
INCLUDES =

SRC = src/main.cpp src/canvas.cpp
OUT = $(PLUGIN_NAME).so

all: $(OUT)

$(OUT): $(SRC) src/canvas.hpp
	$(CXX) $(PLUGIN_CXXFLAGS) $(CXXFLAGS) $(PLUGIN_CPPFLAGS) $(CPPFLAGS) $(INCLUDES) $(SRC) -o $(OUT) $(LDFLAGS)

install: $(OUT)
	hyprctl plugin load $(PWD)/$(OUT)

unload:
	hyprctl plugin unload $(PWD)/$(OUT)

reload: $(OUT)
	-hyprctl plugin unload $(PWD)/$(OUT)
	-hyprctl plugin unload /tmp/$(PLUGIN_NAME)-live.so
	cp $(PWD)/$(OUT) /tmp/$(PLUGIN_NAME)-live.so
	hyprctl plugin load /tmp/$(PLUGIN_NAME)-live.so

clean:
	rm -f $(OUT)

.PHONY: all install unload reload clean
