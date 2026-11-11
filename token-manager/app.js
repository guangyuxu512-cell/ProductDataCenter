const $ = (selector) => document.querySelector(selector)
const state = { token: '', catalog: [], groups: [], grantGroups: null, grantExpiry: null, records: [], editing: null, epoch: 0 }
const titles = {
  'product.read': '查看商品', 'product.create': '新建商品', 'product.update': '编辑商品',
  'product.delete': '删除商品', 'product.export': '导出商品', 'group.read': '查看分组',
  'group.create': '创建分组', 'group.update': '修改分组', 'group.delete': '删除分组',
  'group.assign': '调整商品分组', 'image.upload': '上传图片', 'precheck.read': '查看预检',
  'precheck.run': '发起预检', 'category.read': '查看类目和属性', 'central.read': '查看中控连接',
  'rpa.read': 'RPA 读取', 'token.read': '查看下级 Token', 'token.create': '发放 Token',
  'token.update': '修改 Token', 'token.revoke': '撤销 Token',
}

function element(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

function showError(node, message) {
  node.textContent = message
  node.hidden = !message
}

function notice(message) {
  const node = $('#notice')
  node.textContent = message
  node.hidden = !message
}

function has(permission) {
  return state.catalog.some((item) => item.id === permission && item.canGrant)
}

async function request(path, { token = state.token, method = 'GET', body } = {}) {
  let response
  try {
    response = await fetch(path, {
      method, cache: 'no-store', credentials: 'omit',
      headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  } catch {
    throw new Error('连接失败，请检查网络后重试。')
  }
  if (!response.ok) {
    let detail
    try { detail = (await response.json()).detail } catch { /* use the status below */ }
    if (response.status === 401) throw new Error('管理凭据无效、已过期或已撤销。')
    if (typeof detail === 'string' && detail.length < 250) throw new Error(detail)
    if (response.status === 403) throw new Error('当前凭据没有此操作的权限。')
    throw new Error(`请求失败（${response.status}），请稍后重试。`)
  }
  if (response.status === 204) return null
  try { return await response.json() } catch { throw new Error('服务返回的数据格式无效。') }
}

function displayTime(value) {
  if (!value) return '长期有效'
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value * 1000))
}

function localDateTime(value) {
  if (!value) return ''
  const date = new Date(value * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function tokenStatus(item) {
  if (item.revokedAt) return '已撤销'
  if (item.expiresAt && item.expiresAt <= Date.now() / 1000) return '已过期'
  return '使用中'
}

function renderList() {
  const list = $('#token-list')
  list.replaceChildren()
  $('#empty-state').hidden = state.records.length !== 0 || !has('token.read')
  $('#list-caption').textContent = has('token.read') ? `共 ${state.records.length} 个，仅显示你有权管理的 Token。` : '当前凭据没有查看 Token 的权限。'
  for (const item of state.records) {
    const card = element('article', 'token-card')
    const top = element('div', 'token-top')
    top.append(element('div', 'token-title', item.name))
    const status = tokenStatus(item)
    top.append(element('span', `badge${status === '使用中' ? '' : ' inactive'}`, status))
    card.append(top)
    card.append(element('div', 'token-meta', `ID：${item.id}`))
    card.append(element('div', 'token-meta', `有效期：${displayTime(item.expiresAt)} · ${item.groupIds === null ? '全部分组' : `${item.groupIds.length} 个分组范围`}`))
    const names = item.permissions.map((id) => titles[id] || id)
    card.append(element('div', 'token-permissions', names.length ? names.join('、') : '无有效权限'))
    if (!item.revokedAt && (has('token.update') || has('token.revoke'))) {
      const actions = element('div', 'token-actions')
      if (has('token.update')) {
        const edit = element('button', 'button secondary', '修改权限')
        edit.type = 'button'
        edit.addEventListener('click', () => openEditor(item))
        actions.append(edit)
      }
      if (has('token.revoke')) {
        const revoke = element('button', 'button danger', '撤销')
        revoke.type = 'button'
        revoke.addEventListener('click', () => revokeToken(item, revoke))
        actions.append(revoke)
      }
      card.append(actions)
    }
    list.append(card)
  }
}

async function refreshList() {
  if (!has('token.read')) { state.records = []; renderList(); return }
  const epoch = state.epoch
  const data = await request('/api/v1/tokens')
  if (epoch !== state.epoch) return
  state.records = Array.isArray(data.items) ? data.items : []
  renderList()
}

async function connect(event) {
  event.preventDefault()
  const button = $('#connect-button')
  const input = $('#manager-token')
  const candidate = input.value.trim()
  if (!candidate) return
  button.disabled = true
  showError($('#login-error'), '')
  const epoch = ++state.epoch
  try {
    const catalog = await request('/api/v1/tokens/permissions', { token: candidate })
    if (epoch !== state.epoch) return
    if (!Array.isArray(catalog.items)) throw new Error('权限清单不可用，请稍后重试。')
    state.token = candidate
    state.catalog = catalog.items
    state.grantGroups = Array.isArray(catalog.groupIds) ? catalog.groupIds : null
    state.grantExpiry = catalog.expiresAt || null
    state.groups = []
    if (has('group.read')) {
      try {
        const groups = await request('/api/v1/product-groups')
        if (epoch !== state.epoch) return
        state.groups = Array.isArray(groups.groups) ? groups.groups : []
      } catch { /* Group IDs can still be entered manually. */ }
    }
    if (epoch !== state.epoch) return
    input.value = ''
    $('#login-panel').hidden = true
    $('#dashboard').hidden = false
    $('#connected-bar').hidden = false
    $('#create-token').hidden = !has('token.create')
    $('#refresh').hidden = !has('token.read')
    await refreshList()
  } catch (error) {
    if (epoch !== state.epoch) return
    if (state.token) { notice(error.message); renderList() } else showError($('#login-error'), error.message)
  } finally {
    button.disabled = false
  }
}

function disconnect() {
  state.epoch++
  Object.assign(state, { token: '', catalog: [], groups: [], grantGroups: null, grantExpiry: null, records: [], editing: null })
  for (const dialog of document.querySelectorAll('dialog[open]')) dialog.close()
  $('#manager-token').value = ''
  $('#login-panel').hidden = false
  $('#dashboard').hidden = true
  $('#connected-bar').hidden = true
  showError($('#login-error'), '')
  notice('')
  renderList()
}

function permissionControls(selected) {
  const root = $('#permissions')
  root.replaceChildren()
  for (const item of state.catalog) {
    const label = element('label', `permission-choice${item.canGrant ? '' : ' disabled'}`)
    const checkbox = element('input')
    checkbox.type = 'checkbox'
    checkbox.value = item.id
    checkbox.checked = item.canGrant && selected.includes(item.id)
    checkbox.disabled = !item.canGrant
    const description = element('span')
    description.append(element('strong', '', titles[item.id] || item.id))
    description.append(document.createTextNode(item.description || item.id))
    label.append(checkbox, description)
    root.append(label)
  }
}

function groupControls(selected) {
  const root = $('#group-options')
  root.replaceChildren()
  const entries = new Map()
  for (const group of state.groups) entries.set(String(group.groupId), group.name)
  for (const id of state.grantGroups || []) if (!entries.has(id)) entries.set(id, id === 'ungrouped' ? '未分组商品' : id)
  for (const id of selected || []) if (!entries.has(id)) entries.set(id, id === 'ungrouped' ? '未分组商品' : id)
  if (state.grantGroups === null || state.grantGroups.includes('ungrouped')) entries.set('ungrouped', '未分组商品')
  for (const [id, name] of entries) {
    if (state.grantGroups !== null && !state.grantGroups.includes(id)) continue
    const label = element('label', 'choice')
    const checkbox = element('input')
    checkbox.type = 'checkbox'
    checkbox.value = id
    checkbox.checked = (selected || []).includes(id)
    label.append(checkbox, document.createTextNode(name))
    root.append(label)
  }
  $('#extra-groups').value = ''
}

function updateGroupVisibility() {
  $('#group-options-wrap').hidden = document.querySelector('input[name="group-mode"]:checked').value !== 'selected'
}

function openEditor(item = null) {
  notice('')
  if (item && item.permissions.some((permission) => !has(permission))) {
    notice('该 Token 的原授权超出当前可分配范围，请使用更高权限的凭据修改。')
    return
  }
  if (item && state.grantGroups !== null && (item.groupIds === null || item.groupIds.some((id) => !state.grantGroups.includes(id)))) {
    notice('该 Token 的分组范围超出当前可分配范围，请使用更高权限的凭据修改。')
    return
  }
  state.editing = item
  $('#editor-title').textContent = item ? '修改 Token' : '创建 Token'
  $('#save-token').textContent = item ? '保存修改' : '创建并显示 Token'
  $('#token-name').value = item?.name || ''
  permissionControls(item?.permissions || ['product.read', 'group.read', 'precheck.read'])
  const allGroups = document.querySelector('input[name="group-mode"][value="all"]')
  const selectedGroups = document.querySelector('input[name="group-mode"][value="selected"]')
  allGroups.disabled = state.grantGroups !== null
  selectedGroups.checked = state.grantGroups !== null || Boolean(item && item.groupIds !== null)
  allGroups.checked = !selectedGroups.checked
  groupControls(item?.groupIds || [])
  updateGroupVisibility()
  const defaultExpiry = Math.min(Math.floor(Date.now() / 1000) + 90 * 86400, state.grantExpiry ? state.grantExpiry - 60 : Infinity)
  $('#expires-at').value = localDateTime(item ? item.expiresAt : defaultExpiry)
  $('#expires-at').max = localDateTime(state.grantExpiry)
  $('#expires-at').dataset.initial = $('#expires-at').value
  showError($('#editor-error'), '')
  $('#editor-dialog').showModal()
  $('#token-name').focus()
}

function setPreset(kind) {
  const read = new Set(['product.read', 'product.export', 'group.read', 'precheck.read', 'category.read', 'central.read'])
  for (const checkbox of $('#permissions').querySelectorAll('input')) {
    if (checkbox.disabled) continue
    checkbox.checked = kind === 'all' || (kind === 'product' && !checkbox.value.startsWith('token.')) || (kind === 'read' && read.has(checkbox.value))
  }
}

function sorted(values) { return [...values].sort().join('\n') }

async function saveToken(event) {
  event.preventDefault()
  const button = $('#save-token')
  const name = $('#token-name').value.trim()
  const permissions = [...$('#permissions').querySelectorAll('input:checked')].map((input) => input.value)
  const selectedMode = document.querySelector('input[name="group-mode"]:checked').value === 'selected'
  const groups = selectedMode ? [...new Set([...$('#group-options').querySelectorAll('input:checked')].map((input) => input.value)
    .concat($('#extra-groups').value.split(/[\s,，]+/).filter(Boolean)))] : null
  const dateValue = $('#expires-at').value
  const expiresAt = dateValue ? Math.floor(new Date(dateValue).getTime() / 1000) : null
  if (!name) { showError($('#editor-error'), '请填写名称。'); return }
  if (!permissions.length) { showError($('#editor-error'), '请至少选择一项权限。'); return }
  if (groups && !groups.length) { showError($('#editor-error'), '请选择至少一个分组，或选择全部分组。'); return }
  if (groups && state.grantGroups !== null && groups.some((id) => !state.grantGroups.includes(id))) { showError($('#editor-error'), '不能分配自己无权访问的分组。'); return }
  if (dateValue && (!Number.isFinite(expiresAt) || expiresAt <= Date.now() / 1000)) { showError($('#editor-error'), '有效期必须晚于现在。'); return }
  if (state.grantExpiry && (!expiresAt || expiresAt > state.grantExpiry)) { showError($('#editor-error'), '有效期不能超过发放者的有效期。'); return }
  const item = state.editing
  let body = { name, permissions, groupIds: groups, expiresAt }
  if (item) {
    body = {}
    if (name !== item.name) body.name = name
    if (sorted(permissions) !== sorted(item.permissions)) body.permissions = permissions
    if ((groups === null) !== (item.groupIds === null) || (groups && sorted(groups) !== sorted(item.groupIds || []))) body.groupIds = groups
    if (dateValue !== $('#expires-at').dataset.initial) body.expiresAt = expiresAt
    if (!Object.keys(body).length) { $('#editor-dialog').close(); return }
  }
  button.disabled = true
  showError($('#editor-error'), '')
  const epoch = state.epoch
  try {
    const result = await request(item ? `/api/v1/tokens/${encodeURIComponent(item.id)}` : '/api/v1/tokens', {
      method: item ? 'PATCH' : 'POST', body,
    })
    if (epoch !== state.epoch) return
    $('#editor-dialog').close()
    if (!item) {
      if (typeof result?.token !== 'string' || !result.token) throw new Error('创建结果未返回完整 Token，请先刷新列表核对。')
      $('#new-secret').value = result.token
      $('#copy-status').textContent = ''
      $('#secret-dialog').showModal()
    } else notice('权限已更新。')
    try { await refreshList() } catch { notice('操作已完成，但列表刷新失败，请手动刷新。') }
  } catch (error) {
    if (epoch !== state.epoch) return
    const message = !item && error.message.startsWith('连接失败') ? `${error.message} 创建结果可能已发生，请先刷新列表核对。` : error.message
    if ($('#editor-dialog').open) showError($('#editor-error'), message)
    else notice(message)
  } finally {
    button.disabled = false
  }
}

async function revokeToken(item, button) {
  if (!window.confirm(`确定撤销“${item.name}”吗？撤销后立即无法使用。`)) return
  button.disabled = true
  const epoch = state.epoch
  try {
    await request(`/api/v1/tokens/${encodeURIComponent(item.id)}`, { method: 'DELETE' })
    if (epoch !== state.epoch) return
    notice('Token 已撤销。')
    try { await refreshList() } catch { notice('Token 已撤销，但列表刷新失败，请手动刷新。') }
  } catch (error) {
    if (epoch === state.epoch) notice(error.message)
  } finally { button.disabled = false }
}

async function copySecret() {
  const input = $('#new-secret')
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')
    await navigator.clipboard.writeText(input.value)
    $('#copy-status').textContent = '已复制，请粘贴到 AI 的安全凭据中。'
  } catch {
    input.focus()
    input.select()
    $('#copy-status').textContent = '请手动复制已选中的 Token。'
  }
}

$('#connect-form').addEventListener('submit', connect)
$('#disconnect').addEventListener('click', disconnect)
$('#create-token').addEventListener('click', () => openEditor())
$('#refresh').addEventListener('click', async () => { try { await refreshList(); notice('列表已刷新。') } catch (error) { notice(error.message) } })
$('#editor-form').addEventListener('submit', saveToken)
for (const radio of document.querySelectorAll('input[name="group-mode"]')) radio.addEventListener('change', updateGroupVisibility)
for (const kind of ['read', 'product', 'all']) $(`#preset-${kind}`).addEventListener('click', () => setPreset(kind))
for (const button of document.querySelectorAll('[data-close]')) button.addEventListener('click', () => document.getElementById(button.dataset.close).close())
$('#secret-dialog').addEventListener('close', () => { $('#new-secret').value = ''; $('#copy-status').textContent = '' })
$('#copy-secret').addEventListener('click', copySecret)
