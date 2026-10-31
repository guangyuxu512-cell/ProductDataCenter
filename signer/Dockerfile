FROM node:24-alpine

WORKDIR /app
ENV NODE_ENV=production PORT=8787
COPY server.js sign_once.js ./
COPY vendor ./vendor
USER node
EXPOSE 8787
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
  CMD ["node", "-e", "const h=require('http');const r=h.get({host:'127.0.0.1',port:process.env.PORT||8787,path:'/health',timeout:2000},s=>process.exit(s.statusCode===200?0:1));r.on('error',()=>process.exit(1));r.on('timeout',()=>{r.destroy();process.exit(1)});"]
CMD ["node", "server.js"]
