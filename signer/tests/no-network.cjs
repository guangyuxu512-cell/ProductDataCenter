global.fetch = async () => { throw new Error('network disabled for synthetic probe') }
for (const name of ['node:http', 'node:https', 'node:net', 'node:dgram']) {
  const mod = require(name)
  for (const key of ['request', 'get', 'connect', 'createConnection', 'createSocket']) {
    if (typeof mod[key] === 'function') mod[key] = () => { throw new Error('network disabled for synthetic probe') }
  }
}
