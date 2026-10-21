# Elasticsearch 9.x + IK 中文分词插件（单阶段：ES 镜像自带 curl，直接下载安装）
ARG ES_VERSION=9.1.2
ARG IK_VERSION=9.1.2

FROM docker.elastic.co/elasticsearch/elasticsearch:${ES_VERSION}

ARG IK_VERSION
USER root
RUN curl -fsSL -o /tmp/ik.zip "https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-${IK_VERSION}.zip" \
    && bin/elasticsearch-plugin install --batch file:///tmp/ik.zip \
    && rm -f /tmp/ik.zip \
    && chown -R elasticsearch:elasticsearch /usr/share/elasticsearch
USER elasticsearch