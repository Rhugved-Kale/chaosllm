# For local docker-compose convenience only. The hosted dashboard is a
# static build on Vercel (DESIGN.md 5), not this container.
FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
