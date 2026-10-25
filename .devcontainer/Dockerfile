FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

USER root
# SuperKart does not use Yarn. Remove its unused APT source before Features
# install Docker, so a stale upstream Yarn signing key cannot block apt update.
# Debian and Docker package signature verification remain enabled.
RUN rm -f /etc/apt/sources.list.d/yarn.list

USER vscode
