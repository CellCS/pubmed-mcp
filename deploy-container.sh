#!/bin/bash

docker build -t pubmed-mcp:latest .

docker run -d --name pubmed-mcp \
  -p 8001:8000 \
  --restart unless-stopped \
  --env-file ./.env \
  pubmed-mcp:latest