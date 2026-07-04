# 1단계: Build Stage
FROM node:20-alpine AS build

WORKDIR /app

# ⬇️ 중요: build-time variable 전달
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

COPY package*.json ./

# devDependencies 포함해서 설치 (tsc 포함)
RUN npm ci --include=dev

COPY . .

# TypeScript → tsc -b → Vite build 자동 실행
RUN npm run build

# 2단계: Nginx Runtime
FROM nginx:alpine AS runner
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
