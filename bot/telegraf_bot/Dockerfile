FROM node:20-alpine
WORKDIR /app

COPY package.json package-lock.json* ./

RUN if [ -f package-lock.json ]; then npm ci --production --no-audit --no-fund; else npm install --production --no-audit --no-fund; fi

COPY . .

CMD ["node", "bot.js"]
