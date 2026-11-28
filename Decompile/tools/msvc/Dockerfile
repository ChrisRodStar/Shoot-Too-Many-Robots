# 32-bit Debian + Wine 8, used only to run Visual C++ 2008 (cl.exe 15.00).
# Build:  docker build --platform linux/386 -t smr-msvc9 Decompile/tools/msvc
FROM --platform=linux/386 debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        wine wine32 cabextract p7zip-full msitools xvfb xauth \
        ca-certificates curl file binutils \
    && rm -rf /var/lib/apt/lists/*

ENV WINEPREFIX=/msvc/wine \
    WINEARCH=win32 \
    WINEDEBUG=-all
WORKDIR /msvc
ENTRYPOINT ["/bin/bash"]
