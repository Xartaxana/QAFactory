const addToCart = async (bookId) => {
  const response = await fetch('/api/cart', { method: 'POST', body: JSON.stringify({ bookId }) })
  if (response.ok) showToast('Added', 'success')
}
