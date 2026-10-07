FROM python:3.12-slim-bookworm
WORKDIR /app
COPY apps/worker-control/controller.py ./controller.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 3002
CMD ["python", "controller.py"]
