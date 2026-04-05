FROM python:3.12-slim

WORKDIR /app

ARG VERSION
RUN pip install --no-cache-dir "workflowvm==${VERSION}"

EXPOSE 8765

ENTRYPOINT ["workflowvm"]
CMD ["serve", "--config", "/config/accounts.yml"]
