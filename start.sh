# ~/Desktop/projects/law11/start.sh

docker compose up -d

cd law11_backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000 &

cd law11_frontend && npm run dev
