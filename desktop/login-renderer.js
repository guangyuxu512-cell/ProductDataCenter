const form = document.getElementById('login-form')
const username = document.getElementById('username')
const password = document.getElementById('password')
const error = document.getElementById('error')
const submit = document.getElementById('submit')
form.addEventListener('submit', (event) => {
  event.preventDefault()
  error.textContent = ''
  submit.disabled = true
  window.workbenchAuth.submit(username.value, password.value)
})
document.getElementById('cancel').addEventListener('click', () => window.workbenchAuth.cancel())
window.workbenchAuth.onError((message) => {
  error.textContent = message
  submit.disabled = false
  password.focus()
})
