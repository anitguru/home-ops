FROM python:3.13-alpine AS cocoindex-builder

RUN apk add --no-cache build-base cargo cmake libffi-dev linux-headers openssl-dev perl
RUN python -m pip wheel --no-cache-dir --no-deps \
    --wheel-dir /wheels cocoindex==0.3.9

FROM n8nio/runners:2.30.7

USER root

COPY requirements.txt /tmp/cocoindex-requirements.txt
COPY --from=cocoindex-builder /wheels /tmp/cocoindex-wheels
RUN cd /opt/runners/task-runner-python \
    && uv pip install --python .venv/bin/python --no-cache \
        --find-links /tmp/cocoindex-wheels \
        -r /tmp/cocoindex-requirements.txt \
    && rm -rf /tmp/cocoindex-requirements.txt /tmp/cocoindex-wheels

COPY n8n-task-runners.json /etc/n8n-task-runners.json

USER runner
