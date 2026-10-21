FROM node@sha256:14078204b6bb268c107ceff6d3c43f45a888105e5c2b18b14c32b3409d93a1b0
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts && chown -R node:node /app
COPY --chown=node:node frontend/ ./
USER node
CMD ["npm", "run", "dev"]
