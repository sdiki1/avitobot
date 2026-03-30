ARG NODE_IMAGE=node:20-alpine
FROM ${NODE_IMAGE}

WORKDIR /app

COPY package*.json /app/
RUN npm install

COPY . /app

EXPOSE 3000

CMD ["npm", "start"]
