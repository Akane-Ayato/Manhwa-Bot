FROM python:3.10

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tor \
    git \
    libavif-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    libfreetype6-dev \
    libopenjp2-7-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

RUN python -m pip install --no-cache-dir --upgrade Pillow

COPY . /app

CMD ["bash", "-c", "tor & exec bash start.sh"]