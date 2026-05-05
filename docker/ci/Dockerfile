FROM ubuntu:24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG OMNETPP_VERSION=6.3.0
ARG OMNETPP_ROOT=/opt/omnetpp-${OMNETPP_VERSION}

ENV DEBIAN_FRONTEND=noninteractive
ENV OMNETPP_ROOT=${OMNETPP_ROOT}
ENV OMNETPP_CONFIGFILE=${OMNETPP_ROOT}/Makefile.inc
ENV PATH=${OMNETPP_ROOT}/bin:${PATH}
ENV PYTHONPATH=${OMNETPP_ROOT}/python
ENV LD_LIBRARY_PATH=${OMNETPP_ROOT}/lib
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PIP_ROOT_USER_ACTION=ignore

RUN apt-get update && apt-get install -y --no-install-recommends \
    bison \
    build-essential \
    ca-certificates \
    clang \
    clang-format \
    clang-tidy \
    cmake \
    curl \
    flex \
    gdb \
    git \
    lcov \
    libclang-rt-18-dev \
    libdw-dev \
    libxml2-dev \
    lld \
    make \
    ninja-build \
    perl \
    pkg-config \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    ripgrep \
    time \
    xz-utils \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL \
    "https://github.com/omnetpp/omnetpp/releases/download/omnetpp-${OMNETPP_VERSION}/omnetpp-${OMNETPP_VERSION}-core.tgz" \
    -o /tmp/omnetpp-core.tgz \
    && tar -xzf /tmp/omnetpp-core.tgz -C /opt \
    && rm /tmp/omnetpp-core.tgz \
    && cd "${OMNETPP_ROOT}" \
    && source setenv \
    && ./configure WITH_QTENV=no WITH_OSG=no WITH_OSGEARTH=no \
    && make -j"$(nproc)" \
    && test "$(cat "${OMNETPP_ROOT}/Version")" = "omnetpp-${OMNETPP_VERSION}" \
    && opp_configfilepath

WORKDIR /work
