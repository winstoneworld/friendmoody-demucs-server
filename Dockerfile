# friendmoody Demucs Server
# Python 3.11 + Demucs htdemucs_ft + ffmpeg
# Railway 배포용

FROM python:3.11-slim

# 시스템 패키지 (ffmpeg + 오디오 라이브러리)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 의존성 먼저 설치 (캐시 최적화)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# htdemucs_ft 모델 사전 다운로드 (빌드 시점에 캐싱 → 콜드스타트 단축)
RUN python3 -c "from demucs.pretrained import get_model; get_model('htdemucs_ft')" || true

# 앱 소스 복사
COPY . .

EXPOSE 5001

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5001", "--workers", "1", "--timeout", "660", "--log-level", "info"]
