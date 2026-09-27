# MCP server image. Coolify builds this from the repo; the files must live INSIDE the image
# because a bind mount of the repo does not exist on the deployment host.
FROM python:3.12-alpine
WORKDIR /app
COPY mcp_server.py ./
COPY scripts/scrape.py ./scripts/
ENV SCRAPER_OUT_DIR=/tmp
CMD ["python", "mcp_server.py", "--http"]
