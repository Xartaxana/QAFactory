const handleSubmit = async () => {
  try {
    const result = await signIn('credentials', { email, password })
    if (result?.error) {
      showToast(result.error, 'error')
    } else {
      try {
        await fetch('/api/cart/merge', { method: 'POST' })
      } catch (mergeError) {
        console.error('Cart merge failed:', mergeError)
      }
      showToast('Successfully logged in!', 'success')
    }
  } catch (error) {
    showToast('Login failed.', 'error')
  }
}
