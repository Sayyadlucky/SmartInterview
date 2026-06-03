FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    chromium \
    fonts-liberation \
    libpq-dev \
    pkg-config \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    python3-dev \
    libcairo2-dev \
    libcairo2 \
    libpango1.0-dev \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-dev \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN python -m pip install --upgrade pip wheel "setuptools==80.9.0"
RUN python -m pip install --no-cache-dir -r requirements.txt
RUN python -m pip install --no-cache-dir --force-reinstall "setuptools==80.9.0"
RUN python -m pip show setuptools && python -m pip check
RUN python -c "import pkg_resources; import face_recognition_models; import face_recognition; import dlib; print('face_recognition runtime probe ok', dlib.__version__)"

COPY . /app/

RUN python manage.py collectstatic --noinput || true

CMD exec gunicorn smartInterview.wsgi:application --bind 0.0.0.0:$PORT
